"""Repository Question Agent: Agentic Investigation Loop for General Repository Intelligence.

Implements a controlled, multi-step investigation cycle:

1. UNDERSTAND QUESTION         — NLU intent classification + noun chunking
2. DECOMPOSE                   — Multi-intent sub-query splitting
3. NAVIGATE AIM                — Traverse Application Intelligence Model entities/relationships
4. RETRIEVE EVIDENCE           — Multi-factor hybrid retrieval from vector + knowledge graph
5. COLLECT SUPPLEMENTARY       — Data lineage, state machine, decision rule lookups
6. MERGE & DEDUPLICATE         — Unify evidence across all sources
7. VERIFY CLAIMS               — Claim-to-evidence grounding with derivation types
8. CALIBRATE CONFIDENCE        — Multi-layer confidence scoring
9. DETECT CONTRADICTIONS       — Cross-source conflict identification
10. DETERMINE ANSWER STATUS    — FULLY/PARTIALLY/CONFLICTING/AMBIGUOUS/INSUFFICIENT
11. SYNTHESIZE ANSWER          — PM/BA-friendly structured answer generation
12. APPLY EVIDENCE GATE        — Zero-hallucination guardrail enforcement
13. FORMAT RESPONSE            — Intent-specific section rendering
14. LOG                        — Persist query + answer to QueryLog

The agent operates entirely from the repository's own indexed content and
persisted AIM. There are NO hardcoded question-answer mappings, NO domain-specific
question lists, and NO question whitelists.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.analysis.query_intent import analyze_query, QueryIntent
from app.analysis.application_intelligence import (
    get_or_build_application_intelligence,
    ApplicationIntelligenceModel,
    CAT_DATABASE_TABLE, CAT_DATABASE_FIELD, CAT_MODEL, CAT_API, CAT_ROUTE,
    CAT_WORKFLOW, CAT_BUSINESS_RULE, CAT_VALIDATION, CAT_ROLE, CAT_PERMISSION,
    CAT_STATE, CAT_STATE_TRANSITION, CAT_FORM, CAT_FORM_FIELD,
    CAT_UI_COMPONENT, CAT_MODULE, CAT_FEATURE, CAT_INTEGRATION,
    CAT_NOTIFICATION, CAT_SERVICE, CAT_CLASS, CAT_FUNCTION,
)
from app.analysis.security import redact_secrets
from app.analysis.functional.modules import infer_module_name
from app.knowledge_base.retrieval import retrieve, get_project_catalog, evaluate_sufficiency
from app.reasoning.guardrails import check_evidence
from app.reasoning.llm_client import llm_complete, _OfflineSignal
from app.models.models import (
    QueryLog, Project, ApiEndpoint, DataEntity, CodeSymbol, KnowledgeChunk, Role
)
from app.ingestion.orchestrator import project_dir
from app.knowledge_graph import get_knowledge_graph
from app.domain_vocabulary import get_domain_vocabulary
from app.prompts import templates


# ---------------------------------------------------------------------------
# Investigation Step Data Structures
# ---------------------------------------------------------------------------

@dataclass
class InvestigationContext:
    """Accumulates evidence, claims, and reasoning state across investigation steps."""
    question: str
    effective_question: str = ""
    project_id: int = 0
    query_intent: QueryIntent | None = None

    # Evidence pools
    aim_evidence: list[dict[str, Any]] = field(default_factory=list)
    retrieval_evidence: list[dict[str, Any]] = field(default_factory=list)
    supplementary_evidence: list[dict[str, Any]] = field(default_factory=list)
    merged_evidence: list[dict[str, Any]] = field(default_factory=list)

    # Claim verification
    verified_claims: list[dict[str, Any]] = field(default_factory=list)
    unverified_claims: list[dict[str, Any]] = field(default_factory=list)
    dropped_claims: int = 0

    # Investigation loop tracking
    iteration: int = 1
    max_iterations: int = 3
    investigation_steps: list[str] = field(default_factory=list)
    investigation_history: list[dict[str, Any]] = field(default_factory=list)
    replan_reasons: list[str] = field(default_factory=list)
    expanded_vocabulary: set[str] = field(default_factory=set)
    traversed_nodes: set[str] = field(default_factory=set)
    alternative_queries: list[str] = field(default_factory=list)

    # AIM navigation results
    lineage_traces: list[dict[str, Any]] = field(default_factory=list)
    state_machines: list[dict[str, Any]] = field(default_factory=list)
    decision_rules: list[dict[str, Any]] = field(default_factory=list)
    related_entities: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)

    # Answer synthesis
    answer_status: str = ""
    confidence: str = "None"
    contradictions: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    affected_modules: list[str] = field(default_factory=list)
    business_rules: list[str] = field(default_factory=list)
    flow_steps: list[str] = field(default_factory=list)

    # Metadata
    intents: list[str] = field(default_factory=list)
    primary_intent: str = "HOW_IT_WORKS"
    sub_queries: list[str] = field(default_factory=list)
    is_multi_intent: bool = False


# ---------------------------------------------------------------------------
# Step 1: UNDERSTAND QUESTION
# ---------------------------------------------------------------------------

def _step_understand_question(ctx: InvestigationContext, history: list[dict] | None = None) -> None:
    """NLU intent classification, noun chunking, and pronoun resolution."""
    qi = analyze_query(ctx.question, history=history)
    ctx.query_intent = qi
    ctx.effective_question = qi.resolved_query or ctx.question
    ctx.primary_intent = getattr(qi, "primary_intent", qi.intent)
    ctx.intents = getattr(qi, "intents", [ctx.primary_intent])

    plan = getattr(qi, "query_plan", {})
    ctx.is_multi_intent = bool(plan.get("is_multi_intent", False))
    ctx.sub_queries = plan.get("sub_queries", []) if ctx.is_multi_intent else []


# ---------------------------------------------------------------------------
# Step 2: NAVIGATE AIM
# ---------------------------------------------------------------------------

def _step_navigate_aim(ctx: InvestigationContext, aim: ApplicationIntelligenceModel) -> None:
    """Traverse the Application Intelligence Model to find relevant entities,
    relationships, data lineage, state machines, and decision rules."""
    qi = ctx.query_intent
    if not qi:
        return

    q = ctx.effective_question.lower()
    concepts = getattr(qi, "domain_concepts", [])
    AIM_STOP_WORDS = {
        "does", "this", "that", "what", "where", "when", "which", "with", "from",
        "into", "over", "under", "work", "works", "system", "codebase", "repository",
        "project", "application", "ecommerce", "handle", "handled", "handling",
        "perform", "performed", "performing", "operate", "operates", "ensure", "ensures"
    }
    if not concepts:
        # Fall back to extracting nouns from the question, excluding stop words
        concepts = [w for w in q.split() if len(w) > 3 and w not in AIM_STOP_WORDS]

    # Search across all entity categories for matching concepts
    _SEARCH_CATEGORIES = [
        CAT_DATABASE_TABLE, CAT_DATABASE_FIELD, CAT_MODEL, CAT_API, CAT_ROUTE,
        CAT_WORKFLOW, CAT_BUSINESS_RULE, CAT_VALIDATION, CAT_ROLE, CAT_PERMISSION,
        CAT_STATE, CAT_STATE_TRANSITION, CAT_FORM, CAT_FORM_FIELD,
        CAT_UI_COMPONENT, CAT_MODULE, CAT_FEATURE, CAT_INTEGRATION,
        CAT_NOTIFICATION, CAT_SERVICE, CAT_CLASS, CAT_FUNCTION,
    ]

    for concept in concepts:
        for cat in _SEARCH_CATEGORIES:
            matches = aim.find_entities(cat, concept)
            for m in matches:
                ctx.related_entities.append({
                    "category": cat,
                    "entity": m,
                    "matched_concept": concept,
                })

        # Query relationships for each concept
        rels = aim.query_relationships(concept)
        ctx.relationships.extend(rels)

        # Data lineage lookup
        lineage = aim.find_lineage(concept)
        if lineage:
            ctx.lineage_traces.append(lineage)

        # State machine lookup
        sm = aim.find_state_machine(concept)
        if sm:
            ctx.state_machines.append(sm)

    # Decision rules — only include if query matches validation/rules or matching entities were found
    if any(i in ctx.intents for i in ["VALIDATION", "WHY_BUSINESS_RULE"]):
        matched_rules = [
            r for r in aim.decision_rules
            if any(c in json.dumps(r).lower() for c in concepts)
        ]
        ctx.decision_rules = matched_rules[:10] if matched_rules else (aim.decision_rules[:5] if ctx.related_entities else [])
    elif any(i in ctx.intents for i in ["WORKFLOW", "HOW_IT_WORKS", "GENERAL_FUNCTIONAL"]) and ctx.related_entities:
        matched_rules = [
            r for r in aim.decision_rules
            if any(c in json.dumps(r).lower() for c in concepts)
        ]
        ctx.decision_rules = matched_rules[:5]

    # Convert AIM findings into evidence items for merging
    for ent_match in ctx.related_entities:
        ent = ent_match["entity"]
        name = str(ent.get("name", ""))
        cat = ent_match["category"]
        ev_item = ent.get("evidence", {})
        if isinstance(ev_item, list):
            for ei in ev_item:
                ctx.aim_evidence.append({
                    "source_ref": f"aim:{cat}:{name}",
                    "text": json.dumps(ent)[:300],
                    "score": 5.0,
                    "scores": {"aim_entity": 5.0},
                    "aim_category": cat,
                })
        else:
            ctx.aim_evidence.append({
                "source_ref": f"aim:{cat}:{name}",
                "text": json.dumps(ent)[:300],
                "score": 5.0,
                "scores": {"aim_entity": 5.0},
                "aim_category": cat,
            })


# ---------------------------------------------------------------------------
# Step 3: RETRIEVE EVIDENCE
# ---------------------------------------------------------------------------

def _step_retrieve_evidence(ctx: InvestigationContext, db: Session) -> None:
    """Multi-factor hybrid retrieval from vector index + knowledge graph."""
    if ctx.is_multi_intent and len(ctx.sub_queries) > 1:
        seen_refs: set[tuple[str, str]] = set()
        for sq in ctx.sub_queries:
            sub_ev = retrieve(db, ctx.project_id, sq, top_k=6)
            for item in sub_ev:
                ref_key = (item.get("source_ref", ""), item.get("text", "")[:100])
                if ref_key not in seen_refs:
                    seen_refs.add(ref_key)
                    ctx.retrieval_evidence.append(item)
        if not ctx.retrieval_evidence:
            ctx.retrieval_evidence = retrieve(db, ctx.project_id, ctx.effective_question, top_k=12)
    else:
        ctx.retrieval_evidence = retrieve(db, ctx.project_id, ctx.effective_question, top_k=12)


# ---------------------------------------------------------------------------
# Step 4: COLLECT SUPPLEMENTARY EVIDENCE
# ---------------------------------------------------------------------------

def _step_collect_supplementary(ctx: InvestigationContext, aim: ApplicationIntelligenceModel) -> None:
    """Enrich evidence with data lineage traces, state machine info, and decision rules."""
    for lt in ctx.lineage_traces:
        field_name = lt.get("field_name", "")
        entity_name = lt.get("entity_name", "")
        ctx.supplementary_evidence.append({
            "source_ref": f"lineage:{entity_name}.{field_name}",
            "text": (
                f"Data lineage: {field_name} flows from UI input ({lt.get('ui_input', '')}) "
                f"→ HTTP parameter ({lt.get('http_parameter', '')}) "
                f"→ backend attribute ({lt.get('backend_attribute', '')}) "
                f"→ model {lt.get('model_name', '')} "
                f"→ database field {lt.get('database_field', '')}"
            ),
            "score": 4.0,
            "scores": {"lineage": 4.0},
        })

    for sm in ctx.state_machines:
        entity = sm.get("entity", "")
        states = sm.get("states", [])
        transitions = sm.get("transitions", [])
        trans_desc = "; ".join(
            f"{t.get('from_state', '?')} → {t.get('to_state', '?')} ({t.get('trigger', '')})"
            for t in transitions[:6]
        )
        ctx.supplementary_evidence.append({
            "source_ref": f"state_machine:{entity}",
            "text": (
                f"State machine for {entity}: states = [{', '.join(states[:8])}]. "
                f"Transitions: {trans_desc}"
            ),
            "score": 4.0,
            "scores": {"state_machine": 4.0},
        })

    for rule in ctx.decision_rules[:6]:
        ctx.supplementary_evidence.append({
            "source_ref": f"decision_rule:{rule.get('rule_id', '')}",
            "text": (
                f"Business rule {rule.get('rule_id', '')}: "
                f"IF {rule.get('condition', '')} THEN {rule.get('action', '')}. "
                f"{rule.get('consequence', '')}"
            ),
            "score": 3.0,
            "scores": {"decision_rule": 3.0},
        })


# ---------------------------------------------------------------------------
# Step 5: MERGE & DEDUPLICATE
# ---------------------------------------------------------------------------

def _step_merge_evidence(ctx: InvestigationContext) -> None:
    """Merge all evidence pools and deduplicate by source_ref."""
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []

    # Prioritize retrieval evidence (has highest fidelity scores), then AIM, then supplementary
    for pool in [ctx.retrieval_evidence, ctx.aim_evidence, ctx.supplementary_evidence]:
        for item in pool:
            ref = item.get("source_ref", "")
            text_key = item.get("text", "")[:80]
            dedup_key = f"{ref}|{text_key}"
            if dedup_key not in seen:
                seen.add(dedup_key)
                merged.append(item)

    ctx.merged_evidence = merged


# ---------------------------------------------------------------------------
# Step 6: VERIFY CLAIMS (Claim-to-Evidence Grounding)
# ---------------------------------------------------------------------------

def _ev_to_claims(evidence: list[dict]) -> list[dict]:
    """Convert raw evidence items to claim format for guardrail checking."""
    claims = []
    for e in evidence:
        ref = e.get("source_ref", "")
        file_path = ref.split("#")[0].split(":")[0]
        claims.append({
            "file": file_path,
            "symbol": ref,
            "lines": ref,
            "source_ref": ref,
            "text": e.get("text", ""),
            "why_relevant": redact_secrets(e.get("text", "")[:300]),
            "score": e.get("score", 0.0),
            "scores": e.get("scores", {}),
        })
    return claims


def _step_verify_claims(ctx: InvestigationContext) -> None:
    """Apply citation guardrail: every claim must trace to retrieved evidence."""
    claims = _ev_to_claims(ctx.merged_evidence)
    # Ground against retrieved evidence chunks if available, or merged evidence if retrieval is exhausted
    verify_context = ctx.retrieval_evidence if ctx.retrieval_evidence else (
        ctx.merged_evidence if ctx.iteration >= ctx.max_iterations else []
    )
    kept, dropped = check_evidence(claims, verify_context)
    ctx.verified_claims = kept
    ctx.dropped_claims = dropped


# ---------------------------------------------------------------------------
# Step 7: DETECT CONTRADICTIONS
# ---------------------------------------------------------------------------

def _step_detect_contradictions(ctx: InvestigationContext) -> None:
    """Identify conflicting implementation rules across evidence sources."""
    auth_signals: dict[str, list[tuple[str, str]]] = {}
    for e in ctx.merged_evidence:
        t = e.get("text", "").lower()
        ref = e.get("source_ref", "")
        if "admin" in t and any(w in t for w in ["only", "require", "is_admin", "forbidden", "must be admin", "role == 'admin'"]):
            auth_signals.setdefault("restricted", []).append((ref, "requires administrator role"))
        if any(w in t for w in ["allow_any", "allowany", "public", "anonymous", "anyone can", "no auth"]):
            auth_signals.setdefault("unrestricted", []).append((ref, "allows public or unauthenticated access"))

    if "restricted" in auth_signals and "unrestricted" in auth_signals:
        r1, d1 = auth_signals["restricted"][0]
        r2, d2 = auth_signals["unrestricted"][0]
        ctx.contradictions.append(
            f"Conflicting access rules: `{r1}` ({d1}) vs `{r2}` ({d2}). "
            f"The codebase contains divergent policies for this capability."
        )


# ---------------------------------------------------------------------------
# Step 8: CALIBRATE CONFIDENCE
# ---------------------------------------------------------------------------

def _step_calibrate_confidence(ctx: InvestigationContext) -> None:
    """Multi-layer confidence scoring based on evidence depth and consistency."""
    retrieval_count = len(ctx.retrieval_evidence)
    aim_count = len(ctx.aim_evidence)
    supplementary_count = len(ctx.supplementary_evidence)
    total = retrieval_count + aim_count + supplementary_count

    if total == 0:
        ctx.confidence = "None"
    elif retrieval_count >= 2 and (aim_count >= 1 or supplementary_count >= 1):
        ctx.confidence = "High"
    elif retrieval_count >= 2 or (retrieval_count >= 1 and aim_count >= 1):
        ctx.confidence = "High"
    elif retrieval_count >= 1:
        ctx.confidence = "Medium"
    elif aim_count >= 1 or supplementary_count >= 1:
        ctx.confidence = "Medium"
    else:
        ctx.confidence = "Low"


# ---------------------------------------------------------------------------
# Step 9: DETERMINE ANSWER STATUS
# ---------------------------------------------------------------------------

def _step_determine_answer_status(ctx: InvestigationContext) -> None:
    """Classify answer status based on evidence completeness and contradictions."""
    if not ctx.retrieval_evidence and not ctx.aim_evidence:
        ctx.answer_status = "INSUFFICIENT_EVIDENCE"
        ctx.confidence = "None"
        return

    if ctx.contradictions:
        ctx.answer_status = "CONFLICTING_EVIDENCE"
        return

    # Check for partial knowledge gaps
    has_unknown_gaps = any(g.startswith("**Unknown:**") for g in ctx.gaps)
    if has_unknown_gaps:
        ctx.answer_status = "PARTIALLY_ANSWERABLE"
        return

    ctx.answer_status = "FULLY_ANSWERABLE"


# ---------------------------------------------------------------------------
# Step 10: EXTRACT AFFECTED MODULES
# ---------------------------------------------------------------------------

def _step_extract_modules(ctx: InvestigationContext) -> None:
    """Identify affected modules from evidence source references."""
    modules_set: set[str] = set()
    for e in ctx.merged_evidence:
        ref = e.get("source_ref", "")
        file_path = ref.split("#")[0].split(":")[0]
        if "/" in file_path or "\\" in file_path:
            mod = infer_module_name(file_path)
            if mod and mod != "root":
                modules_set.add(mod)
        elif ref.startswith("module:"):
            modules_set.add(ref.split(":", 1)[1])
    ctx.affected_modules = sorted(modules_set)


# ---------------------------------------------------------------------------
# Step 11: EXTRACT BUSINESS RULES & FLOW STEPS
# ---------------------------------------------------------------------------

def _step_extract_rules_and_flow(ctx: InvestigationContext) -> None:
    """Extract business rules and functional flow steps from evidence."""
    ev = ctx.merged_evidence

    # Business rules
    for e in ev:
        t = e.get("text", "")
        ref = e.get("source_ref", "")
        if any(term in ref or term in t for term in ["rule:", "validation", "raise ValueError", "raise ValidationError"]):
            rule_desc = t.replace("Business rule:", "").strip().split("\n")[0][:250]
            if rule_desc and rule_desc not in ctx.business_rules:
                ctx.business_rules.append(rule_desc)
    ctx.business_rules = ctx.business_rules[:6]

    # Flow steps
    routes = [e for e in ev if "endpoint:" in e.get("source_ref", "") or any(w in e.get("text", "") for w in ["@router", "app.", "route"])]
    handlers = [e for e in ev if any(w in e.get("text", "") for w in ["def ", "function "])]
    validators = [e for e in ev if any(w in e.get("text", "") for w in ["raise ", "validation"])]
    db_ops = [e for e in ev if any(w in e.get("text", "") for w in ["db.session", "Column", "INSERT", "add("])]

    step_num = 1
    if routes:
        route_name = routes[0]["source_ref"].split(":")[-1] if ":" in routes[0]["source_ref"] else routes[0]["source_ref"]
        ctx.flow_steps.append(f"{step_num}. The user's request is received at the application entry point (`{route_name}`)")
        step_num += 1
    if handlers:
        h_name = handlers[0]["source_ref"].split(":")[-1]
        ctx.flow_steps.append(f"{step_num}. The request is processed by the handler function `{h_name}`")
        step_num += 1
    if validators:
        ctx.flow_steps.append(f"{step_num}. Input data is validated against business rules and constraints")
        step_num += 1
    if db_ops:
        ctx.flow_steps.append(f"{step_num}. The validated data is stored in the database")
        step_num += 1

    if not ctx.flow_steps:
        for i, e in enumerate(ev[:4], 1):
            ref_name = e["source_ref"].split(":")[-1] if ":" in e["source_ref"] else e["source_ref"].split("/")[-1]
            ctx.flow_steps.append(f"{i}. Processing involves `{ref_name}`")


# ---------------------------------------------------------------------------
# Step 12: ANALYZE KNOWLEDGE GAPS
# ---------------------------------------------------------------------------

def _step_analyze_gaps(ctx: InvestigationContext) -> None:
    """Identify gaps between question intent and available evidence."""
    ev = ctx.merged_evidence
    routes = [e for e in ev if "endpoint:" in e.get("source_ref", "") or any(w in e.get("text", "") for w in ["@router", "app."])]
    validators = [e for e in ev if any(w in e.get("text", "") for w in ["raise ", "validation"])]
    db_ops = [e for e in ev if any(w in e.get("text", "") for w in ["db.session", "Column", "INSERT", "add("])]

    if any(i in ctx.intents for i in ["WORKFLOW", "HOW_IT_WORKS", "API"]):
        if not routes:
            ctx.gaps.append("**Unknown:** Direct public API route or controller endpoint was not identified in retrieved evidence; workflow inferred from service handlers.")
        else:
            ctx.gaps.append("**Established:** Public entry points and request dispatch handlers are confirmed by route definitions.")

    if any(i in ctx.intents for i in ["VALIDATION", "WHY_BUSINESS_RULE"]):
        if not validators and not ctx.business_rules:
            ctx.gaps.append("**Unknown:** Explicit input guardrails or business constraint rules could not be established from analyzed code.")
        else:
            ctx.gaps.append("**Established:** Domain validation and error guard clauses are confirmed in handler code.")

    if any(i in ctx.intents for i in ["DATABASE", "DATA_ENTITY"]):
        if not db_ops:
            ctx.gaps.append("**Unknown:** Direct database table schema or persistence statements were not identified in retrieved evidence.")
        else:
            ctx.gaps.append("**Established:** Data persistence operations are confirmed by database operations in code.")

    if any(i in ctx.intents for i in ["PERMISSION_AUTH", "USER_ROLE"]):
        auth_ev = [e for e in ev if any(w in e.get("text", "").lower() for w in ["permission", "role", "is_admin", "login", "auth"])]
        if not auth_ev:
            ctx.gaps.append("**Strong Inference:** Role-based access gates are inferred from module context but not directly cited in the retrieved code slice.")
        else:
            ctx.gaps.append("**Established:** Role or permission verification logic is evidenced in the codebase.")

    if ctx.dropped_claims > 0:
        ctx.gaps.append(
            f"**Unresolved Claims:** {ctx.dropped_claims} claim(s) lacked direct citation in retrieved repository evidence and were excluded from final assertions."
        )


# ---------------------------------------------------------------------------
# Step 13: SYNTHESIZE ANSWER
# ---------------------------------------------------------------------------

def _build_business_explanation(ctx: InvestigationContext, repo_overview: str = "") -> str:
    """Generate a PM/BA-friendly business explanation based on query intent."""
    module_desc = ", ".join(ctx.affected_modules) if ctx.affected_modules else "core application"
    intents = ctx.intents

    has_role_intent = any(i in intents for i in ["PERMISSION_AUTH", "USER_ROLE"])
    has_workflow_intent = any(i in intents for i in ["WORKFLOW", "HOW_IT_WORKS", "LIFECYCLE_STATUS"])

    if has_role_intent and has_workflow_intent:
        role_part = (
            f"**Roles & Permissions:** Access control and user authorization govern this capability across the **{module_desc}** module(s). "
            f"The system verifies role permissions before permitting actions to proceed."
        )
        workflow_part = (
            f"**Workflow & Downstream Execution:** Once authorized, the operational flow coordinates input validation, "
            f"commits state updates to persistent data storage, and triggers downstream event notifications across the **{module_desc}** module(s)."
        )
        return f"{role_part}\n\n{workflow_part}"

    qi = ctx.query_intent
    if qi and qi.intent == "purpose" and repo_overview:
        return (
            f"**Application Purpose & Executive Summary:**\n\n{repo_overview}\n\n"
            f"**Functional Scope:** This system is organized around the **{module_desc}** module(s) to automate and support core operational workflows."
        )

    intent_templates = {
        ("WORKFLOW", "HOW_IT_WORKS"): (
            f"**Workflow Overview:** The system executes this operational process across the **{module_desc}** module(s). "
            f"Incoming requests are received at application entry points, evaluated against domain business rules, "
            f"committed to persistent data storage, and coordinated with downstream components."
        ),
        ("DATABASE", "DATA_ENTITY"): (
            f"**Data Model & Storage:** Data persistence for this feature is managed within the **{module_desc}** data structures. "
            f"The application schemas define entity models, field attributes, constraints, and relationships maintained in the database layer."
        ),
        ("PERMISSION_AUTH", "USER_ROLE"): (
            f"**Access Control & Roles:** Security policies and user authorization govern this capability across the **{module_desc}** module(s). "
            f"The system verifies user roles and permissions before allowing sensitive actions or access to protected data."
        ),
        ("API",): (
            f"**API & Service Endpoints:** The application exposes structured API routes in the **{module_desc}** module(s) "
            f"enabling clients, frontends, or external systems to dispatch actions and query state."
        ),
        ("INTEGRATION",): (
            f"**External Integrations:** Third-party connectivity in the **{module_desc}** module(s) connects application logic "
            f"with external services, APIs, and background notification channels."
        ),
        ("ERROR_HANDLING",): (
            f"**Resilience & Error Handling:** System stability is safeguarded through input validations, exception handlers, "
            f"and error responses within the **{module_desc}** module(s) to guarantee graceful recovery."
        ),
        ("VALIDATION", "WHY_BUSINESS_RULE"): (
            f"**Business Logic & Validation:** Domain constraints and validation rules are enforced within the **{module_desc}** module(s) "
            f"to uphold data integrity and reject invalid requests before persistence."
        ),
        ("CAPABILITY", "FEATURE"): (
            f"**Functional Capability:** The system provides specialized domain capabilities in the **{module_desc}** module(s), "
            f"coordinating business operations, state tracking, and record handling."
        ),
        ("NOTIFICATION",): (
            f"**Notifications & Alerts:** The **{module_desc}** module(s) handle notification dispatch including "
            f"email, SMS, or in-app alerts triggered by domain events and state transitions."
        ),
        ("LIFECYCLE_STATUS",): (
            f"**Lifecycle & State Management:** Entity lifecycle and status transitions are tracked within the **{module_desc}** module(s), "
            f"enforcing valid state progressions with guard conditions."
        ),
    }

    for intent_group, template in intent_templates.items():
        if any(i in intents for i in intent_group):
            return template

    return (
        f"**Functional Overview:** Based on repository analysis, this capability is implemented across the **{module_desc}** module(s) "
        f"with defined business logic and persistent state."
    )


def _build_claims_grounding(ctx: InvestigationContext) -> list[dict[str, Any]]:
    """Build claim-to-evidence grounding map."""
    grounding = []
    for item in ctx.verified_claims:
        ref = item.get("source_ref", "")
        why = item.get("why_relevant", "")
        grounding.append({
            "claim": why[:150] if why else f"Evidence cited from {ref}",
            "evidence_ids": [ref],
            "derivation_type": (
                "CROSS_LAYER_TRACE" if any(w in ref.lower() for w in ["route", "endpoint", "view", "handler", "api"])
                else "DIRECT_EVIDENCE"
            ),
            "file": item.get("file", ""),
        })
    return grounding


def _step_synthesize_answer(ctx: InvestigationContext, repo_overview: str = "") -> str:
    """Synthesize the final structured answer from investigation results."""
    business_explanation = _build_business_explanation(ctx, repo_overview)

    # Technical evidence citations
    tech_evidence_items = []
    for e in ctx.merged_evidence[:4]:
        ref_path = e["source_ref"].split("#")[0].split(":")[0]
        sym = e["source_ref"].split(":")[-1] if ":" in e["source_ref"] else ref_path.split("/")[-1]
        tech_evidence_items.append(f"- `{ref_path}` (symbol: `{sym}`)")

    current_behaviour = f"{business_explanation}\n\n**Technical Implementation Details:**\n" + "\n".join(tech_evidence_items)

    if ctx.contradictions:
        contradiction_banner = (
            "### Contradiction Detected\n"
            "**Repository evidence is inconsistent.**\n\n" +
            "\n".join(f"- {c}" for c in ctx.contradictions)
        )
        current_behaviour = f"{contradiction_banner}\n\n{current_behaviour}"

    # Build sections
    sections = []
    qi = ctx.query_intent
    if qi and qi.intent == "purpose":
        sections.append(f"### Application Purpose & Overview\n{current_behaviour}")
        sections.append(f"### Core Workflows & Capabilities\n" + ("\n".join(ctx.flow_steps) if ctx.flow_steps else "Direct execution flow."))
    else:
        sections.append(f"### Direct Answer\n{current_behaviour}")
        sections.append(f"### How It Works\n" + ("\n".join(ctx.flow_steps) if ctx.flow_steps else "Direct execution flow."))

    if ctx.business_rules:
        sections.append(f"### Business Rules & Validations\n" + "\n".join(f"- {r}" for r in ctx.business_rules))

    # Intent-specific sections
    _add_intent_specific_sections(ctx, sections)

    if ctx.affected_modules:
        sections.append(f"### Impacted Components\n" + ", ".join(f"`{m}`" for m in ctx.affected_modules))

    # Add lineage trace section if present
    if ctx.lineage_traces:
        lineage_items = []
        for lt in ctx.lineage_traces[:3]:
            fn = lt.get("field_name", "")
            entity = lt.get("entity_name", "")
            lineage_items.append(
                f"- **{entity}.{fn}**: UI input → HTTP parameter → backend attribute → model → database column"
            )
        sections.append(f"### Data Lineage\n" + "\n".join(lineage_items))

    # Add state machine section if present
    if ctx.state_machines:
        sm_items = []
        for sm in ctx.state_machines[:2]:
            entity = sm.get("entity", "")
            states = sm.get("states", [])
            sm_items.append(f"- **{entity}**: [{', '.join(states[:8])}]")
        sections.append(f"### State Machines\n" + "\n".join(sm_items))

    if ctx.gaps:
        sections.append(f"### Gaps & Verification Status\n" + "\n".join(f"- {g}" for g in ctx.gaps))

    sections.append(f"\n*Confidence: {ctx.confidence} | {len(ctx.verified_claims)} cited source(s); {ctx.dropped_claims} dropped by guardrail.*")

    return redact_secrets("\n\n".join(sections))


def _add_intent_specific_sections(ctx: InvestigationContext, sections: list[str]) -> None:
    """Add intent-specific sections to the answer."""
    ev = ctx.merged_evidence
    intents = ctx.intents

    if any(i in intents for i in ["DATABASE", "DATA_ENTITY"]):
        db_snippets = [e["source_ref"] for e in ev if any(
            w in e["source_ref"].lower() or w in e.get("text", "").lower()
            for w in ["model", "table", "schema", "column", "entity", "sql"]
        )]
        if db_snippets:
            sections.append(f"### Data & Systems Involved\nPersistent data structures are defined in: " +
                          ", ".join(f"`{s}`" for s in db_snippets[:4]) + ".")

    if any(i in intents for i in ["PERMISSION_AUTH", "USER_ROLE"]):
        auth_snippets = [e["source_ref"] for e in ev if any(
            w in e["source_ref"].lower() or w in e.get("text", "").lower()
            for w in ["role", "permission", "auth", "guard", "login", "admin"]
        )]
        if auth_snippets:
            sections.append(f"### Roles & Access Control\nAuthorization and access control logic is enforced in: " +
                          ", ".join(f"`{s}`" for s in auth_snippets[:4]) + ".")

    if "API" in intents:
        api_snippets = [e["source_ref"] for e in ev if "endpoint:" in e["source_ref"] or any(
            w in e.get("text", "").lower() for w in ["@router", "@app.", "route", "apirouter"]
        )]
        if api_snippets:
            sections.append(f"### APIs & Service Endpoints\nHTTP endpoints handling this functionality: " +
                          ", ".join(f"`{s}`" for s in api_snippets[:4]) + ".")

    if "INTEGRATION" in intents:
        int_snippets = [e["source_ref"] for e in ev if any(
            w in e["source_ref"].lower() or w in e.get("text", "").lower()
            for w in ["client", "service", "webhook", "http", "requests", "httpx"]
        )]
        if int_snippets:
            sections.append(f"### External Integrations\nExternal service communication identified in: " +
                          ", ".join(f"`{s}`" for s in int_snippets[:4]) + ".")

    if "ERROR_HANDLING" in intents:
        err_snippets = [e["source_ref"] for e in ev if any(
            w in e.get("text", "").lower() for w in ["except ", "raise ", "try:", "error", "fail", "retry"]
        )]
        if err_snippets:
            sections.append(f"### Error Handling & Resilience\nException handling and error recovery logic found in: " +
                          ", ".join(f"`{s}`" for s in err_snippets[:4]) + ".")

    if "NOTIFICATION" in intents:
        notif_snippets = [e["source_ref"] for e in ev if any(
            w in e["source_ref"].lower() or w in e.get("text", "").lower()
            for w in ["notify", "notification", "email", "sms", "alert"]
        )]
        if notif_snippets:
            sections.append(f"### Notifications & Alerts\nNotification dispatching identified in: " +
                          ", ".join(f"`{s}`" for s in notif_snippets[:4]) + ".")

    if "LIFECYCLE_STATUS" in intents:
        lc_snippets = [e["source_ref"] for e in ev if any(
            w in e.get("text", "").lower()
            for w in ["status", "state", "transition", "pending", "approved", "active", "completed"]
        )]
        if lc_snippets:
            sections.append(f"### Lifecycle & State Transitions\nStatus management and state transitions handled in: " +
                          ", ".join(f"`{s}`" for s in lc_snippets[:4]) + ".")


# ---------------------------------------------------------------------------
# Investigation Sufficiency & 12-Step Replanning
# ---------------------------------------------------------------------------

def _step_evaluate_evidence_sufficiency(
    ctx: InvestigationContext, db: Session
) -> tuple[bool, str, list[str]]:
    """Evaluate whether current evidence pool is sufficient to ground an answer."""
    from app.knowledge_base.retrieval import get_project_catalog, evaluate_sufficiency
    catalog = get_project_catalog(db, ctx.project_id)

    # On the first iteration, if retrieval returned no evidence chunks,
    # the initial search missed evidence; do not prematurely accept AIM metadata.
    # Force replanning and deeper investigation.
    if ctx.iteration == 1 and not ctx.retrieval_evidence:
        is_suff, reason, missing = evaluate_sufficiency(
            db, ctx.project_id, ctx.effective_question, [], catalog
        )
        return False, reason or "initial_retrieval_missed", missing or ["code implementation evidence"]

    eval_candidates = ctx.retrieval_evidence if ctx.retrieval_evidence else ctx.merged_evidence
    if not eval_candidates and not ctx.aim_evidence:
        is_suff, reason, missing = evaluate_sufficiency(
            db, ctx.project_id, ctx.effective_question, [], catalog
        )
        return False, reason, missing

    is_suff, reason, missing = evaluate_sufficiency(
        db, ctx.project_id, ctx.effective_question, eval_candidates, catalog
    )

    if not is_suff:
        return False, reason, missing

    # Claim verification check: if no claims could be verified, trigger investigation retry
    if ctx.iteration < ctx.max_iterations and len(ctx.verified_claims) == 0 and len(ctx.merged_evidence) > 0:
        return False, "unsupported_claims", ["unverified claims require investigation"]

    # On early iteration, check if critical query-intent layers are missing
    if ctx.iteration == 1:
        if any(i in ctx.intents for i in ["VALIDATION", "WHY_BUSINESS_RULE"]):
            has_val = any(
                any(w in e.get("text", "").lower() or w in e.get("source_ref", "").lower()
                    for w in ["raise", "validat", "rule", "clean_", "constraint", "error"])
                for e in ctx.merged_evidence
            )
            if not has_val and len(ctx.business_rules) == 0:
                return False, "missing_validation_layer", ["validation_rules"]

    return True, "sufficient_evidence", []


def _step_replan_and_investigate(
    ctx: InvestigationContext,
    db: Session,
    aim: ApplicationIntelligenceModel,
    insufficiency_reason: str,
    missing_concepts: list[str],
) -> bool:
    """Execute replanning and investigation retry when evidence is insufficient or weak.

    Implements the 12-step investigation cycle:
    1. analyze why evidence is insufficient
    2. identify missing concepts/layers
    3. expand repository vocabulary
    4. traverse related graph nodes
    5. inspect callers/callees
    6. inspect routes/APIs
    7. inspect models/database
    8. inspect templates/forms/UI
    9. inspect configuration/documentation when relevant
    10. run an alternative retrieval strategy
    11. merge/deduplicate new evidence
    12. re-evaluate claims
    """
    initial_count = len(ctx.merged_evidence)
    ctx.replan_reasons.append(
        f"Iteration {ctx.iteration}: {insufficiency_reason} (missing: {missing_concepts})"
    )

    # 1. Analyze why evidence is insufficient & 2. Identify missing concepts/layers
    qi = ctx.query_intent
    target_concepts = [
        c for c in missing_concepts
        if c.lower() not in (
            "no evidence chunks matched query", "clarification required",
            "code implementation evidence", "unverified claims require investigation",
            "validation_rules", "action target"
        ) and len(c) > 1
    ]
    if qi:
        for ent in qi.entities:
            if ent not in target_concepts:
                target_concepts.append(ent)
        for act in qi.actions:
            if act not in target_concepts:
                target_concepts.append(act)
    if not target_concepts:
        from app.knowledge_base.retrieval import keywords
        target_concepts = keywords(ctx.effective_question)[:4]

    # 3. Expand repository vocabulary
    vocab = get_domain_vocabulary(db, ctx.project_id)
    expanded_terms: set[str] = set()
    if vocab:
        for tc in target_concepts:
            expanded_terms.update(vocab.get_synonyms_and_aliases(tc))
            matched = vocab.find_matching_concepts(tc)
            for m in matched:
                expanded_terms.add(m.canonical_name)
                expanded_terms.update(m.aliases)
                expanded_terms.update(m.related_concepts)
                for wf in m.related_workflows:
                    expanded_terms.update(wf.split("_"))

    # Also extract tokens from existing source references
    for e in ctx.merged_evidence:
        ref = e.get("source_ref", "")
        for part in ref.replace("/", " ").replace(".", " ").replace(":", " ").replace("_", " ").split():
            if len(part) > 3 and part.lower() not in ["core", "views", "models", "class", "def"]:
                expanded_terms.add(part.lower())
    ctx.expanded_vocabulary.update(expanded_terms)

    # 4. Traverse related graph nodes
    graph = get_knowledge_graph(db, ctx.project_id)
    new_graph_evidence: list[dict[str, Any]] = []
    seed_node_ids: list[str] = []
    for e in ctx.merged_evidence:
        ref = e.get("source_ref", "")
        for nid, node in graph.nodes.items():
            if node.name.lower() in ref.lower() or (node.file_path and node.file_path.lower() in ref.lower()):
                seed_node_ids.append(nid)

    for term in list(target_concepts) + list(expanded_terms)[:10]:
        matching_nodes = graph.search_nodes([term])
        for _, n in matching_nodes[:5]:
            seed_node_ids.append(n.id)

    if seed_node_ids:
        expanded_node_ids = graph.expand_neighborhood(seed_node_ids[:25], max_hops=2)
        for nid in expanded_node_ids:
            if nid not in ctx.traversed_nodes and nid in graph.nodes:
                ctx.traversed_nodes.add(nid)
                node = graph.nodes[nid]
                new_graph_evidence.append({
                    "source_ref": f"graph:{node.kind}:{node.name}",
                    "text": f"Knowledge graph entity [{node.kind}] {node.name} at {node.file_path} (lines {node.start_line}-{node.end_line}). Metadata: {json.dumps(node.metadata)}",
                    "score": 4.5,
                    "scores": {"graph_traversal": 4.5},
                })

    # 5. Inspect callers/callees
    caller_callee_evidence: list[dict[str, Any]] = []
    for nid in list(ctx.traversed_nodes)[:30]:
        for edge in graph.outgoing.get(nid, []):
            if edge.kind in ("CALLS", "USES_MODEL", "VALIDATES", "ROUTES_TO") and edge.target_id in graph.nodes:
                target_node = graph.nodes[edge.target_id]
                ref_key = f"trace:{edge.kind}:{target_node.name}"
                caller_callee_evidence.append({
                    "source_ref": ref_key,
                    "text": f"Trace ({edge.kind}): {nid} -> {target_node.name} in {target_node.file_path}. {json.dumps(target_node.metadata)}",
                    "score": 4.0,
                    "scores": {"callee_trace": 4.0},
                })
        for edge in graph.incoming.get(nid, []):
            if edge.kind in ("CALLS", "CALLED_BY") and edge.source_id in graph.nodes:
                source_node = graph.nodes[edge.source_id]
                ref_key = f"trace:CALLED_BY:{source_node.name}"
                caller_callee_evidence.append({
                    "source_ref": ref_key,
                    "text": f"Trace (CALLED_BY): {nid} is called by {source_node.name} in {source_node.file_path}.",
                    "score": 4.0,
                    "scores": {"caller_trace": 4.0},
                })

    all_search_terms = set(t.lower() for t in target_concepts) | set(t.lower() for t in expanded_terms)

    # 6. Inspect routes/APIs
    route_evidence: list[dict[str, Any]] = []
    endpoints = db.query(ApiEndpoint).filter(ApiEndpoint.project_id == ctx.project_id).all()
    for ep in endpoints:
        path_lower = ep.path.lower()
        if any(term in path_lower for term in all_search_terms if len(term) > 2):
            route_evidence.append({
                "source_ref": f"endpoint:{ep.method} {ep.path}",
                "text": f"API Endpoint: {ep.method} {ep.path}. Auth required: {ep.auth_required}. Roles: {ep.roles_allowed}",
                "score": 5.0,
                "scores": {"endpoint_inspection": 5.0},
            })

    # 7. Inspect models/database
    model_evidence: list[dict[str, Any]] = []
    entities = db.query(DataEntity).filter(DataEntity.project_id == ctx.project_id).all()
    for de in entities:
        name_lower = de.name.lower()
        fields_str = de.fields_json or ""
        if any(term in name_lower or term in fields_str.lower() for term in all_search_terms if len(term) > 2):
            model_evidence.append({
                "source_ref": f"model:{de.name}",
                "text": f"Data Model/Table: {de.name}. Fields: {fields_str}",
                "score": 5.0,
                "scores": {"model_inspection": 5.0},
            })

    # 8. Inspect templates/forms/UI
    form_evidence: list[dict[str, Any]] = []
    form_symbols = db.query(CodeSymbol).filter(
        CodeSymbol.project_id == ctx.project_id,
        CodeSymbol.kind.in_(["class", "function"])
    ).all()
    for sym in form_symbols:
        s_lower = sym.name.lower()
        if any(kw in s_lower for kw in ["form", "view", "component", "template", "clean", "validat"]):
            if any(term in s_lower or term in (sym.docstring or "").lower() for term in all_search_terms if len(term) > 2):
                form_evidence.append({
                    "source_ref": f"symbol:{sym.kind}:{sym.name}",
                    "text": f"UI/Form/Validator component: {sym.signature}. Doc: {sym.docstring or 'None'}",
                    "score": 4.5,
                    "scores": {"form_inspection": 4.5},
                })

    # 9. Inspect configuration/documentation when relevant
    config_evidence: list[dict[str, Any]] = []
    if any(kw in ctx.effective_question.lower() for kw in ["config", "setting", "url", "route", "setup", "env", "admin"]):
        config_chunks = db.query(KnowledgeChunk).filter(
            KnowledgeChunk.project_id == ctx.project_id
        ).all()
        for cc in config_chunks:
            ref_l = (cc.source_ref or "").lower()
            if any(cfg in ref_l for cfg in ["urls.py", "settings.py", "config", "admin"]):
                config_evidence.append({
                    "source_ref": cc.source_ref,
                    "text": cc.chunk_text[:1500],
                    "score": 4.0,
                    "scores": {"config_inspection": 4.0},
                })

    # 10. Run alternative retrieval strategy
    alt_retrieval_evidence: list[dict[str, Any]] = []
    alt_queries: list[str] = []
    if ctx.effective_question:
        alt_queries.append(ctx.effective_question)
    for mc in target_concepts[:2]:
        for layer_kw in ["model", "form", "validator", "view", "table"]:
            alt_queries.append(f"{mc} {layer_kw}")
    if expanded_terms:
        top_terms = [t for t in list(expanded_terms)[:4] if len(t) > 2]
        if top_terms:
            alt_queries.append(" ".join(top_terms))

    ctx.alternative_queries.extend(alt_queries[:5])
    for aq in alt_queries[:5]:
        alt_results = retrieve(db, ctx.project_id, aq, top_k=6, allow_insufficient=True)
        for ar in alt_results:
            alt_retrieval_evidence.append(ar)

    # 11. Merge/deduplicate new evidence
    ctx.supplementary_evidence.extend(
        new_graph_evidence[:6] + caller_callee_evidence[:6] + route_evidence[:4] +
        model_evidence[:4] + form_evidence[:4] + config_evidence[:4]
    )
    ctx.retrieval_evidence.extend(alt_retrieval_evidence[:8])

    _step_merge_evidence(ctx)

    # 12. Re-evaluate claims
    _step_verify_claims(ctx)

    return len(ctx.merged_evidence) > initial_count or len(ctx.retrieval_evidence) > 0


# ---------------------------------------------------------------------------
# MAIN AGENT ENTRY POINT
# ---------------------------------------------------------------------------

def investigate_question(
    db: Session,
    project_id: int,
    question: str,
    user_id: int = 0,
    history: list[dict] | None = None,
) -> dict[str, Any]:
    """Execute the full agentic investigation loop for a repository question.

    Orchestrates the 14-step investigation cycle with a bounded retry loop:
    If evidence is insufficient at the first attempt, the agent does NOT
    immediately return INSUFFICIENT_EVIDENCE. Instead, it analyzes why evidence
    is insufficient, expands vocabulary, traverses graph nodes, inspects callers/
    callees/routes/models/forms, runs alternative retrieval, and merges new evidence.
    """
    ctx = InvestigationContext(question=question, project_id=project_id, max_iterations=3)

    # Step 1: UNDERSTAND QUESTION
    _step_understand_question(ctx, history=history)
    ctx.investigation_steps = ["UNDERSTAND_QUESTION", "PLAN_INVESTIGATION"]

    # Handle ambiguous pronoun queries
    qi = ctx.query_intent
    if qi and qi.is_ambiguous:
        clarification_msg = qi.clarification_prompt or "Could you please clarify which feature or domain entity you are referring to?"
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "answer_status": "AMBIGUOUS",
            "answer": clarification_msg,
            "current_behaviour": "Ambiguous reference without prior context.",
            "functional_flow": [],
            "business_rules": [],
            "affected_modules": [],
            "evidence": [],
            "claims_grounding": [],
            "confidence": "None",
            "reason": "ambiguous_question",
            "missing_concepts": ["clarification required"],
            "gaps": [clarification_msg],
            "guard_dropped": 0,
            "intents": ctx.intents,
            "primary_intent": ctx.primary_intent,
            "iterations_count": ctx.iteration,
            "max_iterations": ctx.max_iterations,
            "investigation_history": ctx.investigation_history,
            "replan_reasons": ctx.replan_reasons,
            "investigation_steps": ctx.investigation_steps,
        }

    # Check for vocabulary-based ambiguity (multiple matching workflows)
    ambiguity_result = _check_vocabulary_ambiguity(ctx, db)
    if ambiguity_result:
        ambiguity_result["iterations_count"] = ctx.iteration
        ambiguity_result["max_iterations"] = ctx.max_iterations
        ambiguity_result["investigation_history"] = ctx.investigation_history
        ambiguity_result["replan_reasons"] = ctx.replan_reasons
        db.add(QueryLog(project_id=project_id, user_id=user_id or 0, question=question,
                        answer=ambiguity_result["answer"][:8000], evidence_refs_json="[]"))
        db.commit()
        return ambiguity_result

    # Load AIM
    aim = get_or_build_application_intelligence(db, project_id)

    # Initial investigation cycle
    # Step 2: NAVIGATE AIM
    _step_navigate_aim(ctx, aim)
    ctx.investigation_steps.append("NAVIGATE_AIM")

    # Step 3: RETRIEVE EVIDENCE
    _step_retrieve_evidence(ctx, db)
    ctx.investigation_steps.append("RETRIEVE_EVIDENCE")

    # Step 4: COLLECT SUPPLEMENTARY
    _step_collect_supplementary(ctx, aim)
    ctx.investigation_steps.append("COLLECT_SUPPLEMENTARY")

    # Step 5: MERGE & DEDUPLICATE
    _step_merge_evidence(ctx)
    ctx.investigation_steps.append("MERGE_EVIDENCE")

    # Step 6: VERIFY CLAIMS
    _step_verify_claims(ctx)
    ctx.investigation_steps.append("VERIFY_CLAIMS")

    # BOUNDED INVESTIGATION RETRY LOOP:
    # If evidence is insufficient at the first attempt, DO NOT immediately return INSUFFICIENT_EVIDENCE.
    # Instead, analyze why evidence is insufficient, replan, and execute deeper targeted investigation.
    while ctx.iteration < ctx.max_iterations:
        is_suff, reason, missing = _step_evaluate_evidence_sufficiency(ctx, db)

        ctx.investigation_history.append({
            "iteration": ctx.iteration,
            "evidence_count": len(ctx.merged_evidence),
            "retrieval_count": len(ctx.retrieval_evidence),
            "verified_claims_count": len(ctx.verified_claims),
            "is_sufficient": is_suff,
            "reason": reason,
            "missing": missing,
        })

        if is_suff:
            break

        # Replan and execute next investigation iteration
        ctx.iteration += 1
        ctx.investigation_steps.append(f"INVESTIGATION_REPLAN_ITERATION_{ctx.iteration}")

        new_evidence_found = _step_replan_and_investigate(ctx, db, aim, reason, missing)
        if not new_evidence_found:
            # Repository evidence exhausted across all sources
            break

    # Record final iteration in history
    is_suff, reason, missing = _step_evaluate_evidence_sufficiency(ctx, db)
    if not ctx.investigation_history or ctx.investigation_history[-1]["iteration"] != ctx.iteration:
        ctx.investigation_history.append({
            "iteration": ctx.iteration,
            "evidence_count": len(ctx.merged_evidence),
            "retrieval_count": len(ctx.retrieval_evidence),
            "verified_claims_count": len(ctx.verified_claims),
            "is_sufficient": is_suff,
            "reason": reason,
            "missing": missing,
        })

    # Strict Zero-Hallucination Gate:
    # Only return INSUFFICIENT_EVIDENCE after the investigation budget is exhausted
    # and repository evidence genuinely cannot establish the requested behavior.
    if not is_suff and (not ctx.retrieval_evidence or reason in ("unsupported_domain_concept", "unsupported_domain_action", "no_matching_evidence", "insufficient_score_threshold")):
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
            "intents": ctx.intents,
            "primary_intent": ctx.primary_intent,
            "iterations_count": ctx.iteration,
            "max_iterations": ctx.max_iterations,
            "investigation_history": ctx.investigation_history,
            "replan_reasons": ctx.replan_reasons,
            "investigation_steps": ctx.investigation_steps,
        }
        db.add(QueryLog(project_id=project_id, user_id=user_id or 0, question=question,
                        answer=res["answer"][:8000], evidence_refs_json="[]"))
        db.commit()
        return res

    # Step 7: DETECT CONTRADICTIONS
    _step_detect_contradictions(ctx)

    # Step 8: EXTRACT MODULES
    _step_extract_modules(ctx)

    # Step 9: EXTRACT RULES & FLOW
    _step_extract_rules_and_flow(ctx)

    # Step 10: ANALYZE GAPS
    _step_analyze_gaps(ctx)

    # Step 11: CALIBRATE CONFIDENCE
    _step_calibrate_confidence(ctx)

    # Step 12: DETERMINE ANSWER STATUS
    _step_determine_answer_status(ctx)
    if not is_suff and ctx.answer_status == "FULLY_ANSWERABLE":
        ctx.answer_status = "PARTIALLY_ANSWERABLE"

    # Try LLM-enhanced answer if available
    llm_result = _try_llm_answer(ctx, db)
    if llm_result:
        llm_result["iterations_count"] = ctx.iteration
        llm_result["max_iterations"] = ctx.max_iterations
        llm_result["investigation_history"] = ctx.investigation_history
        llm_result["replan_reasons"] = ctx.replan_reasons
        llm_result["investigation_steps"] = ctx.investigation_steps
        db.add(QueryLog(project_id=project_id, user_id=user_id or 0, question=question,
                        answer=llm_result["answer"][:8000],
                        evidence_refs_json=json.dumps(llm_result.get("evidence", [])[:12])))
        db.commit()
        return llm_result

    # Step 13: SYNTHESIZE ANSWER
    from app.reasoning.reasoning import _facts
    facts = _facts(db, project_id)
    repo_overview = facts.get("repo_overview", "")
    answer_text = _step_synthesize_answer(ctx, repo_overview=repo_overview)

    # Build final result
    result = {
        "status": "SUCCESS",
        "answer_status": ctx.answer_status,
        "answer": answer_text,
        "current_behaviour": redact_secrets(_build_business_explanation(ctx, repo_overview)),
        "functional_flow": [redact_secrets(s) for s in ctx.flow_steps],
        "business_rules": [redact_secrets(r) for r in ctx.business_rules],
        "affected_modules": ctx.affected_modules,
        "evidence": ctx.verified_claims,
        "claims_grounding": _build_claims_grounding(ctx),
        "confidence": ctx.confidence,
        "guard_dropped": ctx.dropped_claims,
        "query_plan": getattr(ctx.query_intent, "query_plan", {}),
        "intents": ctx.intents,
        "primary_intent": ctx.primary_intent,
        "gaps": ctx.gaps,
        "iterations_count": ctx.iteration,
        "max_iterations": ctx.max_iterations,
        "investigation_history": ctx.investigation_history,
        "replan_reasons": ctx.replan_reasons,
        "investigation_steps": ctx.investigation_steps,
    }

    # Add AIM navigation metadata
    if ctx.lineage_traces:
        result["data_lineage"] = ctx.lineage_traces[:5]
    if ctx.state_machines:
        result["state_machines"] = ctx.state_machines[:3]
    if ctx.decision_rules:
        result["decision_rules_matched"] = len(ctx.decision_rules)

    db.add(QueryLog(project_id=project_id, user_id=user_id or 0, question=question,
                    answer=result["answer"][:8000], evidence_refs_json=json.dumps(ctx.verified_claims[:12])))
    db.commit()
    return result


# ---------------------------------------------------------------------------
# Helper: LLM-enhanced answer path
# ---------------------------------------------------------------------------

def _try_llm_answer(ctx: InvestigationContext, db: Session) -> dict[str, Any] | None:
    """Attempt LLM-enhanced answer synthesis. Returns None if offline."""
    try:
        raw = llm_complete(
            templates.FUNCTIONAL_QA.render(
                question=ctx.effective_question,
                retrieved_evidence_chunks=json.dumps(ctx.retrieval_evidence)[:14000]
            ),
            ""
        )
        import re
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            data = json.loads(m.group(0))
            llm_kept, llm_dropped = check_evidence(data.get("evidence", []), ctx.retrieval_evidence)
            data["evidence"] = llm_kept
            data["guard_dropped"] = llm_dropped
            data["status"] = "SUCCESS"
            data["answer_status"] = ctx.answer_status
            data["claims_grounding"] = _build_claims_grounding(ctx)
            data["intents"] = ctx.intents
            data["primary_intent"] = ctx.primary_intent
            data["investigation_steps"] = [
                "UNDERSTAND_QUESTION", "NAVIGATE_AIM", "RETRIEVE_EVIDENCE",
                "COLLECT_SUPPLEMENTARY", "MERGE_EVIDENCE", "VERIFY_CLAIMS",
                "LLM_SYNTHESIS",
            ]
            # Ensure required fields
            for k in ["current_behaviour", "functional_flow", "business_rules", "affected_modules", "confidence"]:
                if k not in data:
                    data[k] = getattr(ctx, k.replace("current_behaviour", ""), None) or (
                        ctx.confidence if k == "confidence" else
                        ctx.affected_modules if k == "affected_modules" else
                        ctx.business_rules if k == "business_rules" else
                        ctx.flow_steps if k == "functional_flow" else
                        ""
                    )
            data["answer"] = redact_secrets(data.get("answer", ""))
            return data
    except _OfflineSignal:
        pass
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Helper: Vocabulary-based ambiguity check
# ---------------------------------------------------------------------------

def _check_vocabulary_ambiguity(ctx: InvestigationContext, db: Session) -> dict[str, Any] | None:
    """Check if the question matches multiple repository workflows requiring clarification."""
    p_dir = project_dir(ctx.project_id)
    vocab_path = os.path.join(p_dir, "domain_vocabulary.json")
    if not os.path.exists(vocab_path):
        return None

    try:
        from app.domain_vocabulary import RepositoryDomainVocabulary
        vocab = RepositoryDomainVocabulary.load(vocab_path)
        q_l = ctx.effective_question.lower()

        if not (any(p in q_l for p in ["how are ", "how is ", "how do we handle ", "how does the system handle "]) and
                any(w in q_l for w in ["handle", "handled", "manage", "managed", "deal", "dealt"])):
            return None

        matched = vocab.find_matching_concepts(q_l)
        if not matched:
            return None

        top_mc = matched[0]
        workflows = list(top_mc.related_workflows)
        if not workflows and top_mc.related_concepts:
            workflows = [f"{top_mc.canonical_name}_{rel}" for rel in list(top_mc.related_concepts)[:4]]
        if len(workflows) < 2:
            return None

        wf_list_str = "\n".join(f"- **{wf.replace('_', ' ').title()}**" for wf in workflows[:4])
        ambiguous_answer = (
            f"In this repository, **{top_mc.canonical_name.replace('_', ' ').title()}** is associated with "
            f"multiple distinct functional workflows:\n\n"
            f"{wf_list_str}\n\n"
            f"Because multiple implementations exist, please clarify which specific workflow or operation you would like to explore."
        )
        return {
            "status": "SUCCESS",
            "answer_status": "AMBIGUOUS",
            "answer": ambiguous_answer,
            "current_behaviour": f"Multiple repository-supported workflows exist for {top_mc.canonical_name}.",
            "functional_flow": [f"Candidate workflow: {wf.replace('_', ' ').title()}" for wf in workflows[:4]],
            "business_rules": [],
            "affected_modules": [],
            "evidence": [],
            "claims_grounding": [],
            "confidence": "Medium",
            "reason": "multiple_repository_interpretations",
            "missing_concepts": [],
            "gaps": ["Multiple repository workflows match this concept; user clarification requested."],
            "guard_dropped": 0,
            "ambiguity_candidates": workflows[:4],
            "intents": ctx.intents,
            "primary_intent": ctx.primary_intent,
            "investigation_steps": ["UNDERSTAND_QUESTION", "VOCABULARY_AMBIGUITY_CHECK"],
        }
    except Exception:
        return None
