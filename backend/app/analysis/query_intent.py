"""General Question Engine: 30+ Intent Taxonomy, Dynamic Noun Chunking,
Query Planning, and Contextual Follow-up Resolution.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

# Taxonomy Intent Constants
INTENT_PURPOSE = "PURPOSE"
INTENT_CAPABILITY = "CAPABILITY"
INTENT_FEATURE = "FEATURE"
INTENT_USER_ROLE = "USER_ROLE"
INTENT_PERMISSION_AUTH = "PERMISSION_AUTH"
INTENT_WORKFLOW = "WORKFLOW"
INTENT_HOW_IT_WORKS = "HOW_IT_WORKS"
INTENT_WHY_BUSINESS_RULE = "WHY_BUSINESS_RULE"
INTENT_VALIDATION = "VALIDATION"
INTENT_ERROR_HANDLING = "ERROR_HANDLING"
INTENT_LIFECYCLE_STATUS = "LIFECYCLE_STATUS"
INTENT_DATA_ENTITY = "DATA_ENTITY"
INTENT_DATABASE = "DATABASE"
INTENT_API = "API"
INTENT_INTEGRATION = "INTEGRATION"
INTENT_DEPENDENCY = "DEPENDENCY"
INTENT_ARCHITECTURE = "ARCHITECTURE"
INTENT_MODULE = "MODULE"
INTENT_CONFIGURATION = "CONFIGURATION"
INTENT_NOTIFICATION = "NOTIFICATION"
INTENT_EVENT = "EVENT"
INTENT_BACKGROUND_JOB = "BACKGROUND_JOB"
INTENT_SCHEDULE = "SCHEDULE"
INTENT_SECURITY = "SECURITY"
INTENT_PERFORMANCE = "PERFORMANCE"
INTENT_ENHANCEMENT_IMPACT = "ENHANCEMENT_IMPACT"
INTENT_RISK = "RISK"
INTENT_TESTING = "TESTING"
INTENT_COMPARISON = "COMPARISON"
INTENT_UNKNOWN_GENERAL = "UNKNOWN_GENERAL"
INTENT_GENERAL_FUNCTIONAL = "GENERAL_FUNCTIONAL"

# Common stopwords, generic verbs, auxiliaries, and question words to exclude from domain entities
STOPWORDS = {
    # Articles, demonstratives, pronouns
    "the", "a", "an", "this", "that", "these", "those",
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "their", "our", "its", "someone", "anyone", "everyone", "nobody",
    # Question words
    "what", "which", "who", "whom", "whose", "why", "how", "when", "where",
    # Prepositions & conjunctions
    "and", "or", "but", "if", "because", "as", "until", "while", "of", "at", "by",
    "for", "with", "about", "against", "between", "into", "through", "during",
    "before", "after", "above", "below", "to", "from", "up", "down", "in", "out",
    "on", "off", "over", "under", "again", "further", "then", "once", "here", "there",
    "all", "any", "both", "each", "few", "more", "most", "other", "some", "such",
    "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very",
    "instead", "rather", "without", "within", "along", "across", "via",
    # Auxiliaries & modal verbs
    "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "having",
    "do", "does", "did", "doing", "done",
    "would", "should", "could", "ought", "can", "will", "shall", "may", "might", "must",
    # Generic verbs (MUST NOT be treated as domain concepts)
    "used", "use", "uses", "using", "usage",
    "get", "gets", "getting", "got", "gotten",
    "happen", "happens", "happened", "happening",
    "work", "works", "worked", "working",
    "involve", "involves", "involved", "involving",
    "include", "includes", "included", "including",
    "contain", "contains", "contained", "containing",
    "require", "requires", "required", "requiring",
    "relate", "relates", "related", "relating",
    "make", "makes", "made", "making",
    "take", "takes", "took", "taken", "taking",
    "give", "gives", "gave", "given", "giving",
    "look", "looks", "looked", "looking",
    "see", "sees", "saw", "seen", "seeing",
    "tell", "tells", "told", "telling",
    "show", "shows", "showed", "shown", "showing",
    "find", "finds", "found", "finding",
    "call", "calls", "called", "calling",
    "try", "tries", "tried", "trying",
    "need", "needs", "needed", "needing",
    "want", "wants", "wanted", "wanting",
    "become", "becomes", "became", "becoming",
    "mean", "means", "meant", "meaning",
    "exist", "exists", "existed", "existing",
    "allow", "allows", "allowed", "allowing",
    "let", "lets", "letting",
    "start", "starts", "started", "starting",
    "stop", "stops", "stopped", "stopping",
    "occur", "occurs", "occurred", "occurring",
    "run", "runs", "ran", "running",
    "solve", "solves", "solved", "solving",
    "go", "goes", "went", "gone", "going",
    "come", "comes", "came", "coming",
    "put", "puts", "putting",
    "set", "sets", "setting",
    "lead", "leads", "led", "leading",
    "add", "adds", "added", "adding",
    "store", "stores", "stored", "storing",
    "keep", "keeps", "kept", "keeping",
    "save", "saves", "saved", "saving",
    "handle", "handles", "handled", "handling",
    "perform", "performs", "performed", "performing",
    "record", "records", "recorded", "recording",
    "trace", "traces", "traced", "tracing",
    "track", "tracks", "tracked", "tracking",
    "walk", "walks", "walked", "walking", "walkthrough",
    "describe", "describes", "described", "describing", "description",
    "explain", "explains", "explained", "explaining", "explanation",
    "list", "lists", "listed", "listing",
    "outline", "outlines", "outlined", "outlining",
    # Generic filler nouns & adverbs/adjectives
    "thing", "things", "way", "ways", "step", "steps",
    "app", "application", "codebase", "project", "system", "repository", "repo",
    "currently", "problem", "problems", "now", "just", "feature", "features",
    "capability", "capabilities", "functionality", "functionalities",
    "new", "whenever", "wherever", "every",
    "data", "info", "information",
    # Architectural & meta terms (MUST NOT be treated as domain concepts)
    "flow", "flows", "frontend", "backend", "database", "db", "api", "apis",
    "route", "routes", "url", "urls", "path", "paths", "view", "views",
    "endpoint", "endpoints", "logic", "code", "function", "functions",
    "method", "methods", "module", "modules", "file", "files",
    "business", "rule", "rules", "prevent", "prevents", "preventing", "block", "blocking",
    "workflow", "workflows", "permission", "permissions", "impact", "impacts", "impacted",
    "change", "changes", "support", "area", "areas", "detail", "details",
    "state", "status", "action", "actions",
}

# Known action stems and variations
ACTION_MAPPINGS = {
    "submit": "submit", "submits": "submit", "submission": "submit", "submitting": "submit", "submitted": "submit",
    "approve": "approve", "approves": "approve", "approval": "approve", "approving": "approve", "approved": "approve",
    "store": "store", "stores": "store", "storing": "store", "stored": "store",
    "edit": "edit", "edits": "edit", "editing": "edit", "edited": "edit", "modify": "edit", "modifies": "edit", "modifying": "edit", "modified": "edit",
    "cancel": "cancel", "cancels": "cancel", "cancellation": "cancel", "cancelling": "cancel", "canceled": "cancel",
    "create": "create", "creates": "create", "creation": "create", "creating": "create", "created": "create",
    "delete": "delete", "deletes": "delete", "deletion": "delete", "deleting": "delete", "deleted": "delete",
    "update": "update", "updating": "update", "updated": "update",
    "generate": "generate", "generation": "generate", "generating": "generate", "generated": "generate",
    "checkout": "checkout", "checking out": "checkout",
    "validate": "validate", "validation": "validate", "validating": "validate",
    "check": "check", "checking": "check", "checked": "check",
    "process": "process", "processing": "process", "processed": "process",
    "pay": "pay", "payment": "pay", "paying": "pay",
    "ship": "ship", "shipping": "ship", "shipped": "ship",
    "lock": "lock", "locking": "lock", "locked": "lock",
    "view": "view", "viewing": "view",
    "send": "send", "sending": "send", "sent": "send",
    "calc": "calculate", "calculate": "calculate", "calculating": "calculate", "calculated": "calculate",
    "track": "track", "tracking": "track",
    "search": "search", "searching": "search",
    "place": "create", "places": "create", "placing": "create", "placed": "create",
    "provide": "provide", "provides": "provide", "provided": "provide", "providing": "provide",
    "enter": "provide", "enters": "provide", "entered": "provide", "entering": "provide",
    "login": "login", "authenticate": "login", "auth": "login",
    "notify": "notify", "notification": "notify", "notifications": "notify", "notified": "notify", "notifying": "notify",
    "alert": "notify", "alerts": "notify",
    "email": "email", "emails": "email",
    "register": "register", "registration": "register", "registering": "register",
    "onboard": "onboard", "onboarding": "onboard",
    "schedule": "schedule", "scheduling": "schedule", "scheduled": "schedule",
    "reject": "reject", "rejection": "reject", "rejected": "reject", "rejects": "reject", "rejecting": "reject",
    "fail": "fail", "fails": "fail", "failed": "fail", "failing": "fail", "failure": "fail",
    "assign": "assign", "assignment": "assign", "assigning": "assign",
    "verify": "verify", "verification": "verify", "verifying": "verify",
    "clean": "clean", "cleaning": "clean", "cleaned": "clean",
    "format": "format", "formatting": "format", "formatted": "format",
    "plot": "view", "plotting": "view", "plotted": "view",
    "predict": "predict", "predicting": "predict", "predicted": "predict",
    "input": "input", "inputs": "input", "inputting": "input",
    "fill": "fill", "fills": "fill", "filling": "fill", "filled": "fill",
    "record": "record", "records": "record", "recording": "record", "recorded": "record",
}

B_TERM_VOCAB = {
    "rule", "rules", "prevent", "prevents", "preventing", "block", "blocking", "blocked",
    "approved", "approval", "pending", "rejected", "locked", "active", "cancelled",
    "validation", "validate", "validating", "limit", "threshold", "permission", "permissions",
    "role", "roles", "admin", "admins", "administrator", "administrators", "business",
    "fail", "fails", "failed", "failure", "reject", "rejection",
}

KNOWN_ROLES = {
    "admin", "administrator", "admins", "administrators",
    "user", "users", "customer", "customers", "client", "clients",
    "manager", "managers", "staff", "member", "members",
    "doctor", "doctors", "patient", "patients", "nurse", "nurses",
    "finance", "accountant", "reviewer", "approver", "auditor",
    "operator", "guest", "anonymous", "authenticated", "citizen",
}

PURPOSE_PATTERNS = [
    "what is this application used for",
    "what is this app used for",
    "what does this application do",
    "what does this app do",
    "what does this system do",
    "what does this project do",
    "what problem does this system solve",
    "what problem does this application solve",
    "what problem does this project solve",
    "what is the purpose of this application",
    "what is the purpose of this app",
    "what is the purpose of this project",
    "what is the purpose of this system",
    "what is the purpose of this",
    "purpose of this application",
    "purpose of this project",
    "purpose of this system",
    "what is this application",
    "what is this project",
    "what is this system",
    "what is this codebase",
    "overview of this application",
    "overview of this project",
    "explain what this project does",
    "explain what this application does",
    "who are the users of this system",
    "who uses this application",
]


@dataclass
class QueryIntent:
    intent: str  # Backward-compatible canonical name ('how', 'why/business rule', 'workflow', etc.)
    intents: list[str] = field(default_factory=list)  # Rich taxonomy tokens
    primary_intent: str = INTENT_HOW_IT_WORKS
    entities: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    business_terms: list[str] = field(default_factory=list)
    raw_query: str = ""
    resolved_query: str = ""
    query_plan: dict = field(default_factory=dict)
    is_ambiguous: bool = False
    clarification_prompt: str = ""


def _singularize_word(w: str) -> str:
    word = w.lower().strip()
    if len(word) <= 3 or word.endswith(("ss", "us", "is")):
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("ses", "xes", "ches", "shes")) and len(word) > 4:
        return word[:-2]
    if word.endswith("s"):
        return word[:-1]
    return word


def _extract_domain_concepts_dynamic(tokens: list[str], words: list[str], roles: list[str] | None = None) -> list[str]:
    """Dynamically extract candidate noun phrases (3-grams, 2-grams, 1-grams)

    without hardcoded domain vocabulary. Excludes stopwords, generic verbs, and action mappings.
    """
    from app.domain_vocabulary import normalize_morphology, COMMON_ACTION_VERBS
    # Identify indices of meaningful candidate tokens
    candidate_indices = []
    for idx, w in enumerate(tokens):
        if len(w) <= 2:
            continue
        w_norm = normalize_morphology(w)
        if (
            w in STOPWORDS
            or w in ACTION_MAPPINGS
            or w in B_TERM_VOCAB
            or w in COMMON_ACTION_VERBS
            or w in KNOWN_ROLES
            or w_norm in ACTION_MAPPINGS
            or w_norm in COMMON_ACTION_VERBS
            or w_norm in STOPWORDS
            or w_norm in KNOWN_ROLES
        ):
            continue
        candidate_indices.append(idx)

    # Group consecutive candidate indices into candidate chunks
    chunks: list[list[int]] = []
    current_chunk: list[int] = []
    for idx in candidate_indices:
        if not current_chunk or idx == current_chunk[-1] + 1:
            current_chunk.append(idx)
        else:
            chunks.append(current_chunk)
            current_chunk = [idx]
    if current_chunk:
        chunks.append(current_chunk)

    extracted: list[str] = []
    seen: set[str] = set()

    def add_concept(c: str):
        c_clean = c.strip()
        if c_clean and c_clean not in seen and len(c_clean) > 2:
            seen.add(c_clean)
            extracted.append(c_clean)

    for ch in chunks:
        ch_tokens = [tokens[i] for i in ch]
        n = len(ch_tokens)

        # 1. Full chunk phrase if length >= 2 (e.g. "missing person report", "customer onboarding")
        if n >= 2:
            full_phrase = " ".join(ch_tokens)
            add_concept(full_phrase)
            # Singularized version of full phrase if ends in 's'
            last_sing = _singularize_word(ch_tokens[-1])
            if last_sing != ch_tokens[-1]:
                add_concept(" ".join(ch_tokens[:-1] + [last_sing]))

        # 2. 2-gram sub-phrases (e.g. "missing person")
        if n >= 3:
            for i in range(n - 1):
                sub_p = " ".join(ch_tokens[i:i+2])
                add_concept(sub_p)
                sub_last = _singularize_word(ch_tokens[i+1])
                if sub_last != ch_tokens[i+1]:
                    add_concept(f"{ch_tokens[i]} {sub_last}")

        # 3. Individual constituent tokens (singularized and base)
        for t in ch_tokens:
            sing = _singularize_word(t)
            add_concept(sing)
            if sing != t:
                add_concept(t)

    # 4. Add individual roles as recognized entities
    for r in (roles or []):
        r_sing = _singularize_word(r)
        add_concept(r_sing)
        if r_sing != r:
            add_concept(r)

    return extracted


def _resolve_follow_up(query: str, history: list[dict] | None = None) -> tuple[str, bool, str]:
    """Resolve pronouns like 'it', 'they', 'that' against prior context."""
    q_lower = query.lower().strip()
    q_norm = re.sub(r"[-_]+", " ", q_lower)

    # 1. Purpose or overview questions are never ambiguous follow-ups
    if any(pat in q_lower or pat in q_norm for pat in PURPOSE_PATTERNS):
        return query, False, ""

    if any(term in q_lower for term in ["this app", "this application", "this project", "this system", "this codebase", "this repo"]):
        return query, False, ""

    stand_alone_pronouns = {"it", "they", "them", "that", "this action", "this request"}
    has_pronoun = any(re.search(r"\b" + re.escape(p) + r"\b", q_lower) for p in stand_alone_pronouns)

    if not has_pronoun or not history:
        # If query is very short with only pronouns (e.g. "who approves it?") and no context:
        words = re.findall(r"[a-zA-Z]+", q_lower)
        non_stops = [w for w in words if w not in STOPWORDS and w not in ACTION_MAPPINGS and w not in B_TERM_VOCAB]
        # Only mark ambiguous if literally 0 domain nouns/actions and a stand-alone pronoun is present
        if len(non_stops) == 0 and has_pronoun and len(words) <= 5:
            return query, True, "Could you please clarify which feature, request, or domain entity you are referring to?"
        return query, False, ""

    # Find the most recent domain entity in history
    last_entity = ""
    for item in reversed(history):
        prev_q = item.get("question", "")
        prev_qi = analyze_query(prev_q, history=None)
        if prev_qi.entities:
            last_entity = prev_qi.entities[0]
            break

    if last_entity:
        resolved = re.sub(r"\b(it|that|this action|this request)\b", last_entity, query, flags=re.IGNORECASE)
        return resolved, False, ""

    return query, False, ""


def analyze_query(query: str, history: list[dict] | None = None) -> QueryIntent:
    """Classify 30+ intent taxonomy, dynamically extract concepts, and construct internal query plan."""
    resolved_query, is_ambiguous, clarification = _resolve_follow_up(query, history)
    q = resolved_query.strip()
    q_lower = q.lower()
    q_normalized = re.sub(r"[-_]+", " ", q_lower)

    # 1. Multi-Dimensional Taxonomy Intent Classification
    classified_intents: list[str] = []

    # PURPOSE / OVERVIEW
    has_purpose_phrase = (
        any(pat in q_lower or pat in q_normalized for pat in PURPOSE_PATTERNS) or
        bool(re.search(r"\b(?:what\s+(?:does\s+)?(?:this|the)\s+(?:\w+\s+)?(?:app|application|project|system|codebase)\s+(?:actually\s+)?(?:do|does))\b", q_lower)) or
        bool(re.search(r"\b(?:tell\s+me|explain|describe)\s+what\s+(?:this|the)\s+(?:\w+\s+)?(?:app|application|project|system)\b", q_lower)) or
        "what does this app" in q_lower or "what does this project" in q_lower
    )
    if has_purpose_phrase:
        classified_intents.append(INTENT_PURPOSE)

    # USER & ROLE
    if any(p in q_lower for p in ["who are the users", "user role", "roles in", "what can an admin", "who can", "which role", "what roles"]):
        classified_intents.append(INTENT_USER_ROLE)

    # PERMISSION & AUTHORIZATION
    if any(p in q_lower for p in ["who can approve", "permission", "authorization", "authorized", "can a user", "can an admin", "access control", "restricted", "why can't", "why cannot"]):
        classified_intents.append(INTENT_PERMISSION_AUTH)

    # DATABASE & STORAGE
    if any(p in q_lower for p in ["database", "table", "tables", "schema", "where is", "stored", "data stored", "columns", "foreign key", "orm", "sql"]):
        classified_intents.append(INTENT_DATABASE)
        classified_intents.append(INTENT_DATA_ENTITY)

    # API & ENDPOINTS
    if any(p in q_lower for p in ["api", "apis", "endpoint", "endpoints", "http call", "rest", "route", "routes", "request payload"]):
        classified_intents.append(INTENT_API)

    # INTEGRATION & EXTERNAL SERVICES
    if any(p in q_lower for p in ["integrate", "integration", "integrations", "external service", "third party", "third-party", "webhook", "stripe", "sendgrid", "smtp"]):
        classified_intents.append(INTENT_INTEGRATION)

    # ERROR HANDLING & RESILIENCE
    if any(p in q_lower for p in ["fail", "fails", "failed", "failure", "error", "exception", "retry", "retry mechanism", "unavailable", "what happens when a request is rejected", "rejected"]):
        classified_intents.append(INTENT_ERROR_HANDLING)

    # VALIDATION & BUSINESS RULES
    if any(p in q_lower for p in ["validation", "validations", "validate", "business rule", "business rules", "rule prevents", "prevents", "blocking", "blocked", "constraints", "required fields"]):
        classified_intents.append(INTENT_VALIDATION)
        classified_intents.append(INTENT_WHY_BUSINESS_RULE)

    # LIFECYCLE & STATE TRANSITIONS
    if any(p in q_lower for p in ["lifecycle", "creation to completion", "status transition", "state machine", "from creation"]):
        classified_intents.append(INTENT_LIFECYCLE_STATUS)

    # NOTIFICATIONS & EVENTS
    if any(p in q_lower for p in ["notification", "notifications", "notify", "email", "emails", "alert", "alerts", "sms"]):
        classified_intents.append(INTENT_NOTIFICATION)

    # DEPENDENCIES & PACKAGES
    if any(p in q_lower for p in ["dependency", "dependencies", "libraries", "package", "manifest", "requirements.txt"]):
        classified_intents.append(INTENT_DEPENDENCY)

    # ARCHITECTURE & TOPOLOGY
    if any(p in q_lower for p in ["architecture", "topology", "subsystem", "microservice", "monolith", "services"]):
        classified_intents.append(INTENT_ARCHITECTURE)

    # MODULE UNDERSTANDING
    if any(p in q_lower for p in ["which modules", "what modules", "modules are involved", "module understanding", "package structure"]):
        classified_intents.append(INTENT_MODULE)

    # ENHANCEMENT & IMPACT
    if any(p in q_lower for p in [
        "enhancement", "can we allow", "can we change", "impact of", "what if we",
        "what would happen if", "add support for", "how to add", "allow editing",
    ]) or q_lower.startswith("add ") or " add " in q_lower or q_lower.startswith("allow "):
        classified_intents.append(INTENT_ENHANCEMENT_IMPACT)

    # WORKFLOW / HOW IT WORKS
    if any(p in q_lower for p in [
        "trace flow", "trace", "execution flow", "workflow", "steps involved", "step by step",
        "how does", "how is", "how do", "how to", "what happens after", "move from", "onboarding work"
    ]):
        classified_intents.append(INTENT_WORKFLOW)
        classified_intents.append(INTENT_HOW_IT_WORKS)

    if not classified_intents:
        classified_intents.append(INTENT_GENERAL_FUNCTIONAL)
        classified_intents.append(INTENT_UNKNOWN_GENERAL)

    primary_intent = classified_intents[0]

    # Map to backward-compatible string intent
    if INTENT_PURPOSE in classified_intents:
        legacy_intent = "purpose"
    elif INTENT_ENHANCEMENT_IMPACT in classified_intents:
        legacy_intent = "enhancement/impact"
    elif any(p in q_lower for p in ["customer cannot", "user cannot", "client reports", "user reports", "troubleshoot", "fails with", "bug:"]):
        legacy_intent = "client support"
    elif INTENT_MODULE in classified_intents:
        legacy_intent = "module understanding"
    elif any(p in q_lower for p in ["trace flow", "trace the", "step by step"]):
        legacy_intent = "workflow"
    elif INTENT_WHY_BUSINESS_RULE in classified_intents or any(p in q_lower for p in ["why", "which business rule", "which rule", "rule prevents"]):
        legacy_intent = "why/business rule"
    else:
        legacy_intent = "how"

    # 2. Extract Actions
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9]*", q_normalized)
    actions: list[str] = []
    from app.domain_vocabulary import normalize_morphology, COMMON_ACTION_VERBS
    for w in words:
        if w in ACTION_MAPPINGS:
            act = ACTION_MAPPINGS[w]
            if act not in actions:
                actions.append(act)
        else:
            w_norm = normalize_morphology(w)
            if w_norm in ACTION_MAPPINGS:
                act = ACTION_MAPPINGS[w_norm]
                if act not in actions:
                    actions.append(act)
            elif w_norm in COMMON_ACTION_VERBS:
                if w_norm not in actions:
                    actions.append(w_norm)

    if "check stock" in q_normalized or "checking stock" in q_normalized:
        if "check" not in actions:
            actions.append("check")

    # 3. Extract Roles
    roles: list[str] = []
    for w in words:
        if w in KNOWN_ROLES:
            sing_role = _singularize_word(w)
            if sing_role not in roles:
                roles.append(sing_role)

    # 4. Extract Dynamic Domain Concepts
    entities: list[str] = []
    if legacy_intent != "purpose":
        entities = _extract_domain_concepts_dynamic(words, words, roles)

    # 5. Extract Business Terms
    business_terms: list[str] = []
    for w in words:
        if w in B_TERM_VOCAB and w not in business_terms:
            business_terms.append(w)

    # 6. Extract Modules (Candidate module names — dynamically from entities)
    # Single-token entities are treated as candidate module names since repository
    # modules typically map to single domain nouns (e.g. 'orders', 'patients', 'auth').
    # Multi-word entities are excluded as module candidates.
    modules: list[str] = [e for e in entities if " " not in e and len(e) > 2]

    # 7. Internal Query Plan
    target_layers = []
    if INTENT_PURPOSE in classified_intents:
        target_layers.extend(["overview", "entry"])
    if INTENT_WORKFLOW in classified_intents or INTENT_HOW_IT_WORKS in classified_intents:
        target_layers.extend(["frontend", "validation", "backend", "database", "notification"])
    if INTENT_DATABASE in classified_intents or INTENT_DATA_ENTITY in classified_intents:
        target_layers.extend(["database", "schema", "models"])
    if INTENT_API in classified_intents:
        target_layers.extend(["endpoints", "controllers", "routes"])
    if INTENT_PERMISSION_AUTH in classified_intents or INTENT_USER_ROLE in classified_intents:
        target_layers.extend(["security", "route_guards", "permissions"])
    if INTENT_INTEGRATION in classified_intents:
        target_layers.extend(["integrations", "clients", "external_apis"])
    if INTENT_ERROR_HANDLING in classified_intents:
        target_layers.extend(["exceptions", "error_handlers", "retry_logic"])
    if INTENT_VALIDATION in classified_intents or INTENT_WHY_BUSINESS_RULE in classified_intents:
        target_layers.extend(["validators", "guards", "constraints"])
    if INTENT_ENHANCEMENT_IMPACT in classified_intents:
        target_layers.extend(["target_component", "relations", "downstream", "data_model"])

    required_evidence_kinds = []
    if INTENT_DATABASE in classified_intents:
        required_evidence_kinds.extend(["model", "sql", "migration"])
    if INTENT_API in classified_intents:
        required_evidence_kinds.extend(["endpoint", "route"])
    if INTENT_VALIDATION in classified_intents or INTENT_WHY_BUSINESS_RULE in classified_intents:
        required_evidence_kinds.extend(["rule", "guard", "validation"])
    if not required_evidence_kinds:
        required_evidence_kinds = ["symbol", "endpoint", "model", "rule", "doc"]

    query_plan = {
        "target_entities": entities,
        "target_actions": actions,
        "target_roles": roles,
        "target_layers": sorted(set(target_layers)),
        "required_evidence_kinds": sorted(set(required_evidence_kinds)),
        "primary_intent": primary_intent,
        "intents": classified_intents,
    }

    return QueryIntent(
        intent=legacy_intent,
        intents=classified_intents,
        primary_intent=primary_intent,
        entities=entities,
        actions=actions,
        roles=roles,
        modules=modules,
        business_terms=business_terms,
        raw_query=query,
        resolved_query=resolved_query,
        query_plan=query_plan,
        is_ambiguous=is_ambiguous,
        clarification_prompt=clarification,
    )
