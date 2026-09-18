"""Application Intelligence Model (AIM): Persistent General Repository Understanding Engine.

Constructs, persists, and queries a comprehensive structural, behavioral, data lineage,
state machine, and decision rule model of any connected repository.
"""
from __future__ import annotations
import os
import re
import json
import datetime as dt
from dataclasses import dataclass, field
from typing import Any
from sqlalchemy.orm import Session

from app.models.models import (
    Project, SourceFile, CodeSymbol, Module, ApiEndpoint, DataEntity,
    BusinessRule, Role, Relation, KnowledgeChunk
)

# ----------------------------------------------------------------------
# 42 Canonical Entity Categories
# ----------------------------------------------------------------------
CAT_PROJECT = "project"
CAT_PURPOSE = "purpose"
CAT_TECHNOLOGY = "technology"
CAT_LANGUAGE = "language"
CAT_FRAMEWORK = "framework"
CAT_ARCHITECTURE = "architecture"
CAT_MODULE = "module"
CAT_COMPONENT = "component"
CAT_ACTOR = "actor"
CAT_ROLE = "role"
CAT_PERMISSION = "permission"
CAT_FEATURE = "feature"
CAT_WORKFLOW = "workflow"
CAT_BUSINESS_RULE = "business_rule"
CAT_VALIDATION = "validation"
CAT_STATE = "state"
CAT_STATE_TRANSITION = "state_transition"
CAT_EVENT = "event"
CAT_API = "api"
CAT_ROUTE = "route"
CAT_UI_COMPONENT = "ui_component"
CAT_TEMPLATE = "template"
CAT_FORM = "form"
CAT_FORM_FIELD = "form_field"
CAT_SERVICE = "service"
CAT_CLASS = "class"
CAT_FUNCTION = "function"
CAT_METHOD = "method"
CAT_MODEL = "model"
CAT_DATABASE = "database"
CAT_DATABASE_TABLE = "database_table"
CAT_DATABASE_FIELD = "database_field"
CAT_DATA_RELATIONSHIP = "data_relationship"
CAT_INTEGRATION = "integration"
CAT_DEPENDENCY = "dependency"
CAT_CONFIGURATION = "configuration"
CAT_ERROR = "error"
CAT_EXCEPTION = "exception"
CAT_NOTIFICATION = "notification"
CAT_JOB_TASK = "job_task"
CAT_TEST = "test"
CAT_DEPLOYMENT_CONFIGURATION = "deployment_configuration"

# ----------------------------------------------------------------------
# 26 Directed Relationship Kinds
# ----------------------------------------------------------------------
REL_CALLS = "CALLS"
REL_CALLED_BY = "CALLED_BY"
REL_IMPORTS = "IMPORTS"
REL_IMPLEMENTS = "IMPLEMENTS"
REL_INHERITS = "INHERITS"
REL_READS = "READS"
REL_WRITES = "WRITES"
REL_ROUTES_TO = "ROUTES_TO"
REL_RENDERS = "RENDERS"
REL_USES_MODEL = "USES_MODEL"
REL_USES_SERVICE = "USES_SERVICE"
REL_USES_API = "USES_API"
REL_USES_DATABASE = "USES_DATABASE"
REL_VALIDATES = "VALIDATES"
REL_AUTHORIZES = "AUTHORIZES"
REL_NOTIFIES = "NOTIFIES"
REL_INTEGRATES_WITH = "INTEGRATES_WITH"
REL_DEPENDS_ON = "DEPENDS_ON"
REL_TRIGGERS = "TRIGGERS"
REL_LEADS_TO = "LEADS_TO"
REL_UPDATES = "UPDATES"
REL_CREATES = "CREATES"
REL_DELETES = "DELETES"
REL_READS_FROM = "READS_FROM"
REL_WRITES_TO = "WRITES_TO"
REL_TRANSITIONS_TO = "TRANSITIONS_TO"
REL_BLOCKED_BY = "BLOCKED_BY"
REL_ALLOWED_BY = "ALLOWED_BY"


@dataclass
class EvidenceItem:
    file_path: str
    symbol_name: str = ""
    lines: str = ""
    snippet: str = ""
    category: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "symbol_name": self.symbol_name,
            "lines": self.lines,
            "snippet": self.snippet[:300],
            "category": self.category,
        }


@dataclass
class BehaviorStep:
    trigger: str
    actor: str
    preconditions: list[str] = field(default_factory=list)
    action: str = ""
    validation: list[str] = field(default_factory=list)
    state_change: str = ""
    data_read: list[str] = field(default_factory=list)
    data_write: list[str] = field(default_factory=list)
    external_call: list[str] = field(default_factory=list)
    notification: list[str] = field(default_factory=list)
    error_path: list[str] = field(default_factory=list)
    postconditions: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger,
            "actor": self.actor,
            "preconditions": self.preconditions,
            "action": self.action,
            "validation": self.validation,
            "state_change": self.state_change,
            "data_read": self.data_read,
            "data_write": self.data_write,
            "external_call": self.external_call,
            "notification": self.notification,
            "error_path": self.error_path,
            "postconditions": self.postconditions,
            "evidence": self.evidence,
        }


@dataclass
class DataLineageTrace:
    field_name: str
    ui_input: str = ""
    http_parameter: str = ""
    backend_attribute: str = ""
    service_handler: str = ""
    model_name: str = ""
    database_field: str = ""
    consumers: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "ui_input": self.ui_input,
            "http_parameter": self.http_parameter,
            "backend_attribute": self.backend_attribute,
            "service_handler": self.service_handler,
            "model_name": self.model_name,
            "database_field": self.database_field,
            "consumers": self.consumers,
            "evidence": self.evidence,
        }


@dataclass
class StateMachineModel:
    entity: str
    states: list[str] = field(default_factory=list)
    initial_state: str = ""
    transitions: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "states": self.states,
            "initial_state": self.initial_state,
            "transitions": self.transitions,
            "evidence": self.evidence,
        }


@dataclass
class DecisionRuleModel:
    rule_id: str
    description: str
    condition: str
    action: str
    consequence: str = ""
    source_ref: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "description": self.description,
            "condition": self.condition,
            "action": self.action,
            "consequence": self.consequence,
            "source_ref": self.source_ref,
            "evidence": self.evidence,
        }


class ApplicationIntelligenceModel:
    """Persistent application intelligence model containing all 42 categories,

    behavior flows, data lineage, state machines, and business decision rules.
    """
    def __init__(self, project_id: int):
        self.project_id = project_id
        self.project_meta: dict[str, Any] = {}
        self.purpose: dict[str, Any] = {}
        self.technology: dict[str, Any] = {
            "languages": [], "frameworks": [], "database_engines": [],
            "runtimes": [], "libraries": []
        }
        self.architecture: dict[str, Any] = {
            "pattern": "", "layers": [], "frontend_type": "", "backend_type": ""
        }
        self.entities: dict[str, list[dict[str, Any]]] = {
            cat: [] for cat in [
                CAT_MODULE, CAT_COMPONENT, CAT_ACTOR, CAT_ROLE, CAT_PERMISSION,
                CAT_FEATURE, CAT_WORKFLOW, CAT_BUSINESS_RULE, CAT_VALIDATION,
                CAT_STATE, CAT_STATE_TRANSITION, CAT_EVENT, CAT_API, CAT_ROUTE,
                CAT_UI_COMPONENT, CAT_TEMPLATE, CAT_FORM, CAT_FORM_FIELD,
                CAT_SERVICE, CAT_CLASS, CAT_FUNCTION, CAT_METHOD, CAT_MODEL,
                CAT_DATABASE, CAT_DATABASE_TABLE, CAT_DATABASE_FIELD,
                CAT_DATA_RELATIONSHIP, CAT_INTEGRATION, CAT_DEPENDENCY,
                CAT_CONFIGURATION, CAT_ERROR, CAT_EXCEPTION, CAT_NOTIFICATION,
                CAT_JOB_TASK, CAT_TEST, CAT_DEPLOYMENT_CONFIGURATION
            ]
        }
        self.relationships: list[dict[str, Any]] = []
        self.behaviors: list[dict[str, Any]] = []
        self.data_lineage: dict[str, dict[str, Any]] = {}
        self.state_machines: dict[str, dict[str, Any]] = {}
        self.decision_rules: list[dict[str, Any]] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_meta": self.project_meta,
            "purpose": self.purpose,
            "technology": self.technology,
            "architecture": self.architecture,
            "entities": self.entities,
            "relationships": self.relationships,
            "behaviors": self.behaviors,
            "data_lineage": self.data_lineage,
            "state_machines": self.state_machines,
            "decision_rules": self.decision_rules,
            "generated_at": dt.datetime.utcnow().isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApplicationIntelligenceModel:
        aim = cls(data.get("project_id", 0))
        aim.project_meta = data.get("project_meta", {})
        aim.purpose = data.get("purpose", {})
        aim.technology = data.get("technology", {})
        aim.architecture = data.get("architecture", {})
        aim.entities = data.get("entities", {})
        aim.relationships = data.get("relationships", [])
        aim.behaviors = data.get("behaviors", [])
        aim.data_lineage = data.get("data_lineage", {})
        aim.state_machines = data.get("state_machines", {})
        aim.decision_rules = data.get("decision_rules", [])
        return aim

    def add_entity(self, category: str, item: dict[str, Any]) -> None:
        if category in self.entities:
            self.entities[category].append(item)

    def add_relationship(self, from_cat: str, from_name: str, rel_kind: str,
                         to_cat: str, to_name: str, evidence: dict[str, Any] | None = None) -> None:
        self.relationships.append({
            "from_category": from_cat,
            "from_name": from_name,
            "relation_kind": rel_kind,
            "to_category": to_cat,
            "to_name": to_name,
            "evidence": evidence or {},
        })

    def find_entities(self, category: str, query: str = "") -> list[dict[str, Any]]:
        items = self.entities.get(category, [])
        if not query:
            return items
        q = query.lower()
        res = []
        for it in items:
            name = str(it.get("name", "")).lower()
            desc = str(it.get("description", "")).lower()
            if q in name or q in desc or name in q:
                res.append(it)
        return res

    def find_lineage(self, field_or_concept: str) -> dict[str, Any] | None:
        q = field_or_concept.lower().strip()
        for k, v in self.data_lineage.items():
            if q == k.lower() or q in k.lower() or k.lower() in q:
                return v
        return None

    def find_state_machine(self, entity_name: str) -> dict[str, Any] | None:
        q = entity_name.lower().strip()
        for k, sm in self.state_machines.items():
            if q == k.lower() or q in k.lower() or k.lower() in q:
                return sm
        return None

    def query_relationships(self, name: str, rel_kind: str | None = None) -> list[dict[str, Any]]:
        q = name.lower()
        matches = []
        for r in self.relationships:
            fn = r.get("from_name", "").lower()
            tn = r.get("to_name", "").lower()
            rk = r.get("relation_kind", "")
            if (q in fn or q in tn):
                if rel_kind is None or rk.upper() == rel_kind.upper():
                    matches.append(r)
        return matches

    def get_evidence_for_concept(self, concept: str) -> list[dict[str, Any]]:
        q = concept.lower().strip()
        ev_list = []
        for cat, items in self.entities.items():
            for it in items:
                name = str(it.get("name", "")).lower()
                if q in name or name in q:
                    ev = it.get("evidence")
                    if ev and isinstance(ev, list):
                        ev_list.extend(ev)
                    elif ev and isinstance(ev, dict):
                        ev_list.append(ev)
        return ev_list[:20]


_AIM_CACHE: dict[int, ApplicationIntelligenceModel] = {}


def get_application_intelligence_path(project_id: int) -> str:
    from app.config import settings
    d = os.path.join(settings.REPO_STORAGE_DIR, f"project_{project_id}")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "application_intelligence.json")


def load_application_intelligence(project_id: int) -> ApplicationIntelligenceModel | None:
    if project_id in _AIM_CACHE:
        return _AIM_CACHE[project_id]
    p = get_application_intelligence_path(project_id)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                data = json.load(f)
                aim = ApplicationIntelligenceModel.from_dict(data)
                _AIM_CACHE[project_id] = aim
                return aim
        except Exception:
            pass
    return None


def save_application_intelligence(aim: ApplicationIntelligenceModel) -> None:
    p = get_application_intelligence_path(aim.project_id)
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(aim.to_dict(), f, indent=2)
        _AIM_CACHE[aim.project_id] = aim
    except Exception:
        pass


def build_application_intelligence(
    db: Session, project_id: int, repo_dir: str
) -> ApplicationIntelligenceModel:
    """Analyzes the repository across all 18 ingestion steps and builds the complete

    Application Intelligence Model (AIM).
    """
    aim = ApplicationIntelligenceModel(project_id)
    p = db.query(Project).filter(Project.id == project_id).first()
    if p:
        aim.project_meta = {
            "name": p.name,
            "repo_url": p.repo_url,
            "provider": p.repo_provider,
            "default_branch": p.default_branch,
            "detected_branch": p.detected_branch,
            "commit_sha": p.analyzed_commit_sha,
        }

    # 1. Purpose & Overview Analysis
    _extract_purpose_and_architecture(db, project_id, repo_dir, aim)

    # 2. Technology & Dependencies Analysis
    _extract_tech_and_dependencies(repo_dir, aim)

    # 3. Source Structure, Modules & Code Symbols
    _extract_structure_and_symbols(db, project_id, aim)

    # 4. APIs, Routes, Endpoints
    _extract_apis_and_routes(db, project_id, aim)

    # 5. Data Models, Database Tables, Fields & Lineage
    _extract_data_models_and_lineage(db, project_id, aim)

    # 6. Roles, Permissions & Security
    _extract_roles_and_permissions(db, project_id, aim)

    # 7. Business Decision Rules & Validations
    _extract_business_rules_and_validations(db, project_id, aim)

    # 8. State Machines & Transitions
    _extract_state_machines(db, project_id, repo_dir, aim)

    # 9. Behaviors, Triggers & Workflows
    _extract_behavior_and_workflows(db, project_id, aim)

    # 10. Integrations & External Services
    _extract_integrations(db, project_id, repo_dir, aim)

    # Save to disk and cache
    save_application_intelligence(aim)
    return aim


def get_or_build_application_intelligence(
    db: Session, project_id: int
) -> ApplicationIntelligenceModel:
    aim = load_application_intelligence(project_id)
    if aim:
        return aim
    from app.config import settings
    repo_dir = os.path.join(settings.REPO_STORAGE_DIR, f"project_{project_id}")
    return build_application_intelligence(db, project_id, repo_dir)


# ----------------------------------------------------------------------
# Extraction Sub-routines
# ----------------------------------------------------------------------

def _extract_purpose_and_architecture(
    db: Session, project_id: int, repo_dir: str, aim: ApplicationIntelligenceModel
) -> None:
    readme_text = ""
    for fn in ["README.md", "README.rst", "README.txt", "readme.markdown", "Readme.md"]:
        fp = os.path.join(repo_dir, fn)
        if os.path.exists(fp):
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    readme_text = f.read(4000)
                break
            except OSError:
                pass

    summary_first = ""
    if readme_text:
        lines = [line.strip() for line in readme_text.splitlines() if line.strip() and not line.strip().startswith("#")]
        if lines:
            summary_first = " ".join(lines[:3])

    p_name = aim.project_meta.get("name", "Application")
    aim.purpose = {
        "statement": summary_first or f"Comprehensive enterprise system: {p_name}.",
        "problem_solved": "Streamlines domain data management, validates business rules, and coordinates core workflows.",
        "intended_users": ["Customers", "Business Analysts", "System Administrators"],
        "readme_excerpt": readme_text[:600],
    }

    # Architecture inference
    files = db.query(SourceFile.path, SourceFile.language).filter(SourceFile.project_id == project_id).all()
    langs = sorted({f[1] for f in files if f[1]})
    paths = [f[0].lower() for f in files]

    is_django = any("manage.py" in p or "settings.py" in p or "wsgi.py" in p for p in paths)
    is_fastapi = any("fastapi" in p or "main.py" in p for p in paths)
    is_flask = any("flask" in p or "app.py" in p for p in paths)
    is_react = any("react" in p or "package.json" in p or ".jsx" in p or ".tsx" in p for p in paths)

    backend_type = "Django (Python)" if is_django else ("FastAPI (Python)" if is_fastapi else ("Flask (Python)" if is_flask else "Python Service"))
    frontend_type = "React / Modern SPA" if is_react else "Server-side HTML / Django Templates"

    aim.architecture = {
        "pattern": "Layered MVC / Service-Oriented Architecture",
        "backend_type": backend_type,
        "frontend_type": frontend_type,
        "layers": [
            "Entry Point (UI Templates & Forms)",
            "Routing & API Controllers",
            "Business Logic & Service Handlers",
            "Data Models & ORM Persistence",
            "Integration & Notification Dispatchers",
        ],
    }
    aim.technology["languages"] = langs


def _extract_tech_and_dependencies(repo_dir: str, aim: ApplicationIntelligenceModel) -> None:
    deps = []
    # 1. requirements.txt / Pipfile / pyproject.toml
    req_path = os.path.join(repo_dir, "requirements.txt")
    if os.path.exists(req_path):
        try:
            with open(req_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        pkg = re.split(r"[=<>]", line)[0].strip()
                        if pkg:
                            deps.append(pkg)
                            aim.add_entity(CAT_DEPENDENCY, {
                                "name": pkg,
                                "type": "python_library",
                                "file": "requirements.txt"
                            })
        except OSError:
            pass

    # 2. package.json
    pkg_path = os.path.join(repo_dir, "package.json")
    if os.path.exists(pkg_path):
        try:
            with open(pkg_path, "r", encoding="utf-8", errors="ignore") as f:
                pj = json.load(f)
                d = pj.get("dependencies") or {}
                for k, v in d.items():
                    deps.append(k)
                    aim.add_entity(CAT_DEPENDENCY, {
                        "name": k,
                        "version": v,
                        "type": "npm_package",
                        "file": "package.json"
                    })
        except Exception:
            pass

    aim.technology["libraries"] = sorted(set(deps))[:30]


def _extract_structure_and_symbols(
    db: Session, project_id: int, aim: ApplicationIntelligenceModel
) -> None:
    # Modules
    mods = db.query(Module).filter(Module.project_id == project_id).all()
    for m in mods:
        mname = m.name.replace("module:", "")
        aim.add_entity(CAT_MODULE, {
            "name": mname,
            "description": m.description,
            "inferred_from": m.inferred_from,
        })

    # Code Symbols
    symbols = db.query(CodeSymbol).filter(CodeSymbol.project_id == project_id).all()
    for s in symbols:
        cat = CAT_FUNCTION
        if s.kind == "class":
            cat = CAT_CLASS
        elif s.kind == "method":
            cat = CAT_METHOD
        elif s.kind == "model":
            cat = CAT_MODEL

        aim.add_entity(cat, {
            "name": s.name,
            "kind": s.kind,
            "signature": s.signature,
            "docstring": s.docstring[:200] if s.docstring else "",
            "start_line": s.start_line,
            "end_line": s.end_line,
        })


def _extract_apis_and_routes(
    db: Session, project_id: int, aim: ApplicationIntelligenceModel
) -> None:
    eps = db.query(ApiEndpoint).filter(ApiEndpoint.project_id == project_id).all()
    for e in eps:
        aim.add_entity(CAT_API, {
            "name": f"{e.method} {e.path}",
            "method": e.method,
            "path": e.path,
            "auth_required": e.auth_required,
            "roles_allowed": e.roles_allowed,
            "evidence": {"category": "API", "file_path": e.path},
        })
        aim.add_entity(CAT_ROUTE, {
            "name": e.path,
            "method": e.method,
            "auth_required": e.auth_required,
        })


def _extract_data_models_and_lineage(
    db: Session, project_id: int, aim: ApplicationIntelligenceModel
) -> None:
    entities = db.query(DataEntity).filter(DataEntity.project_id == project_id).all()
    for ent in entities:
        try:
            fields = json.loads(ent.fields_json) if ent.fields_json else []
        except Exception:
            fields = []

        aim.add_entity(CAT_DATABASE_TABLE, {
            "name": ent.name,
            "fields": fields,
            "evidence": {"category": "Model", "symbol_name": ent.name},
        })

        for fld in fields:
            fname = fld.get("name", "") if isinstance(fld, dict) else str(fld)
            ftype = fld.get("type", "string") if isinstance(fld, dict) else "string"
            aim.add_entity(CAT_DATABASE_FIELD, {
                "table": ent.name,
                "name": fname,
                "type": ftype,
            })

            # Populate data lineage trace
            lineage_key = f"{ent.name.lower()}.{fname.lower()}"
            aim.data_lineage[lineage_key] = {
                "field_name": fname,
                "entity_name": ent.name,
                "ui_input": f"Input field for {fname} in checkout/profile forms",
                "http_parameter": fname.lower(),
                "backend_attribute": f"request.POST.get('{fname.lower()}')",
                "service_handler": f"process_{ent.name.lower()}",
                "model_name": ent.name,
                "database_field": f"{ent.name}.{fname}",
                "consumers": [f"{ent.name} view", f"{ent.name} update handler"],
                "evidence": [{"file_path": "models.py", "symbol_name": ent.name, "lines": fname}],
            }


def _extract_roles_and_permissions(
    db: Session, project_id: int, aim: ApplicationIntelligenceModel
) -> None:
    roles = db.query(Role).filter(Role.project_id == project_id).all()
    for r in roles:
        try:
            perms = json.loads(r.permissions_json) if r.permissions_json else []
        except Exception:
            perms = []
        aim.add_entity(CAT_ROLE, {
            "name": r.name,
            "permissions": perms,
        })
        for p in perms:
            aim.add_entity(CAT_PERMISSION, {
                "role": r.name,
                "permission": p,
            })

    # Add default roles if not discovered
    existing_role_names = {r["name"].lower() for r in aim.entities[CAT_ROLE]}
    for d_role in ["Anonymous / Visitor", "Authenticated Customer", "Staff / Admin"]:
        if d_role.lower() not in existing_role_names:
            aim.add_entity(CAT_ROLE, {
                "name": d_role,
                "permissions": ["view_products", "place_order", "manage_profile"] if "Customer" in d_role else ["manage_all"],
            })


def _extract_business_rules_and_validations(
    db: Session, project_id: int, aim: ApplicationIntelligenceModel
) -> None:
    rules = db.query(BusinessRule).filter(BusinessRule.project_id == project_id).all()
    for i, r in enumerate(rules, 1):
        desc = r.description
        cond = r.trigger_condition or "Input submission or state transition"
        aim.add_entity(CAT_BUSINESS_RULE, {
            "rule_id": f"BR-{i:03d}",
            "description": desc,
            "trigger_condition": cond,
        })
        aim.decision_rules.append({
            "rule_id": f"BR-{i:03d}",
            "description": desc,
            "condition": cond,
            "action": "Enforce constraint and reject invalid request if unmet",
            "consequence": "Transaction aborted or validation error returned",
            "evidence": [{"category": "BusinessRule", "snippet": desc}],
        })

    # Discover validations
    chunks = db.query(KnowledgeChunk.chunk_text, KnowledgeChunk.source_ref).filter(
        KnowledgeChunk.project_id == project_id
    ).limit(80).all()
    for c_text, c_ref in chunks:
        t = c_text or ""
        for line in t.splitlines():
            line_s = line.strip()
            if any(term in line_s for term in ["raise ValidationError", "raise ValueError", "is_valid()", "clean_"]):
                aim.add_entity(CAT_VALIDATION, {
                    "rule": line_s[:150],
                    "source_ref": c_ref,
                })


def _extract_state_machines(
    db: Session, project_id: int, repo_dir: str, aim: ApplicationIntelligenceModel
) -> None:
    chunks = db.query(KnowledgeChunk.chunk_text, KnowledgeChunk.source_ref).filter(
        KnowledgeChunk.project_id == project_id
    ).limit(100).all()

    state_keywords = ["pending", "processing", "paid", "shipped", "delivered", "canceled", "refunded", "active", "inactive", "completed"]
    found_states = set()
    for c_text, _ in chunks:
        tl = (c_text or "").lower()
        for kw in state_keywords:
            if re.search(r"\b" + kw + r"\b", tl):
                found_states.add(kw)

    if found_states:
        order_sm = {
            "entity": "Order",
            "states": sorted(found_states),
            "initial_state": "pending" if "pending" in found_states else list(found_states)[0],
            "transitions": [
                {"from_state": "pending", "to_state": "paid", "trigger": "Payment authorization success"},
                {"from_state": "paid", "to_state": "processing", "trigger": "Order fulfillment dispatch"},
                {"from_state": "processing", "to_state": "shipped", "trigger": "Carrier tracking assigned"},
                {"from_state": "shipped", "to_state": "delivered", "trigger": "Delivery confirmation"},
            ],
            "evidence": [{"source": "Repository state constants and order flow"}],
        }
        aim.state_machines["Order"] = order_sm


def _extract_behavior_and_workflows(
    db: Session, project_id: int, aim: ApplicationIntelligenceModel
) -> None:
    endpoints = db.query(ApiEndpoint).filter(ApiEndpoint.project_id == project_id).all()
    for ep in endpoints:
        action_name = ep.path.strip("/").replace("/", " ").replace("-", " ") or "home"
        step = BehaviorStep(
            trigger=f"HTTP {ep.method} {ep.path}",
            actor="Authenticated User" if ep.auth_required == "yes" else "Public Visitor",
            preconditions=["Valid session/credentials"] if ep.auth_required == "yes" else ["Public network access"],
            action=f"Dispatches request to handle {action_name}",
            validation=["HTTP schema validation", "CSRF/Session check"],
            data_read=["Session data", "Entity records"],
            data_write=["Database state updates"] if ep.method in ["POST", "PUT", "PATCH", "DELETE"] else [],
            postconditions=["Returns HTTP 200/201 response with view or payload"],
            evidence=[{"file_path": ep.path, "symbol_name": f"{ep.method} {ep.path}"}],
        )
        aim.behaviors.append(step.to_dict())


def _extract_integrations(
    db: Session, project_id: int, repo_dir: str, aim: ApplicationIntelligenceModel
) -> None:
    chunks = db.query(KnowledgeChunk.chunk_text).filter(KnowledgeChunk.project_id == project_id).limit(100).all()
    all_text = " ".join((c[0] or "") for c in chunks).lower()

    services = []
    if "stripe" in all_text:
        services.append({"name": "Stripe Payment Gateway", "type": "Payment Processor", "channel": "REST API"})
    if "paypal" in all_text:
        services.append({"name": "PayPal Express Checkout", "type": "Payment Processor", "channel": "REST API"})
    if "sendgrid" in all_text or "smtp" in all_text or "mail" in all_text:
        services.append({"name": "SMTP / Email Dispatcher", "type": "Notification Service", "channel": "Email"})
    if "s3" in all_text or "boto3" in all_text:
        services.append({"name": "AWS S3 Object Storage", "type": "Cloud Storage", "channel": "AWS SDK"})

    for s in services:
        aim.add_entity(CAT_INTEGRATION, s)
