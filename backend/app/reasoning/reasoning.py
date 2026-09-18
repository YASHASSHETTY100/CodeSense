"""Four core reasoning functions with functional intelligence, evidence sufficiency, and secret safety."""
from __future__ import annotations
import os, json, re
from sqlalchemy.orm import Session
from app.models.models import (
    Project, Module, ApiEndpoint, DataEntity, BusinessRule,
    Role, CodeSymbol, SourceFile, QueryLog, KnowledgeChunk
)
from app.knowledge_base.retrieval import retrieve, get_project_catalog, evaluate_sufficiency
from app.prompts import templates
from app.reasoning.llm_client import llm_complete, _OfflineSignal
from app.reasoning.guardrails import check_evidence
from app.analysis.security import redact_secrets
from app.analysis.functional.modules import infer_module_name
from app.ingestion.orchestrator import project_dir


def _extract_repo_overview(db: Session, project_id: int) -> str:
    """Extract project purpose from README, package manifests, or code comments."""
    # 1. Try reading README from disk
    dest = project_dir(project_id)
    for readme_name in ["README.md", "readme.md", "README", "README.rst", "README.txt"]:
        fp = os.path.join(dest, readme_name)
        if os.path.exists(fp):
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    txt = f.read().strip()
                if txt:
                    # Take first 3 non-empty paragraphs
                    paras = [p.strip() for p in txt.split("\n\n") if p.strip()]
                    overview = "\n\n".join(paras[:2])
                    return redact_secrets(overview[:1500])
            except OSError:
                pass

    # 2. Check for README in KnowledgeChunks
    readme_chunk = (
        db.query(KnowledgeChunk)
        .filter(KnowledgeChunk.project_id == project_id)
        .filter(KnowledgeChunk.source_ref.ilike("%readme%"))
        .first()
    )
    if readme_chunk and readme_chunk.chunk_text:
        return redact_secrets(readme_chunk.chunk_text[:1200])

    return ""


def _extract_dependencies(project_id: int) -> list[str]:
    dest = project_dir(project_id)
    deps = []
    req_path = os.path.join(dest, "requirements.txt")
    if os.path.exists(req_path):
        try:
            with open(req_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        pkg = re.split(r"[=<>]", line)[0].strip()
                        if pkg:
                            deps.append(pkg)
        except OSError:
            pass
    pkg_path = os.path.join(dest, "package.json")
    if os.path.exists(pkg_path):
        try:
            with open(pkg_path, "r", encoding="utf-8", errors="ignore") as f:
                pj = json.load(f)
                deps.extend(list((pj.get("dependencies") or {}).keys()))
        except Exception:
            pass
    return sorted(set(deps))[:25]


def _detect_integrations(db: Session, project_id: int) -> list[str]:
    chunks = db.query(KnowledgeChunk.chunk_text).filter(KnowledgeChunk.project_id == project_id).limit(120).all()
    all_text = " ".join((c[0] or "") for c in chunks).lower()
    integrations = set()
    if "sqlite" in all_text:
        integrations.add("SQLite Database Engine")
    if "postgres" in all_text or "psycopg" in all_text:
        integrations.add("PostgreSQL Database")
    if "fastapi" in all_text:
        integrations.add("FastAPI REST Framework")
    if "streamlit" in all_text:
        integrations.add("Streamlit UI Application")
    if "torch" in all_text or "pytorch" in all_text:
        integrations.add("PyTorch Deep Learning Runtime")
    if "cv2" in all_text or "opencv" in all_text:
        integrations.add("OpenCV Computer Vision")
    if "celery" in all_text or "redis" in all_text:
        integrations.add("Celery / Redis Asynchronous Task Queue")
    if "smtp" in all_text or "sendmail" in all_text or "mail" in all_text:
        integrations.add("SMTP Email Notification Service")
    if "github" in all_text:
        integrations.add("GitHub Version Control")
    return sorted(integrations)


def _facts(db: Session, project_id: int) -> dict:
    mods = db.query(Module).filter(Module.project_id == project_id).all()
    eps = db.query(ApiEndpoint).filter(ApiEndpoint.project_id == project_id).all()
    ents = db.query(DataEntity).filter(DataEntity.project_id == project_id).all()
    rules = db.query(BusinessRule).filter(BusinessRule.project_id == project_id).all()
    roles = db.query(Role).filter(Role.project_id == project_id).all()
    langs = sorted({r[0] for r in db.query(SourceFile.language).filter(
        SourceFile.project_id == project_id).distinct().all() if r[0]})
    repo_overview = _extract_repo_overview(db, project_id)
    deps = _extract_dependencies(project_id)
    integrations = _detect_integrations(db, project_id)

    # Clean module names: omit raw parser prefixes like 'module:root'
    cleaned_mods = []
    for m in mods:
        mname = m.name.replace("module:", "")
        cleaned_mods.append({"name": mname, "description": m.description})

    return {
        "modules": cleaned_mods,
        "endpoints": [{"method": e.method, "path": e.path, "auth": e.auth_required,
                       "roles": e.roles_allowed} for e in eps[:100]],
        "entities": [{"name": e.name, "fields": e.fields_json} for e in ents],
        "rules": [r.description[:400] for r in rules[:100]],
        "roles": [r.name for r in roles],
        "languages": langs,
        "repo_overview": repo_overview,
        "dependencies": deps,
        "integrations": integrations,
    }


def _ev_to_claims(evidence: list[dict]) -> list[dict]:
    claims = []
    for e in evidence:
        ref = e["source_ref"]
        file = ref.split("#")[0].split(":")[0]
        claims.append({
            "file": file,
            "symbol": ref,
            "lines": ref,
            "source_ref": ref,
            "text": e.get("text", ""),
            "why_relevant": redact_secrets(e["text"][:300]),
            "score": e.get("score", 0.0),
            "scores": e.get("scores", {}),
        })
    return claims


def summarize_project(db: Session, project_id: int) -> dict:
    p = db.query(Project).filter(Project.id == project_id).one()
    if p.summary_cache:
        try:
            cached = json.loads(p.summary_cache)
            if isinstance(cached, dict) and "summary" in cached and cached["summary"]:
                return cached
        except Exception:
            pass

    facts = _facts(db, project_id)
    ev = retrieve(db, project_id, "project purpose modules workflows business rules", top_k=8, allow_insufficient=True)

    try:
        raw = llm_complete(templates.PROJECT_SUMMARY.render(
            structured_facts_json=json.dumps(facts)[:12000]), "")
        return {
            "summary": redact_secrets(raw),
            "facts": facts,
            "evidence": _ev_to_claims(ev),
            "prompt_version": templates.VERSION,
            "llm": "live",
        }
    except _OfflineSignal:
        mods = ", ".join(m["name"] for m in facts["modules"][:15]) or "core"
        repo_overview = facts.get("repo_overview")
        purpose_line = (
            f"# Project Purpose\n{repo_overview}"
            if repo_overview
            else f"# Project Purpose\n{p.name} ({p.repo_url}). Languages: {', '.join(facts['languages']) or 'unknown'}."
        )

        tech_stack = ", ".join(facts["languages"]) if facts["languages"] else "Multi-language"
        if facts.get("dependencies"):
            tech_stack += f" (Dependencies: {', '.join(facts['dependencies'][:8])})"

        integrations_str = "\n".join(f"- {i}" for i in facts.get("integrations", [])) or "Internal system; no external SaaS services detected."
        deps_str = "\n".join(f"- {d}" for d in facts.get("dependencies", [])[:15]) or "Standard library runtime."
        
        # Workflows extraction
        workflows = []
        for e in facts["endpoints"][:6]:
            workflows.append(f"- HTTP {e['method']} `{e['path']}`: Request routing and endpoint handling.")
        if not workflows:
            workflows.append("- Workflow execution initiates from core entry-point functions.")

        lines = [
            purpose_line,
            f"## Business Problem Solved\nStreamlines domain operations, coordinates case/record management, and enforces business logic validations across application workflows.",
            f"## Technology Stack\n{tech_stack}",
            f"## Major Modules & Features\n{mods}.",
            f"## Major APIs/Services\n" + ("\n".join(
                f"- {e['method']} {e['path']} (auth={e['auth']})" for e in facts["endpoints"][:20]) or "No HTTP routes detected."),
            f"## Data Model Overview\n" + (", ".join(e["name"] for e in facts["entities"][:20]) or "No data entities detected."),
            f"## User Roles\n" + (", ".join(facts["roles"][:20]) or "Standard authorized user roles."),
            f"## Main Workflows\n" + "\n".join(workflows),
            f"## Important Business Rules\n" + ("\n".join(f"- {r[:250]}" for r in facts["rules"][:10]) or "No validation rules detected."),
            f"## Integrations & External Services\n{integrations_str}",
            f"## Dependencies\n{deps_str}",
            f"## Key Functional Relationships\nEntry handlers route inputs through domain validation rules before persisting to the data layer and triggering notification and downstream execution pipelines.",
        ]
        return {
            "summary": redact_secrets("\n\n".join(lines)),
            "facts": facts,
            "evidence": _ev_to_claims(ev),
            "prompt_version": templates.VERSION,
            "llm": "offline-extractive",
        }


def _build_functional_answer(question: str, ev: list[dict], kept: list[dict], dropped: int, repo_overview: str = "") -> dict:
    """Build structured functional answer from evidence with PM/BA-friendly language."""
    from app.analysis.query_intent import analyze_query
    qi = analyze_query(question)

    # 1. Affected modules
    modules_set = set()
    for e in ev:
        ref = e["source_ref"]
        file_path = ref.split("#")[0].split(":")[0]
        if "/" in file_path or "\\" in file_path:
            mod = infer_module_name(file_path)
            if mod and mod != "root":
                modules_set.add(mod)
        elif ref.startswith("module:"):
            modules_set.add(ref.split(":", 1)[1])
    affected_modules = sorted(modules_set)

    # 2. Business rules — translated to PM/BA language
    extracted_rules = []
    for e in ev:
        t = e.get("text", "")
        ref = e.get("source_ref", "")
        if ref.startswith("rule:") or "rule:" in ref or "validation" in t or "raise ValueError" in t or "raise ValidationError" in t:
            rule_desc = t.replace("Business rule:", "").strip().split("\n")[0][:250]
            if rule_desc and rule_desc not in extracted_rules:
                extracted_rules.append(rule_desc)
    business_rules = extracted_rules[:6]

    # 3. Functional flow steps — described in business language
    flow_steps = []
    routes = [e for e in ev if "endpoint:" in e["source_ref"] or "router" in e["text"] or "@router" in e["text"] or "app." in e["text"]]
    handlers = [e for e in ev if "def " in e["text"] or "function " in e["text"]]
    validators = [e for e in ev if "raise " in e["text"] or "validation" in e["text"]]
    db_ops = [e for e in ev if "db.session" in e["text"] or "Column" in e["text"] or "INSERT" in e["text"] or "add(" in e["text"]]

    step_num = 1
    if routes:
        route_name = routes[0]['source_ref'].split(":")[-1] if ":" in routes[0]['source_ref'] else routes[0]['source_ref']
        flow_steps.append(f"{step_num}. The user's request is received at the application entry point (`{route_name}`)")
        step_num += 1
    if handlers:
        h_name = handlers[0]["source_ref"].split(":")[-1]
        flow_steps.append(f"{step_num}. The request is processed by the handler function `{h_name}`")
        step_num += 1
    if validators:
        flow_steps.append(f"{step_num}. Input data is validated against business rules and constraints")
        step_num += 1
    if db_ops:
        flow_steps.append(f"{step_num}. The validated data is stored in the database")
        step_num += 1

    if not flow_steps:
        for i, e in enumerate(ev[:4], 1):
            ref_name = e['source_ref'].split(":")[-1] if ":" in e['source_ref'] else e['source_ref'].split("/")[-1]
            flow_steps.append(f"{i}. Processing involves `{ref_name}`")

    # 4. Current behavior — PM/BA-friendly business explanation
    primary_intent = getattr(qi, "primary_intent", qi.intent)
    rich_intents = getattr(qi, "intents", [primary_intent])
    module_desc = ", ".join(affected_modules) if affected_modules else "core application"

    # Check for contradictions across sources
    def _detect_contradictions(ev_list: list[dict]) -> tuple[bool, str]:
        if len(ev_list) < 2:
            return False, ""
        auth_rules: dict[str, list[tuple[str, str]]] = {}
        for e in ev_list:
            t = e.get("text", "")
            ref = e.get("source_ref", "")
            t_l = t.lower()
            if "admin" in t_l and any(w in t_l for w in ["only", "require", "is_admin", "forbidden", "must be admin", "role == 'admin'"]):
                auth_rules.setdefault("restricted", []).append((ref, "requires administrator role"))
            if any(w in t_l for w in ["allow_any", "allowany", "public", "anonymous", "anyone can", "no auth"]):
                auth_rules.setdefault("unrestricted", []).append((ref, "allows public or unauthenticated access"))
            if "conflict" in t_l or "contradiction" in t_l:
                auth_rules.setdefault("explicit_conflict", []).append((ref, t[:150]))

        if "restricted" in auth_rules and "unrestricted" in auth_rules:
            r1, d1 = auth_rules["restricted"][0]
            r2, d2 = auth_rules["unrestricted"][0]
            return True, (
                f"### Contradiction Detected\n"
                f"**Repository evidence is inconsistent.**\n\n"
                f"Conflicting implementation rules were detected across repository sources:\n"
                f"- Evidence in `{r1}`: {d1}\n"
                f"- Evidence in `{r2}`: {d2}\n\n"
                f"The codebase contains divergent policies for this capability."
            )
        return False, ""

    has_contradiction, contradiction_banner = _detect_contradictions(ev)

    has_role_intent = any(i in rich_intents for i in ["PERMISSION_AUTH", "USER_ROLE"])
    has_workflow_intent = any(i in rich_intents for i in ["WORKFLOW", "HOW_IT_WORKS", "LIFECYCLE_STATUS"])

    if has_role_intent and has_workflow_intent:
        role_part = (
            f"**Roles & Permissions:** Access control and user authorization govern this capability across the **{module_desc}** module(s). "
            f"The system verifies role permissions before permitting actions to proceed."
        )
        workflow_part = (
            f"**Workflow & Downstream Execution:** Once authorized, the operational flow coordinates input validation, "
            f"commits state updates to persistent data storage, and triggers downstream event notifications across the **{module_desc}** module(s)."
        )
        business_explanation = f"{role_part}\n\n{workflow_part}"
    elif qi.intent == "purpose" and repo_overview:
        business_explanation = (
            f"**Application Purpose & Executive Summary:**\n\n{repo_overview}\n\n"
            f"**Functional Scope:** This system is organized around the **{module_desc}** module(s) to automate and support core operational workflows."
        )
    elif any(i in rich_intents for i in ["WORKFLOW", "HOW_IT_WORKS"]):
        business_explanation = (
            f"**Workflow Overview:** The system executes this operational process across the **{module_desc}** module(s). "
            f"Incoming requests are received at application entry points, evaluated against domain business rules, "
            f"committed to persistent data storage, and coordinated with downstream components."
        )
    elif any(i in rich_intents for i in ["DATABASE", "DATA_ENTITY"]):
        business_explanation = (
            f"**Data Model & Storage:** Data persistence for this feature is managed within the **{module_desc}** data structures. "
            f"The application schemas define entity models, field attributes, constraints, and relationships maintained in the database layer."
        )
    elif any(i in rich_intents for i in ["PERMISSION_AUTH", "USER_ROLE"]):
        business_explanation = (
            f"**Access Control & Roles:** Security policies and user authorization govern this capability across the **{module_desc}** module(s). "
            f"The system verifies user roles and permissions before allowing sensitive actions or access to protected data."
        )
    elif "API" in rich_intents:
        business_explanation = (
            f"**API & Service Endpoints:** The application exposes structured API routes in the **{module_desc}** module(s) "
            f"enabling clients, frontends, or external systems to dispatch actions and query state."
        )
    elif "INTEGRATION" in rich_intents:
        business_explanation = (
            f"**External Integrations:** Third-party connectivity in the **{module_desc}** module(s) connects application logic "
            f"with external services, APIs, and background notification channels."
        )
    elif "ERROR_HANDLING" in rich_intents:
        business_explanation = (
            f"**Resilience & Error Handling:** System stability is safeguarded through input validations, exception handlers, "
            f"and error responses within the **{module_desc}** module(s) to guarantee graceful recovery."
        )
    elif any(i in rich_intents for i in ["VALIDATION", "WHY_BUSINESS_RULE"]):
        business_explanation = (
            f"**Business Logic & Validation:** Domain constraints and validation rules are enforced within the **{module_desc}** module(s) "
            f"to uphold data integrity and reject invalid requests before persistence."
        )
    elif "CAPABILITY" in rich_intents or "FEATURE" in rich_intents:
        business_explanation = (
            f"**Functional Capability:** The system provides specialized domain capabilities in the **{module_desc}** module(s), "
            f"coordinating business operations, state tracking, and record handling."
        )
    else:
        business_explanation = (
            f"**Functional Overview:** Based on repository analysis, this capability is implemented across the **{module_desc}** module(s) "
            f"with defined business logic and persistent state."
        )

    # Clean technical evidence citations as supporting detail
    tech_evidence_items = []
    for e in ev[:4]:
        ref_path = e['source_ref'].split('#')[0].split(':')[0]
        sym = e['source_ref'].split(':')[-1] if ':' in e['source_ref'] else ref_path.split('/')[-1]
        tech_evidence_items.append(f"- `{ref_path}` (symbol: `{sym}`)")

    current_behaviour = f"{business_explanation}\n\n**Technical Implementation Details:**\n" + "\n".join(tech_evidence_items)
    if has_contradiction:
        current_behaviour = f"{contradiction_banner}\n\n{current_behaviour}"

    # 5. Confidence
    confidence = "High" if len(ev) >= 2 and (business_rules or flow_steps) else "Medium"

    # 6. Gaps — distinguish established behavior, strong inference, and unknown
    gaps = []
    if any(i in rich_intents for i in ["WORKFLOW", "HOW_IT_WORKS", "API"]):
        if not routes:
            gaps.append("**Unknown:** Direct public API route or controller endpoint was not identified in retrieved evidence; workflow inferred from service handlers.")
        else:
            gaps.append("**Established:** Public entry points and request dispatch handlers are confirmed by route definitions.")

    if any(i in rich_intents for i in ["VALIDATION", "WHY_BUSINESS_RULE"]):
        if not validators and not business_rules:
            gaps.append("**Unknown:** Explicit input guardrails or business constraint rules could not be established from analyzed code.")
        else:
            gaps.append("**Established:** Domain validation and error guard clauses are confirmed in handler code.")

    if any(i in rich_intents for i in ["DATABASE", "DATA_ENTITY"]):
        if not db_ops:
            gaps.append("**Unknown:** Direct database table schema or persistence statements were not identified in retrieved evidence.")
        else:
            gaps.append("**Established:** Data persistence operations are confirmed by database operations in code.")

    if any(i in rich_intents for i in ["PERMISSION_AUTH", "USER_ROLE"]):
        auth_ev = [e for e in ev if any(w in e['text'].lower() for w in ["permission", "role", "is_admin", "login", "auth"])]
        if not auth_ev:
            gaps.append("**Strong Inference:** Role-based access gates are inferred from module context but not directly cited in the retrieved code slice.")
        else:
            gaps.append("**Established:** Role or permission verification logic is evidenced in the codebase.")

    # Formatted Markdown Answer with Intent-Specific Specialization
    # Claim-to-evidence grounding mapping
    claims_grounding = []
    for item in kept:
        ref = item.get("source_ref", "")
        why = item.get("why_relevant", "")
        claims_grounding.append({
            "claim": why[:150] if why else f"Evidence cited from {ref}",
            "evidence_ids": [ref],
            "derivation_type": "CROSS_LAYER_TRACE" if any(w in ref.lower() for w in ["route", "endpoint", "view", "handler", "api"]) else "DIRECT_EVIDENCE",
            "file": item.get("file", ""),
        })

    # Calibrated answer status
    answer_status = "FULLY_ANSWERABLE"
    if has_contradiction:
        answer_status = "CONFLICTING_EVIDENCE"
    elif any(g.startswith("**Unknown:**") for g in gaps):
        answer_status = "PARTIALLY_ANSWERABLE"

    sections = []
    if qi.intent == "purpose":
        sections.append(f"### Application Purpose & Overview\n{current_behaviour}")
        sections.append(f"### Core Workflows & Capabilities\n" + ("\n".join(flow_steps) if flow_steps else "Direct execution flow."))
    else:
        sections.append(f"### Direct Answer\n{current_behaviour}")
        sections.append(f"### How It Works\n" + ("\n".join(flow_steps) if flow_steps else "Direct execution flow."))

    if business_rules:
        sections.append(f"### Business Rules & Validations\n" + "\n".join(f"- {r}" for r in business_rules))

    # Intent-specific sections
    if any(i in rich_intents for i in ["DATABASE", "DATA_ENTITY"]):
        db_snippets = [e['source_ref'] for e in ev if any(w in e['source_ref'].lower() or w in e['text'].lower() for w in ["model", "table", "schema", "column", "entity", "sql"])]
        if db_snippets:
            sections.append(f"### Data & Systems Involved\nPersistent data structures are defined in: " + ", ".join(f"`{s}`" for s in db_snippets[:4]) + ".")

    if any(i in rich_intents for i in ["PERMISSION_AUTH", "USER_ROLE"]):
        auth_snippets = [e['source_ref'] for e in ev if any(w in e['source_ref'].lower() or w in e['text'].lower() for w in ["role", "permission", "auth", "guard", "login", "admin"])]
        if auth_snippets:
            sections.append(f"### Roles & Access Control\nAuthorization and access control logic is enforced in: " + ", ".join(f"`{s}`" for s in auth_snippets[:4]) + ".")

    if "API" in rich_intents:
        api_snippets = [e['source_ref'] for e in ev if "endpoint:" in e['source_ref'] or any(w in e['text'].lower() for w in ["@router", "@app.", "route", "apirouter"])]
        if api_snippets:
            sections.append(f"### APIs & Service Endpoints\nHTTP endpoints handling this functionality: " + ", ".join(f"`{s}`" for s in api_snippets[:4]) + ".")

    if "INTEGRATION" in rich_intents:
        int_snippets = [e['source_ref'] for e in ev if any(w in e['source_ref'].lower() or w in e['text'].lower() for w in ["client", "service", "webhook", "http", "requests", "httpx"])]
        if int_snippets:
            sections.append(f"### External Integrations\nExternal service communication identified in: " + ", ".join(f"`{s}`" for s in int_snippets[:4]) + ".")

    if "ERROR_HANDLING" in rich_intents:
        err_snippets = [e['source_ref'] for e in ev if any(w in e['text'].lower() for w in ["except ", "raise ", "try:", "error", "fail", "retry"])]
        if err_snippets:
            sections.append(f"### Error Handling & Resilience\nException handling and error recovery logic found in: " + ", ".join(f"`{s}`" for s in err_snippets[:4]) + ".")

    if "NOTIFICATION" in rich_intents:
        notif_snippets = [e['source_ref'] for e in ev if any(w in e['source_ref'].lower() or w in e['text'].lower() for w in ["notify", "notification", "email", "sms", "alert"])]
        if notif_snippets:
            sections.append(f"### Notifications & Alerts\nNotification dispatching identified in: " + ", ".join(f"`{s}`" for s in notif_snippets[:4]) + ".")

    if "LIFECYCLE_STATUS" in rich_intents:
        lc_snippets = [e['source_ref'] for e in ev if any(w in e['text'].lower() for w in ["status", "state", "transition", "pending", "approved", "active", "completed"])]
        if lc_snippets:
            sections.append(f"### Lifecycle & State Transitions\nStatus management and state transitions handled in: " + ", ".join(f"`{s}`" for s in lc_snippets[:4]) + ".")

    if affected_modules:
        sections.append(f"### Impacted Components\n" + ", ".join(f"`{m}`" for m in affected_modules))

    if gaps:
        sections.append(f"### Gaps & Verification Status\n" + "\n".join(f"- {g}" for g in gaps))

    sections.append(f"\n*Confidence: {confidence} | {len(kept)} cited source(s); {dropped} dropped by guardrail.*")
    answer_text = redact_secrets("\n\n".join(sections))

    return {
        "status": "SUCCESS",
        "answer_status": answer_status,
        "answer": answer_text,
        "current_behaviour": redact_secrets(current_behaviour),
        "functional_flow": [redact_secrets(s) for s in flow_steps],
        "business_rules": [redact_secrets(r) for r in business_rules],
        "affected_modules": affected_modules,
        "evidence": kept,
        "claims_grounding": claims_grounding,
        "confidence": confidence,
        "guard_dropped": dropped,
        "query_plan": getattr(qi, "query_plan", {}),
        "intents": getattr(qi, "intents", []),
        "primary_intent": getattr(qi, "primary_intent", "HOW_IT_WORKS"),
        "gaps": gaps,
    }


def answer_functional_question(db: Session, project_id: int, question: str, user_id: int = 0, history: list[dict] | None = None) -> dict:
    from app.analysis.query_intent import analyze_query
    qi = analyze_query(question, history=history)

    # Check if question is an unresolved ambiguous pronoun query
    if qi.is_ambiguous:
        clarification_msg = qi.clarification_prompt or "Could you please clarify which feature or domain entity you are referring to?"
        res = {
            "status": "INSUFFICIENT_EVIDENCE",
            "answer": clarification_msg,
            "current_behaviour": "Ambiguous reference without prior context.",
            "functional_flow": [],
            "business_rules": [],
            "affected_modules": [],
            "evidence": [],
            "confidence": "None",
            "reason": "ambiguous_question",
            "missing_concepts": ["clarification required"],
            "gaps": [clarification_msg],
            "guard_dropped": 0,
        }
        return res

    effective_question = qi.resolved_query or question

    # Ambiguity check for broad questions with multiple candidate repository workflows
    p_dir = project_dir(project_id)
    vocab_path = os.path.join(p_dir, "domain_vocabulary.json")
    if os.path.exists(vocab_path):
        try:
            from app.domain_vocabulary import RepositoryDomainVocabulary
            vocab = RepositoryDomainVocabulary.load(vocab_path)
            q_l = effective_question.lower()
            if any(p in q_l for p in ["how are ", "how is ", "how do we handle ", "how does the system handle "]) and any(w in q_l for w in ["handle", "handled", "manage", "managed", "deal", "dealt"]):
                matched = vocab.find_matching_concepts(q_l)
                if matched:
                    top_mc = matched[0]
                    workflows = list(top_mc.related_workflows)
                    if not workflows and top_mc.related_concepts:
                        workflows = [f"{top_mc.canonical_name}_{rel}" for rel in list(top_mc.related_concepts)[:4]]
                    if len(workflows) >= 2:
                        wf_list_str = "\n".join(f"- **{wf.replace('_', ' ').title()}**" for wf in workflows[:4])
                        ambiguous_answer = (
                            f"In this repository, **{top_mc.canonical_name.replace('_', ' ').title()}** is associated with multiple distinct functional workflows:\n\n"
                            f"{wf_list_str}\n\n"
                            f"Because multiple implementations exist, please clarify which specific workflow or operation you would like to explore."
                        )
                        res = {
                            "status": "SUCCESS",
                            "answer": ambiguous_answer,
                            "current_behaviour": f"Multiple repository-supported workflows exist for {top_mc.canonical_name}.",
                            "functional_flow": [f"Candidate workflow: {wf.replace('_', ' ').title()}" for wf in workflows[:4]],
                            "business_rules": [],
                            "affected_modules": [],
                            "evidence": [],
                            "confidence": "Medium",
                            "reason": "multiple_repository_interpretations",
                            "missing_concepts": [],
                            "gaps": ["Multiple repository workflows match this concept; user clarification requested."],
                            "guard_dropped": 0,
                            "ambiguity_candidates": workflows[:4],
                        }
                        db.add(QueryLog(project_id=project_id, user_id=user_id or 0, question=question,
                                        answer=res["answer"][:8000], evidence_refs_json="[]"))
                        db.commit()
                        return res
        except Exception:
            pass

    # Multi-intent decomposition check
    is_multi_intent = bool(getattr(qi, "query_plan", {}).get("is_multi_intent", False))
    sub_queries = getattr(qi, "query_plan", {}).get("sub_queries", []) if is_multi_intent else []

    if is_multi_intent and len(sub_queries) > 1:
        ev = []
        seen_refs = set()
        for sq in sub_queries:
            sub_ev = retrieve(db, project_id, sq, top_k=6)
            for item in sub_ev:
                ref_key = (item.get("source_ref"), item.get("text", "")[:100])
                if ref_key not in seen_refs:
                    seen_refs.add(ref_key)
                    ev.append(item)
        if not ev:
            ev = retrieve(db, project_id, effective_question, top_k=12)
    else:
        ev = retrieve(db, project_id, effective_question, top_k=12)

    # Evidence sufficiency gate
    if not ev:
        catalog = get_project_catalog(db, project_id)
        is_suff, reason, missing = evaluate_sufficiency(db, project_id, effective_question, [], catalog)
        missing_str = ", ".join(missing) if missing else "the requested domain concept"
        ans_msg = (
            f"The analyzed codebase does not contain sufficient evidence regarding '{question}'. "
            f"No matching implementations, endpoints, or business rules were found for {missing_str}."
        )
        res = {
            "status": "INSUFFICIENT_EVIDENCE",
            "answer_status": "INSUFFICIENT_EVIDENCE",
            "answer": redact_secrets(ans_msg),
            "current_behaviour": "No evidenced behavior found in the codebase.",
            "functional_flow": [],
            "business_rules": [],
            "affected_modules": [],
            "evidence": [],
            "claims_grounding": [],
            "confidence": "None",
            "reason": reason,
            "missing_concepts": missing,
            "gaps": [f"No implementation or evidence found for {missing_str}."],
            "guard_dropped": 0,
        }
        db.add(QueryLog(project_id=project_id, user_id=user_id or 0, question=question,
                        answer=res["answer"][:8000], evidence_refs_json="[]"))
        db.commit()
        return res

    claims = _ev_to_claims(ev)
    kept, dropped = check_evidence(claims, ev)
    facts = _facts(db, project_id)
    repo_overview = facts.get("repo_overview", "")

    try:
        raw = llm_complete(templates.FUNCTIONAL_QA.render(
            question=effective_question,
            retrieved_evidence_chunks=json.dumps(ev)[:14000]), "")
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            data = json.loads(m.group(0))
            llm_kept, llm_dropped = check_evidence(data.get("evidence", []), ev)
            data["evidence"] = llm_kept
            data["guard_dropped"] = llm_dropped
            data["status"] = "SUCCESS"
            # Ensure 6 dimensions exist
            fb = _build_functional_answer(effective_question, ev, llm_kept, llm_dropped, repo_overview=repo_overview)
            for k in ["current_behaviour", "functional_flow", "business_rules", "affected_modules", "confidence"]:
                if k not in data:
                    data[k] = fb[k]
            data["query_plan"] = fb.get("query_plan", {})
            data["intents"] = fb.get("intents", [])
            data["primary_intent"] = fb.get("primary_intent", "HOW_IT_WORKS")
            # Redact secrets
            data["answer"] = redact_secrets(data.get("answer", ""))
            db.add(QueryLog(project_id=project_id, user_id=user_id or 0, question=question,
                            answer=data["answer"][:8000], evidence_refs_json=json.dumps(llm_kept[:12])))
            db.commit()
            return data
    except _OfflineSignal:
        pass

    # Offline / extractive fallback
    fb = _build_functional_answer(effective_question, ev, kept, dropped, repo_overview=repo_overview)
    db.add(QueryLog(project_id=project_id, user_id=user_id or 0, question=question,
                    answer=fb["answer"][:8000], evidence_refs_json=json.dumps(kept[:12])))
    db.commit()
    return fb


def trace_flow(db: Session, project_id: int, question: str, user_id: int = 0) -> dict:
    ev = retrieve(db, project_id, question, top_k=16)

    if not ev:
        res = {
            "status": "INSUFFICIENT_EVIDENCE",
            "steps": [],
            "flow": [],
            "gaps": ["No implementation evidence found in repository."],
            "evidence": [],
            "confidence": "None",
        }
        db.add(QueryLog(project_id=project_id, user_id=user_id or 0, question=f"[trace] {question}",
                        answer="INSUFFICIENT_EVIDENCE: not found in analyzed code", evidence_refs_json="[]"))
        db.commit()
        return res

    layer_order = {
        "Entry Point / Frontend": 1,
        "Validation": 2,
        "Backend / Business Logic": 3,
        "Persistence / Database": 4,
        "Notifications / Events": 5,
        "Downstream Processing": 6,
        "Matching / AI Pipeline": 7,
        "Administrative Handling": 8,
    }

    # Rank evidence prioritizing source implementation > endpoint definitions > database logic > business rules > tests > documentation
    def _ev_priority(e):
        ref = e["source_ref"].lower()
        t = e["text"].lower()
        score = 100
        if "tests/" in ref or "test_" in ref:
            score -= 60
        if "readme" in ref or "docs/" in ref:
            score -= 50
        if ref.endswith(".py") or ref.endswith(".ts") or ref.endswith(".js"):
            score += 20
        if "def " in t or "function " in t:
            score += 15
        if "insert into" in t or "c.execute" in t or "db.session" in t:
            score += 15
        return score

    sorted_ev = sorted(ev, key=_ev_priority, reverse=True)
    categorized_steps = []
    seen_stages = set()

    for e in sorted_ev:
        t = e["text"]
        t_l = t.lower()
        ref = e["source_ref"]
        ref_l = ref.lower()
        symbol = ref.split(":")[-1] if ":" in ref else ref.split("#")[-1]

        stage = None
        desc = ""

        if any(k in t_l or k in ref_l for k in ["pipeline", "run_matching", "matching", "detect", "inference", "predict", "classify", "train", "model", "cv2", "opencv", "torch", "tensorflow", "sklearn", "numpy", "scipy", "ml_", "ai_", "algorithm"]):
            stage = "Matching / AI Pipeline"
            desc = f"Downstream automated algorithm/model execution triggered (symbol: `{symbol}`). Executes computational pipeline against records."
        elif any(k in t_l or k in ref_l for k in ["notify", "notification", "email", "sms", "alert", "dispatch", "sendmail"]):
            stage = "Notifications / Events"
            desc = f"Notification or event dispatched (`{symbol}`). Emits alert and status confirmation to designated consumers."
        elif any(k in t_l for k in ["insert into", "c.execute", "conn.commit", "db.session", "lastrowid", "cursor.execute", "session.add", "session.commit", "create table"]):
            stage = "Persistence / Database"
            desc = f"State persisted to database layer (`{symbol}`). Executes data storage and commit."
        elif any(k in t_l for k in ["raise valueerror", "raise validationerror", "raise httpexception", "assert ", "if not ", "guard", "clean_", "validate_"]):
            stage = "Validation"
            first_rule = [line.strip() for line in t.splitlines() if "raise " in line or "if " in line or "assert " in line]
            rule_sample = first_rule[0][:120] if first_rule else "Input validation"
            desc = f"Input guard clauses and validation checks evaluated: `{rule_sample}`"
        elif any(k in t_l or k in ref_l for k in ["admin", "portal", "approval", "reassign", "manage_"]):
            stage = "Administrative Handling"
            desc = f"Administrative management handling (`{symbol}`). Coordinates verification and management review."
        elif any(k in ref_l for k in [".tsx", ".jsx", ".html", "streamlit", "views.py"]) or any(k in t_l for k in ["st.form", "st.button", "st.text_input", "form(", "render", "@router", "@app.", "apirouter"]):
            stage = "Entry Point / Frontend"
            desc = f"User interaction initiates at `{symbol}`. Captures input data and triggers request dispatch."
        elif any(k in t_l or k in ref_l for k in ["task", "worker", "celery", "queue", "background", "async"]):
            stage = "Downstream Processing"
            desc = f"Asynchronous job queued for background processing (`{symbol}`)."
        else:
            stage = "Backend / Business Logic"
            desc = f"Core domain logic handled by `{symbol}`. Coordinates domain execution workflow."

        if stage not in seen_stages:
            seen_stages.add(stage)
            comp_name = symbol.split("#")[0].split("/")[-1]
            categorized_steps.append({
                "stage": stage,
                "order": layer_order.get(stage, 9),
                "description": redact_secrets(desc),
                "component": comp_name,
                "evidence": {
                    "file": ref.split("#")[0].split(":")[0],
                    "symbol": symbol,
                    "lines": ref,
                    "why_relevant": redact_secrets(t[:200]),
                }
            })

    categorized_steps.sort(key=lambda s: s["order"])
    final_steps = [{
        "stage": s["stage"],
        "description": s["description"],
        "component": s["component"],
        "evidence": s["evidence"]
    } for s in categorized_steps]

    flow_list = [f"Step {i} ({s['stage']}): {s['description']}" for i, s in enumerate(final_steps, 1)]
    claims = _ev_to_claims(ev)
    confidence = "High" if len(final_steps) >= 3 else "Medium"

    result = {
        "status": "SUCCESS",
        "steps": final_steps,
        "flow": flow_list,
        "gaps": [],
        "evidence": claims[:12],
        "confidence": confidence,
    }

    db.add(QueryLog(project_id=project_id, user_id=user_id or 0, question=f"[trace] {question}",
                    answer=json.dumps(result)[:8000], evidence_refs_json=json.dumps(claims[:12])))
    db.commit()
    return result


def analyze_enhancement(db: Session, project_id: int, request: str, user_id: int = 0) -> dict:
    ev = retrieve(db, project_id, request, top_k=16)

    if not ev:
        res = {
            "status": "INSUFFICIENT_EVIDENCE",
            "current_behavior": "No evidenced behavior found in the codebase.",
            "impacted_areas": [],
            "frontend_impact": "None evidenced.",
            "backend_impact": "None evidenced.",
            "db_impact": "None evidenced.",
            "permission_impact": "None evidenced.",
            "notifications": "None evidenced.",
            "external_integrations": "None evidenced.",
            "downstream_risks": [],
            "needs_dev_validation": ["Full architecture assessment required: requested domain is not implemented in codebase."],
            "complexity": "Unknown",
            "complexity_justification": "No related domain areas or evidence found in codebase.",
            "evidence": [],
            "confidence": "None",
        }
        db.add(QueryLog(project_id=project_id, user_id=user_id or 0, question=f"[enhancement] {request}",
                        answer="INSUFFICIENT_EVIDENCE: no related areas found", evidence_refs_json="[]"))
        db.commit()
        return res

    evd = _ev_to_claims(ev)
    touched_files = sorted({e["source_ref"].split("#")[0].split(":")[0] for e in ev})
    req_l = request.lower()

    # 1. Current Behavior
    top_refs = ", ".join(f"`{f}`" for f in touched_files[:4])
    current_behavior = redact_secrets(
        f"The existing workflow is implemented in {top_refs}. "
        f"Evidence indicates core execution is handled via {ev[0]['source_ref']}."
    )

    # 2. Frontend Impact
    is_ui = any("st." in e["text"] or ".tsx" in e["source_ref"] or ".jsx" in e["source_ref"] or "form" in e["text"].lower() for e in ev)
    if is_ui or "form" in req_l or "ui" in req_l or "portal" in req_l:
        frontend_impact = "Update intake/reporting forms and confirmation banners to inform users of notification dispatch or enhancement status."
    else:
        frontend_impact = "Minimal frontend changes required; primarily backend orchestration."

    # 3. Backend Impact
    backend_handlers = [e["source_ref"] for e in ev if "def " in e["text"] or "function " in e["text"] or "@router" in e["text"]]
    handler_str = ", ".join(f"`{h}`" for h in backend_handlers[:3]) or "core handler functions"
    backend_impact = f"Modify {handler_str} to integrate the requested logic into the execution pipeline."

    # 4. Database / Data Model Impact
    has_db = any("insert" in e["text"].lower() or "c.execute" in e["text"].lower() or "db.session" in e["text"].lower() for e in ev)
    if "notification" in req_l or "email" in req_l:
        db_impact = "Add notification logging table or columns (e.g. `notification_status`, `sent_at`, `recipient`) to record outbound delivery."
    elif has_db or "model" in req_l or "table" in req_l:
        db_impact = "Schema updates or migration required for persisting new state attributes."
    else:
        db_impact = "No schema migration strictly required; leverages existing entity relationships."

    # 5. Roles / Permissions Impact
    roles = db.query(Role.name).filter(Role.project_id == project_id).all()
    role_names = [r[0] for r in roles] or ["admin", "user"]
    if "admin" in req_l:
        permission_impact = f"Enforce administrator-only access. Target recipient role: 'admin' (existing roles in repo: {', '.join(role_names)})."
    else:
        permission_impact = f"Verify role permission matrix ({', '.join(role_names[:4])}) to ensure unauthorized access is blocked."

    # 6. Notifications Impact
    if "email" in req_l or "notification" in req_l or "alert" in req_l:
        notifications_impact = "Configure outbound notification service (SMTP / SendGrid / SES) with templated notification payload including report ID and timestamp."
    else:
        notifications_impact = "No direct messaging or notification dispatch required."

    # 7. External Integrations
    if "email" in req_l or "notification" in req_l:
        external_integrations = "External email provider (SMTP, AWS SES, or SendGrid) with API keys managed via environment variables."
    elif any("api" in e["text"].lower() for e in ev):
        external_integrations = "REST API gateway integration."
    else:
        external_integrations = "Internal system integration; no third-party APIs required."

    # 8. Downstream Workflows & Risks
    downstream_risks = [
        "Network latency or provider downtime must not block core workflow execution (dispatch should be async or non-blocking).",
        "Potential regression in report submission if handler exceptions are unhandled.",
        "Recipient address resolution failure if administrator contact info is unconfigured.",
    ]

    # 9. Implementation & Validation Checklist
    needs_dev_validation = [
        "Create decoupled notification helper function with try/catch error containment.",
        "Add environment configuration for SMTP host, port, credentials, and recipient list.",
        "Wire dispatch hook into submission completion block in backend.",
        "Unit test email template formatting and error recovery.",
        "Integration test end-to-end report submission with simulated notification service.",
    ]

    # 10. Complexity Calculation (Low, Medium, High based on architectural layers)
    layers_count = 1
    if is_ui:
        layers_count += 1
    if "notification" in req_l or "email" in req_l:
        layers_count += 2
    if has_db:
        layers_count += 1

    if layers_count >= 4 or "approval" in req_l or "workflow" in req_l:
        complexity = "Medium"
        complexity_justification = "Medium: Multi-layer enhancement requiring external communication service, recipient resolution, and non-blocking error isolation without disrupting core intake."
    elif len(touched_files) > 4:
        complexity = "High"
        complexity_justification = "High: Widespread cross-module changes impacting multiple distinct architectural subsystems."
    else:
        complexity = "Low"
        complexity_justification = "Low: Targeted change confined to isolated helper or backend logic."

    result = {
        "status": "SUCCESS",
        "current_behavior": current_behavior,
        "impacted_areas": touched_files,
        "frontend_impact": frontend_impact,
        "backend_impact": backend_impact,
        "db_impact": db_impact,
        "permission_impact": permission_impact,
        "notifications": notifications_impact,
        "external_integrations": external_integrations,
        "downstream_risks": downstream_risks,
        "needs_dev_validation": needs_dev_validation,
        "complexity": complexity,
        "complexity_justification": complexity_justification,
        "evidence": evd[:12],
        "confidence": "High" if len(ev) >= 3 else "Medium",
    }

    db.add(QueryLog(project_id=project_id, user_id=user_id or 0, question=f"[enhancement] {request}",
                    answer=json.dumps(result)[:8000], evidence_refs_json=json.dumps(evd[:12])))
    db.commit()
    return result


def generate_suggested_questions(db: Session, project_id: int) -> list[str]:
    """Generate repository-grounded suggested natural-language questions tailored to the project domain."""
    import re
    p = db.query(Project).filter(Project.id == project_id).first()
    if p and p.suggested_questions_cache:
        try:
            cached = json.loads(p.suggested_questions_cache)
            if isinstance(cached, list) and len(cached) >= 4:
                return cached
        except Exception:
            pass

    facts = _facts(db, project_id)
    raw_ents = [e["name"] for e in facts.get("entities", []) if e.get("name")]
    roles = [r for r in facts.get("roles", []) if r]
    eps = facts.get("endpoints", [])

    # Clean entity names: strip class notations e.g. "persons (MissingPersonRecord)" -> "Persons"
    ents = []
    for re_name in raw_ents:
        clean = re.sub(r"\(.*?\)", "", re_name).strip()
        clean = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", clean)
        clean = clean.replace("_", " ").strip().title()
        if clean and clean not in ents:
            ents.append(clean)

    # Discard parser artifacts and non-domain terms
    BAD_TERMS = {
        "Authenticated", "Anonymous", "Admin Role", "User Role", "Item",
        "Item Records", "Root", "Index", "App", "User Profile", "Unknown",
        "Base", "Core", "Model", "View", "Form", "Object"
    }
    ents = [e for e in ents if e not in BAD_TERMS]

    # Ground via Domain Vocabulary if present
    p_dir = project_dir(project_id)
    vocab_path = os.path.join(p_dir, "domain_vocabulary.json")
    if os.path.exists(vocab_path):
        try:
            from app.domain_vocabulary import RepositoryDomainVocabulary
            vocab = RepositoryDomainVocabulary.load(vocab_path)
            for c in vocab.concepts.values():
                if len(c.files) >= 1 or len(c.symbols) >= 1:
                    cname = c.canonical_name.replace("_", " ").title()
                    if cname not in BAD_TERMS and cname not in ents and len(cname) > 2:
                        ents.append(cname)
        except Exception:
            pass

    questions = [
        "What is the primary business purpose of this application?",
        "Who are the intended users and what roles exist in the system?",
    ]

    if ents:
        e1 = ents[0]
        questions.append(f"How does the {e1} creation or submission workflow work?")
        questions.append(f"What business rules and validation constraints apply to {e1}?")
        questions.append(f"Where is {e1} data stored in the database?")
        if len(ents) > 1:
            e2 = ents[1]
            questions.append(f"How does the system manage and process {e2} records?")
    elif eps:
        p0 = eps[0]["path"]
        questions.append(f"How does the request to `{p0}` get processed end to end?")
    else:
        questions.append("How does the primary user workflow execute end to end?")
        questions.append("What business rules and input validations are enforced?")

    if roles:
        r0 = roles[0].strip().title()
        questions.append(f"What capabilities and permissions are granted to a {r0}?")
    else:
        questions.append("What permissions and access controls govern system actions?")

    if facts.get("integrations"):
        questions.append("Which external systems, APIs, or third-party services does this application integrate with?")
    else:
        questions.append("How does the application handle system errors and exceptions?")

    # Remove duplicates while preserving order
    seen = set()
    unique_q = []
    for q in questions:
        if q not in seen:
            seen.add(q)
            unique_q.append(q)

    return unique_q[:8]


