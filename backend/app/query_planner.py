"""Structured Query Planner for natural-language functional queries.

Converts an arbitrary natural-language question into an execution plan containing:
- actor / entity
- actions
- objects
- candidate domain concepts
- constraints
- candidate workflows
- required evidence layers
- retrieval strategies
- multi-intent sub-queries
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any
from app.domain_vocabulary import (
    RepositoryDomainVocabulary, DomainConcept, decompose_tokens, singularize,
    normalize_morphology, ACTION_SYNONYMS, COMMON_ACTION_VERBS
)

# Supported Intent Categories
INTENT_PROJECT_PURPOSE = "PROJECT_PURPOSE"
INTENT_ROLE = "ROLE"
INTENT_PERMISSION = "PERMISSION"
INTENT_FEATURE = "FEATURE"
INTENT_WORKFLOW = "WORKFLOW"
INTENT_BUSINESS_RULE = "BUSINESS_RULE"
INTENT_VALIDATION = "VALIDATION"
INTENT_DATA_ENTITY = "DATA_ENTITY"
INTENT_DATA_STORAGE = "DATA_STORAGE"
INTENT_API = "API"
INTENT_INTEGRATION = "INTEGRATION"
INTENT_DEPENDENCY = "DEPENDENCY"
INTENT_ERROR_HANDLING = "ERROR_HANDLING"
INTENT_CONFIGURATION = "CONFIGURATION"
INTENT_SECURITY = "SECURITY"
INTENT_UI_BEHAVIOR = "UI_BEHAVIOR"
INTENT_BACKEND_BEHAVIOR = "BACKEND_BEHAVIOR"
INTENT_DATABASE_BEHAVIOR = "DATABASE_BEHAVIOR"
INTENT_TRACEABILITY = "TRACEABILITY"
INTENT_IMPACT_ANALYSIS = "IMPACT_ANALYSIS"
INTENT_GENERAL_FUNCTIONAL = "GENERAL_FUNCTIONAL"

GENERIC_VERBS = {
    "do", "does", "did", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "can", "could", "would", "should", "will", "shall",
    "may", "might", "must", "happen", "happens", "work", "works", "use", "used",
    "get", "gets", "make", "makes", "take", "takes", "tell", "explain", "describe",
}

ACTOR_TERMS = {
    "customer", "user", "client", "buyer", "shopper", "admin", "administrator",
    "manager", "operator", "staff", "member", "guest", "patient", "doctor",
    "nurse", "author", "creator", "caller", "applicant", "citizen", "trader",
    "investor", "system", "worker", "subscriber", "consumer",
}


@dataclass
class QueryPlan:
    raw_query: str
    actor: str = ""
    actions: list[str] = field(default_factory=list)
    objects: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    candidate_workflows: list[str] = field(default_factory=list)
    required_layers: list[str] = field(default_factory=list)
    retrieval_strategies: list[str] = field(default_factory=list)
    primary_intent: str = INTENT_GENERAL_FUNCTIONAL
    intents: list[str] = field(default_factory=list)
    sub_queries: list[str] = field(default_factory=list)
    is_multi_intent: bool = False
    is_ambiguous: bool = False
    ambiguity_candidates: list[str] = field(default_factory=list)
    clarification_prompt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_query": self.raw_query,
            "actor": self.actor,
            "actions": self.actions,
            "objects": self.objects,
            "concepts": self.concepts,
            "constraints": self.constraints,
            "candidate_workflows": self.candidate_workflows,
            "required_layers": self.required_layers,
            "retrieval_strategies": self.retrieval_strategies,
            "primary_intent": self.primary_intent,
            "intents": self.intents,
            "sub_queries": self.sub_queries,
            "is_multi_intent": self.is_multi_intent,
            "is_ambiguous": self.is_ambiguous,
            "ambiguity_candidates": self.ambiguity_candidates,
            "clarification_prompt": self.clarification_prompt,
        }


def decompose_multi_intent_query(query: str) -> list[str]:
    """Decompose compound questions containing multiple distinct requests.

    Example:
    'How does checkout work, who can perform it, how is payment processed, and what happens to the order afterward?'
    -> ['How does checkout work', 'who can perform it', 'how is payment processed', 'what happens to the order afterward']
    """
    # Look for compound delimiters like ', and', ';', 'and what happens', 'and who can', 'and how'
    parts = re.split(r";|\band\s+(?=(?:who|how|what|where|which|can|is|why)\b)|,\s*(?=(?:who|how|what|where|which|can|is|why)\b)", query, flags=re.IGNORECASE)
    cleaned = [p.strip().rstrip("?,.") for p in parts if len(p.strip().split()) >= 3]
    if len(cleaned) > 1:
        return cleaned
    return [query.strip()]


def create_query_plan(query: str, vocab: RepositoryDomainVocabulary | None = None) -> QueryPlan:
    """Derive structured query plan for an arbitrary natural-language question."""
    q_norm = query.strip()
    q_lower = q_norm.lower()

    # 1. Multi-intent decomposition
    sub_queries = decompose_multi_intent_query(q_norm)
    is_multi = len(sub_queries) > 1

    words = re.findall(r"[a-zA-Z0-9]+", q_lower)

    # 2. Extract Actor
    actor = ""
    for w in words:
        w_sing = singularize(w)
        if w_sing in ACTOR_TERMS:
            actor = w_sing
            break

    # 3. Extract Actions
    actions: list[str] = []
    for w in words:
        w_sing = singularize(w)
        w_norm = normalize_morphology(w)
        for cand in [w_norm, w_sing, w]:
            if cand in ACTION_SYNONYMS or cand in COMMON_ACTION_VERBS or cand in {"provide", "enter", "submit", "save", "edit", "update", "cancel", "approve", "calculate", "process", "pay", "order", "search", "view", "check", "record", "verify"}:
                if cand not in actions and cand not in GENERIC_VERBS:
                    actions.append(cand)
                break

    # Expand action synonyms
    expanded_actions = list(actions)
    for act in actions:
        for syn in ACTION_SYNONYMS.get(act, []):
            if syn not in expanded_actions:
                expanded_actions.append(syn)

    # 4. Extract Object & Domain Concepts (grounded via repository vocabulary if provided)
    concepts: list[str] = []
    objects: list[str] = []

    if vocab:
        matched_concepts = vocab.find_matching_concepts(q_lower)
        for mc in matched_concepts:
            if mc.canonical_name not in concepts:
                concepts.append(mc.canonical_name)
            for a in mc.aliases:
                if a in q_lower and a not in objects:
                    objects.append(a)

    # If vocabulary didn't match objects, extract non-actor, non-verb nouns
    if not objects:
        for idx, w in enumerate(words):
            w_sing = singularize(w)
            if (
                w_sing not in ACTOR_TERMS
                and w_sing not in GENERIC_VERBS
                and w_sing not in actions
                and len(w_sing) > 2
                and w_sing not in {"the", "and", "for", "with", "this", "that", "how", "what", "why", "which", "where", "who", "when", "can"}
            ):
                if w_sing not in objects:
                    objects.append(w_sing)
                if w_sing not in concepts:
                    concepts.append(w_sing)

    # 5. Extract Constraints
    constraints: list[str] = []
    for w in words:
        if w in {"approved", "active", "cancelled", "pending", "rejected", "failed", "completed", "invalid", "default"}:
            if w not in constraints:
                constraints.append(w)

    # 6. Intent Classification
    intents: list[str] = []

    # Purpose / Overview
    if any(p in q_lower for p in ["what is this application", "what does this app", "what problem", "purpose of this", "what is this project"]):
        intents.append(INTENT_PROJECT_PURPOSE)

    # Role & Permission
    if any(p in q_lower for p in ["who can", "who is allowed", "role", "roles", "permission", "permissions", "authorized", "access control"]):
        intents.append(INTENT_PERMISSION)
        intents.append(INTENT_ROLE)

    # Workflow & How it works
    if any(p in q_lower for p in ["how does", "how do", "how is", "how to", "workflow", "process", "steps", "what happens after", "trace flow"]):
        intents.append(INTENT_WORKFLOW)

    # Business Rule & Validation
    if any(p in q_lower for p in ["rule", "rules", "validation", "validate", "validating", "prevent", "prevents", "block", "why can't", "why cannot", "condition"]):
        intents.append(INTENT_BUSINESS_RULE)
        intents.append(INTENT_VALIDATION)

    # Data & Database
    if any(p in q_lower for p in ["database", "table", "tables", "where is", "stored", "data", "columns", "schema", "model"]):
        intents.append(INTENT_DATA_STORAGE)
        intents.append(INTENT_DATA_ENTITY)

    # API & Route
    if any(p in q_lower for p in ["api", "apis", "endpoint", "endpoints", "route", "routes", "http"]):
        intents.append(INTENT_API)

    # Integration
    if any(p in q_lower for p in ["integrate", "integration", "external", "third party", "service", "stripe", "webhook"]):
        intents.append(INTENT_INTEGRATION)

    # Error handling
    if any(p in q_lower for p in ["fail", "fails", "failed", "error", "exception", "retry", "reject"]):
        intents.append(INTENT_ERROR_HANDLING)

    # Impact analysis
    if any(p in q_lower for p in ["enhancement", "can we allow", "can we change", "impact of", "what if", "would happen if"]):
        intents.append(INTENT_IMPACT_ANALYSIS)

    if not intents:
        intents.append(INTENT_GENERAL_FUNCTIONAL)

    primary_intent = intents[0]

    # 7. Derive Required Evidence Layers
    required_layers: list[str] = []
    if any(act in {"provide", "enter", "input", "fill"} for act in actions) or "ui" in q_lower or "form" in q_lower:
        required_layers.extend(["ui", "form", "route", "backend", "persistence"])
    elif INTENT_WORKFLOW in intents:
        required_layers.extend(["form", "route", "controller", "service", "model", "database"])
    elif INTENT_DATA_STORAGE in intents:
        required_layers.extend(["model", "database"])
    elif INTENT_API in intents:
        required_layers.extend(["route", "controller"])
    elif INTENT_BUSINESS_RULE in intents:
        required_layers.extend(["validation", "controller", "model"])
    else:
        required_layers.extend(["backend", "model", "persistence"])

    # 8. Retrieval Strategies
    retrieval_strategies = ["semantic", "symbol", "lexical", "graph_neighborhood"]
    if "ui" in required_layers or "form" in required_layers:
        retrieval_strategies.append("template_form")
        retrieval_strategies.append("cross_layer_trace")
    if INTENT_WORKFLOW in intents or INTENT_TRACEABILITY in intents:
        retrieval_strategies.append("cross_layer_trace")

    # 9. Candidate Workflows
    candidate_workflows = []
    if "checkout" in q_lower or "cart" in q_lower or "order" in q_lower:
        candidate_workflows.append("checkout")
    if "address" in q_lower:
        candidate_workflows.extend(["checkout", "customer_profile", "order_shipping"])
    if "onboarding" in q_lower or "register" in q_lower:
        candidate_workflows.append("registration")

    # 10. Ambiguity detection
    is_ambiguous = False
    ambiguity_candidates = []
    clarification_prompt = ""
    # If the query is a stand-alone pronoun or extremely vague
    if len(words) <= 3 and any(w in words for w in ["it", "they", "that", "this"]):
        is_ambiguous = True
        clarification_prompt = "Could you please specify which feature, entity, or process you are asking about?"

    return QueryPlan(
        raw_query=query,
        actor=actor,
        actions=actions,
        objects=objects,
        concepts=concepts,
        constraints=constraints,
        candidate_workflows=candidate_workflows,
        required_layers=sorted(set(required_layers)),
        retrieval_strategies=sorted(set(retrieval_strategies)),
        primary_intent=primary_intent,
        intents=intents,
        sub_queries=sub_queries,
        is_multi_intent=is_multi,
        is_ambiguous=is_ambiguous,
        ambiguity_candidates=ambiguity_candidates,
        clarification_prompt=clarification_prompt,
    )
