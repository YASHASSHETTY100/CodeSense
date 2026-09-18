"""Hybrid retrieval: multi-factor scoring (semantic, entities, actions, rules) with sufficiency gating."""
from __future__ import annotations
import json, re
from sqlalchemy.orm import Session
from app.models.models import (
    KnowledgeChunk, Module, ApiEndpoint, DataEntity, CodeSymbol, SourceFile, BusinessRule, Role
)
from app.knowledge_base.embeddings import get_embedder, cosine
from app.config import settings
from app.analysis.security import redact_secrets, is_test_file, is_util_file, is_vendor_asset_file
from app.analysis.query_intent import analyze_query, QueryIntent
from app.domain_vocabulary import get_domain_vocabulary, RepositoryDomainVocabulary, ACTION_SYNONYMS, normalize_morphology
from app.knowledge_graph import get_knowledge_graph, RepositoryKnowledgeGraph
from app.query_planner import create_query_plan, QueryPlan

# Configurable Retrieval Weights & Thresholds
WEIGHT_SEMANTIC = 10.0
WEIGHT_ENTITY_MATCH = 4.0
WEIGHT_ACTION_MATCH = 3.0
WEIGHT_MODULE_MATCH = 2.5
WEIGHT_RULE_MATCH = 5.0
WEIGHT_WORKFLOW_MATCH = 3.0
WEIGHT_SUMMARY_CHUNK = 2.0
WEIGHT_IMPLEMENTATION_BOOST = 3.0
WEIGHT_DB_LOGIC_BOOST = 2.0
PENALTY_VENDOR_FILE = 25.0
PENALTY_TEST_FILE = 4.0
PENALTY_UTIL_FILE = 1.5
PENALTY_DOC_FOR_WORKFLOW = 4.0

MIN_EVIDENCE_SCORE_THRESHOLD = 3.5

_WORD = re.compile(r"[a-zA-Z][a-zA-Z0-9_.-]{2,}")

GENERIC_STOP_WORDS = {
    "used", "use", "uses", "using", "get", "gets", "getting", "got", "happen", "happens",
    "happened", "happening", "work", "works", "worked", "working", "does", "do", "did",
    "done", "is", "are", "was", "were", "be", "been", "being", "how", "what", "why",
    "when", "where", "which", "who", "whom", "whose", "can", "could", "should", "would",
    "have", "has", "had", "the", "a", "an", "this", "that", "these", "those", "for",
    "with", "from", "into", "onto", "about", "after", "before", "app", "application",
    "system", "project", "codebase", "repo", "repository", "currently", "step", "steps",
    "thing", "things", "way", "ways", "flow", "flows", "frontend", "backend", "database", "db",
    "api", "apis", "endpoint", "endpoints", "logic", "code", "function", "functions",
    "method", "methods", "module", "modules", "file", "files", "business", "rule", "rules",
    "prevent", "prevents", "preventing", "block", "blocking", "workflow", "workflows",
    "permission", "permissions", "impact", "impacts", "impacted", "change", "changes",
    "support", "area", "areas", "instead", "rather", "without", "within",
    "involve", "involves", "involved", "involving", "include", "includes", "included", "including",
    "require", "requires", "required", "requiring", "relate", "relates", "related", "relating",
    "data", "info", "information", "store", "stores", "stored", "storing", "keep", "keeps", "kept", "keeping",
    "save", "saves", "saved", "saving",
}

SUBMIT_ACTION_VOCAB = {
    "submit", "submission", "submitted", "submitting", "create", "creation",
    "created", "save", "saving", "saved", "store", "storing", "stored",
    "insert", "inserting", "inserted", "post", "posting", "file", "filing",
    "record", "recording", "intake", "intaking", "form",
}


def singularize_token(word: str) -> str:
    """Safely singularize token without damaging short words or invariant endings."""
    w = word.lower().strip()
    if len(w) <= 3 or w.endswith("ss") or w.endswith("us") or w.endswith("is"):
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("ses") and len(w) > 4:
        return w[:-2]
    if w.endswith("xes") and len(w) > 4:
        return w[:-2]
    if w.endswith("ches") and len(w) > 5:
        return w[:-2]
    if w.endswith("shes") and len(w) > 5:
        return w[:-2]
    if w.endswith("s"):
        return w[:-1]
    return w


def normalize_concept(text: str) -> str:
    """Requirement 1:
    - lowercase
    - hyphen/underscore -> space
    - collapse whitespace
    - safe singularization
    - preserve multi-word phrases
    """
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[_\-]+", " ", text)
    tokens = [singularize_token(tok) for tok in text.split()]
    return " ".join(tokens).strip()


def decompose_identifier(ident: str) -> list[str]:
    """Requirement 2c:
    Decompose symbol or identifier (camelCase, snake_case, kebab-case, path) into tokens.
    e.g. report_missing_person_form -> ['report', 'missing', 'person', 'form']
         MissingPersonReport -> ['missing', 'person', 'report']
    """
    if not ident:
        return []
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", ident)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    parts = re.split(r"[^a-zA-Z0-9]+", s)
    return [singularize_token(p) for p in parts if len(p) > 1]


def is_doc_file(path_or_ref: str) -> bool:
    ref = (path_or_ref or "").lower()
    return (
        "readme" in ref or "todo" in ref or "test_plan" in ref or
        "changelog" in ref or "license" in ref or "contributing" in ref or
        ref.startswith("docs/") or "\\docs\\" in ref
    )


def keywords(q: str) -> list[str]:
    stop = {"the", "and", "for", "with", "does", "how", "what", "why", "which", "this",
            "that", "from", "into", "work", "works", "app", "application", "currently"}
    return [w.lower() for w in _WORD.findall(q) if w.lower() not in stop][:20]


def get_project_catalog(db: Session, project_id: int) -> dict:
    """Extract known entities, modules, symbols, endpoints, and files for project."""
    entities = {e.name.lower() for e in db.query(DataEntity.name).filter(DataEntity.project_id == project_id).all()}
    modules = {m.name.lower() for m in db.query(Module.name).filter(Module.project_id == project_id).all()}
    symbols = {s.name.lower() for s in db.query(CodeSymbol.name).filter(CodeSymbol.project_id == project_id).all()}
    endpoints = {f"{e.method.lower()} {e.path.lower()}" for e in db.query(ApiEndpoint).filter(ApiEndpoint.project_id == project_id).all()}
    endpoint_paths = {e.path.lower() for e in db.query(ApiEndpoint).filter(ApiEndpoint.project_id == project_id).all()}
    files = {sf.path.lower() for sf in db.query(SourceFile.path).filter(SourceFile.project_id == project_id).all()}
    rules = [r.description.lower() for r in db.query(BusinessRule.description).filter(BusinessRule.project_id == project_id).all()]
    roles = {r.name.lower() for r in db.query(Role.name).filter(Role.project_id == project_id).all()}

    symbol_token_sets: list[set[str]] = []
    symbol_normalized_phrases: list[str] = []
    all_decomposed_tokens: set[str] = set()

    for sym in symbols:
        toks = decompose_identifier(sym)
        if toks:
            st = set(toks)
            symbol_token_sets.append(st)
            symbol_normalized_phrases.append(" ".join(toks))
            all_decomposed_tokens.update(toks)

    for ent in entities:
        toks = decompose_identifier(ent)
        all_decomposed_tokens.update(toks)

    for ep in endpoint_paths:
        toks = decompose_identifier(ep)
        all_decomposed_tokens.update(toks)

    for f in files:
        toks = decompose_identifier(f)
        all_decomposed_tokens.update(toks)

    for r in roles:
        toks = decompose_identifier(r)
        all_decomposed_tokens.update(toks)

    # CRITICAL: Include symbols and roles in all_catalog_text
    all_catalog_text = " ".join(
        list(entities) + list(modules) + list(symbols) + list(roles) +
        list(endpoint_paths) + list(files) + rules + symbol_normalized_phrases
    )

    vocab = None
    try:
        vocab = get_domain_vocabulary(db, project_id)
        for canon, c in vocab.concepts.items():
            all_decomposed_tokens.add(canon)
            all_decomposed_tokens.update(c.aliases)
            all_decomposed_tokens.update(c.fields)
            all_catalog_text += f" {canon} {' '.join(c.aliases)} {' '.join(c.fields)} {' '.join(c.ui_labels)}"
    except Exception:
        pass

    graph = None
    try:
        graph = get_knowledge_graph(db, project_id)
        for nid, node in graph.nodes.items():
            all_decomposed_tokens.add(node.name.lower())
            all_catalog_text += f" {node.name.lower()}"
    except Exception:
        pass

    all_catalog_compact = re.sub(r"[\s_/-]+", "", all_catalog_text.lower())

    return {
        "entities": entities,
        "modules": modules,
        "symbols": symbols,
        "endpoints": endpoints,
        "endpoint_paths": endpoint_paths,
        "files": files,
        "rules": rules,
        "roles": roles,
        "symbol_token_sets": symbol_token_sets,
        "symbol_normalized_phrases": symbol_normalized_phrases,
        "all_decomposed_tokens": all_decomposed_tokens,
        "all_catalog_text": all_catalog_text,
        "all_catalog_compact": all_catalog_compact,
        "vocab": vocab,
        "graph": graph,
    }


def is_concept_evidenced(
    concept: str,
    catalog: dict,
    candidates: list[dict],
    query_actions: list[str] | None = None,
) -> bool:
    """Targeted concept-to-evidence matching layer.

    Evaluates whether a domain concept is grounded in repository evidence:
    1. Exact normalized phrase match in catalog or candidates
    2. Token overlap and symbol decomposition (e.g. report_missing_person_form -> 'report', 'missing', 'person', 'form')
    3. Related action vocabulary & direct implementation relationships (e.g. report submission -> report_missing_person_form + DB insert + notification)
    4. Co-occurrence in single candidate chunks
    5. Strict negative-query protection: if non-generic concept tokens (e.g. 'purchase' or 'invoice') have 0 repo presence, return False.
    """
    if not concept:
        return True

    norm_concept = normalize_concept(concept)
    if not norm_concept:
        return True

    vocab = catalog.get("vocab")
    if vocab:
        resolved = vocab.resolve_term(concept)
        if resolved is not None:
            return True

    concept_tokens = [
        singularize_token(t) for t in norm_concept.split()
        if t not in GENERIC_STOP_WORDS
    ]
    if not concept_tokens:
        return True

    all_decomposed = catalog.get("all_decomposed_tokens", set())
    candidate_texts = [c.get("text", "").lower() for c in candidates[:12]]
    candidate_refs = [c.get("source_ref", "").lower() for c in candidates[:12]]
    all_cand_text = " ".join(candidate_texts + candidate_refs)

    def clean_text_for_concept_search(text: str, tok: str) -> str:
        if tok == "order":
            text = re.sub(r"\border\s+by\b", " ", text, flags=re.IGNORECASE)
            text = re.sub(r"\bin\s+order\s+to\b", " ", text, flags=re.IGNORECASE)
        elif tok == "group":
            text = re.sub(r"\bgroup\s+by\b", " ", text, flags=re.IGNORECASE)
        return text

    def token_in_repo(tok: str) -> bool:
        if tok in all_decomposed:
            return True
        morph_tok = normalize_morphology(tok)
        if morph_tok in all_decomposed:
            return True
        cat_text = catalog.get("all_catalog_text", "")
        clean_cat = clean_text_for_concept_search(cat_text, tok)
        if bool(re.search(r"\b" + re.escape(tok) + r"\b", clean_cat)):
            return True
        clean_cand = clean_text_for_concept_search(all_cand_text, tok)
        if bool(re.search(r"\b" + re.escape(tok) + r"\b", clean_cand)):
            return True
        if morph_tok != tok:
            clean_cat_m = clean_text_for_concept_search(cat_text, morph_tok)
            if bool(re.search(r"\b" + re.escape(morph_tok) + r"\b", clean_cat_m)):
                return True
            clean_cand_m = clean_text_for_concept_search(all_cand_text, morph_tok)
            if bool(re.search(r"\b" + re.escape(morph_tok) + r"\b", clean_cand_m)):
                return True
        return False

    # 1. Strict negative check:
    # If ANY non-generic token is completely absent from the entire repository, check if vocabulary resolves it.
    for tok in concept_tokens:
        if not token_in_repo(tok):
            if not vocab or not vocab.resolve_term(tok):
                return False

    # 2. Exact normalized phrase match in catalog or candidates
    all_cat_text = catalog.get("all_catalog_text", "")
    if norm_concept in all_cat_text:
        return True

    norm_compact = re.sub(r"[\s_/-]+", "", norm_concept)
    if len(norm_compact) >= 5 and norm_compact in catalog.get("all_catalog_compact", ""):
        return True

    for c_text in candidate_texts:
        clean_c = c_text
        for tok in concept_tokens:
            clean_c = clean_text_for_concept_search(clean_c, tok)
        if norm_concept in clean_c:
            return True
        if len(norm_compact) >= 5 and norm_compact in re.sub(r"[\s_/-]+", "", clean_c):
            return True

    # 3. Symbol decomposition match:
    # Does any symbol contain all tokens of the concept?
    c_token_set = set(concept_tokens)
    c_morph_token_set = {normalize_morphology(t) for t in concept_tokens}
    symbol_token_sets = catalog.get("symbol_token_sets", [])
    for s_tokens in symbol_token_sets:
        s_morph_tokens = {normalize_morphology(st) for st in s_tokens}
        if c_token_set.issubset(s_tokens) or c_morph_token_set.issubset(s_tokens) or c_morph_token_set.issubset(s_morph_tokens):
            return True

    for ent in catalog.get("entities", set()):
        ent_tokens = set(decompose_identifier(ent))
        ent_morph_tokens = {normalize_morphology(et) for et in ent_tokens}
        if c_token_set.issubset(ent_tokens) or c_morph_token_set.issubset(ent_tokens) or c_morph_token_set.issubset(ent_morph_tokens):
            return True

    # 4. Related action vocabulary & direct implementation relationships:
    actions = query_actions or []
    has_submit_intent = any(a in SUBMIT_ACTION_VOCAB for a in actions) or any(w in norm_concept for w in SUBMIT_ACTION_VOCAB)
    if has_submit_intent:
        for s_tokens in symbol_token_sets:
            if any(ct in s_tokens or normalize_morphology(ct) in s_tokens for ct in concept_tokens):
                if any(act_w in s_tokens for act_w in SUBMIT_ACTION_VOCAB):
                    return True

    # 5. Candidate chunk co-occurrence:
    # Check if all tokens of the concept co-occur within a single implementation candidate chunk
    for c_text in candidate_texts:
        clean_c = c_text
        for tok in concept_tokens:
            clean_c = clean_text_for_concept_search(clean_c, tok)
        if all(
            re.search(r"\b" + re.escape(tok) + r"\b", clean_c) or
            re.search(r"\b" + re.escape(normalize_morphology(tok)) + r"\b", clean_c)
            for tok in concept_tokens
        ):
            return True

    # 6. Single-token concept handling (e.g. 'report'):
    if len(concept_tokens) == 1:
        tok = concept_tokens[0]
        mtok = normalize_morphology(tok)
        for s_tokens in symbol_token_sets:
            if tok in s_tokens or mtok in s_tokens:
                return True
        if tok in all_decomposed or mtok in all_decomposed:
            return True
        cat_text = catalog.get("all_catalog_text", "")
        clean_cat = clean_text_for_concept_search(cat_text, tok)
        if bool(re.search(r"\b" + re.escape(tok) + r"\b", clean_cat)):
            return True
        if mtok != tok:
            clean_cat_m = clean_text_for_concept_search(cat_text, mtok)
            if bool(re.search(r"\b" + re.escape(mtok) + r"\b", clean_cat_m)):
                return True

    return False


def evaluate_sufficiency(
    db: Session,
    project_id: int,
    question: str,
    scored_candidates: list[dict],
    catalog: dict | None = None,
) -> tuple[bool, str, list[str]]:
    if catalog is None:
        catalog = get_project_catalog(db, project_id)

    # If the project has no indexed files/entities/symbols at all
    if not catalog["files"] and not catalog["entities"] and not catalog["symbols"]:
        return False, "empty_project", ["project has no indexed files"]

    qi = analyze_query(question)
    q_lower = question.lower()

    # Purpose and overview queries are inherently supported if repo has code/docs
    if qi.intent == "purpose" or getattr(qi, "primary_intent", "") == "PURPOSE" or any(term in q_lower for term in [
        "project purpose", "summarize", "overview", "modules workflows",
        "application used for", "app used for", "application do", "app do", "app does",
        "problem does this", "purpose of this", "what does this project do",
        "what does this application do", "what is this application", "what this app",
        "what this whole app", "app actually does", "objective of this", "objective of the",
        "operational objective", "primary objective"
    ]):
        if scored_candidates and scored_candidates[0]["score"] > 0:
            return True, "purpose_supported", []

    # Negative query protection:
    # 1. Evaluate all extracted domain entities using the targeted concept-to-evidence layer
    missing = []
    evidenced_ents = []
    for ent in qi.entities:
        if is_concept_evidenced(ent, catalog, scored_candidates, qi.actions):
            evidenced_ents.append(ent)
        else:
            missing.append(ent)

    if missing:
        # Check if missing items are actor/role terms, modifiers, or sub-tokens of an evidenced compound entity
        MODIFIER_TERMS = {
            "delivery", "shipping", "billing", "mailing", "home", "work", "primary",
            "secondary", "default", "current", "new", "old", "first", "last", "client",
            "customer", "user", "location", "locations", "system", "end", "persistent",
            "storage", "component", "components", "interconnected", "exposed", "lifecycle",
            "ensure", "prior", "detail", "details", "path", "flow", "stage", "step", "steps",
            "operation", "operations", "process", "processing", "destination", "destination details",
            "mathematical", "algorithmic", "computational", "operational", "technical",
            "objective", "objectives", "goal", "goals", "demographic", "deep", "learning",
            "model", "models", "dispatcher", "dispatchers", "coordinator", "coordinators",
            "coordinate", "coordinated", "coordinating", "coordination",
            "condition", "conditions", "corrupted", "invalid", "empty", "date", "index", "indices",
            "identification", "registered", "record", "records", "administrative", "authenticated",
            "manage", "search", "trigger", "triggered", "photo", "uploaded", "upload", "saving",
            "access", "permission", "permissions", "auth", "authorize", "authorization",
            "contain", "contains", "detect", "detectable", "detection"
        }
        def _is_tok_evidenced_or_modifier(tok: str) -> bool:
            t = tok.lower().strip()
            if not t or len(t) <= 1:
                return True
            from app.analysis.query_intent import _singularize_word
            t_sing = _singularize_word(t)
            t_root = t.rstrip("s")
            candidates = {t, t_sing, t_root}
            if t in ("indices", "indice"):
                candidates.add("index")
            for cand in candidates:
                if cand in qi.roles or cand in MODIFIER_TERMS:
                    return True
                if any(cand == ev_ent or cand in ev_ent.split() for ev_ent in evidenced_ents):
                    return True
                if any(cand == s.lower() or cand in s.lower().split("_") for s in catalog["symbols"]):
                    return True
                if any(cand == f.lower() for f in catalog["files"]):
                    return True
            return False

        real_missing = []
        for m in missing:
            m_clean = m.lower().strip()
            # If recognized as role or modifier or actor term (including compound combinations of modifiers and evidenced tokens)
            if m_clean in qi.roles or m_clean in MODIFIER_TERMS or all(_is_tok_evidenced_or_modifier(tok) for tok in m_clean.split()):
                continue
            # If m is a token inside one of the evidenced entities (e.g. 'delivery' in 'delivery address')
            if any(m_clean in ev_ent.split() for ev_ent in evidenced_ents):
                continue
            # Check if domain vocabulary resolves it
            vocab = catalog.get("vocab")
            if vocab and vocab.resolve_term(m_clean):
                continue
            real_missing.append(m)

        if real_missing:
            return False, "unsupported_domain_concept", real_missing

        if not evidenced_ents and not any(i in qi.intents for i in ["PERMISSION_AUTH", "USER_ROLE", "SECURITY", "PURPOSE"]):
            return False, "unsupported_domain_concept", missing

        # If only generic roles were matched but the actual domain subject is unevidenced
        is_meta_query = any(i in qi.intents for i in ["PERMISSION_AUTH", "USER_ROLE", "SECURITY", "PURPOSE", "ARCHITECTURE", "DATABASE", "DATA_ENTITY", "API", "WORKFLOW", "HOW_IT_WORKS"]) or qi.intent in ("purpose", "role", "who", "database", "api", "workflow")
        core_evidenced = [e for e in evidenced_ents if e not in qi.roles]
        if not core_evidenced and not is_meta_query:
            return False, "unsupported_domain_concept", real_missing or missing

        # If real_missing has a multi-word foreign concept completely unevidenced in the catalog
        foreign_missing = [
            m for m in real_missing
            if len(m.split()) >= 2 and not any(tok in s for s in catalog["symbols"] for tok in m.split() if len(tok) > 3)
        ]
        if foreign_missing:
            return False, "unsupported_domain_concept", foreign_missing

    # 2. Specific domain actions (e.g. "how does inventory get updated?" when inventory is read-only)
    if "update" in qi.actions or "modify" in qi.actions:
        target_ents = [e for e in qi.entities if is_concept_evidenced(e, catalog, scored_candidates, qi.actions)]
        target_name = target_ents[0] if target_ents else (qi.entities[0] if qi.entities else "")
        if not target_name:
            return False, "unsupported_domain_concept", ["action target"]
        target_cands = [c for c in scored_candidates if target_name in c["source_ref"].lower() or target_name in c["text"].lower()]
        update_evidenced = any(
            any(act_word in c["text"].lower() for act_word in ["update", "modify", "save", "write", "set", "increment", "decrement", "put", "patch", "change", "post", "create"])
            for c in target_cands
        )
        if not update_evidenced:
            has_write_sym = any(
                target_name in s and any(w in s for w in ["update", "modify", "edit", "save", "set", "change", "create"])
                for s in catalog["symbols"]
            )
            # If the user is asking "Can a user modify X after Y?" (adversarial/feasibility inquiry),
            # do NOT reject at sufficiency gate; let the reasoning engine explain what is/isn't permitted!
            is_feasibility_question = any(term in q_lower for term in ["can a", "can the", "is it possible", "can we", "can customer"])
            if not has_write_sym and not is_feasibility_question:
                return False, "unsupported_domain_action", [f"{target_name} update"]

    if not scored_candidates:
        return False, "no_matching_evidence", missing or ["no evidence chunks matched query"]

    # 3. Minimum score threshold check
    top_score = scored_candidates[0]["score"] if scored_candidates else 0.0
    if top_score < MIN_EVIDENCE_SCORE_THRESHOLD:
        return False, "insufficient_score_threshold", ["evidence score below minimum threshold"]

    # 4. Check if top chunk is only a test file while asking general domain question
    if is_test_file(scored_candidates[0]["source_ref"]) and not any(t in q_lower for t in ["test", "spec", "fixture"]):
        non_test = [c for c in scored_candidates if not is_test_file(c["source_ref"])]
        if not non_test or non_test[0]["score"] < MIN_EVIDENCE_SCORE_THRESHOLD:
            return False, "insufficient_non_test_evidence", ["only test files matched without domain implementation"]

    return True, "sufficient_evidence", []


def retrieve(db: Session, project_id: int, question: str, top_k: int = 12, allow_insufficient: bool = False) -> list[dict]:
    kws = keywords(question)
    qi = analyze_query(question)
    catalog = get_project_catalog(db, project_id)
    chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.project_id == project_id).all()

    if not chunks:
        return []

    q_lower = question.lower()
    is_test_query = any(t in q_lower for t in ["test", "spec", "fixture", "mock"])
    is_util_query = any(u in q_lower for u in ["util", "helper", "common", "config"])

    vocab = catalog.get("vocab") or get_domain_vocabulary(db, project_id)
    graph = catalog.get("graph") or get_knowledge_graph(db, project_id)

    matched_concepts = vocab.find_matching_concepts(question) if vocab else []
    concept_synonyms: set[str] = set()
    traced_files: set[str] = set()
    traced_symbols: set[str] = set()

    for mc in matched_concepts:
        concept_synonyms.update(vocab.get_synonyms_and_aliases(mc.canonical_name))
        if graph:
            layer_dict = graph.trace_cross_layer(mc.canonical_name)
            for lnodes in layer_dict.values():
                for nd in lnodes:
                    if nd.file_path:
                        traced_files.add(nd.file_path.lower())
                    if nd.name:
                        traced_symbols.add(nd.name.lower())

    rich_intents = getattr(qi, "intents", [])

    def compute_chunk_scores(c: KnowledgeChunk) -> tuple[float, dict]:
        t = (c.chunk_text or "").lower()
        ref = (c.source_ref or "").lower()

        lex_score = 0.0
        concept_score = 0.0
        sym_score = 0.0
        graph_score = 0.0
        wf_score = 0.0
        layer_score = 0.0
        impl_score = 0.0

        # 1. Lexical matches
        for k in kws:
            if k in ref:
                lex_score += 3.0
            elif k in t:
                lex_score += 1.5

        # 2. Concept matches (canonical and verified aliases)
        for syn in concept_synonyms:
            syn_norm = normalize_concept(syn)
            if syn_norm:
                if syn_norm in ref:
                    concept_score += 8.0
                elif syn_norm in t:
                    concept_score += 4.0

        for ent in qi.entities:
            ent_norm = normalize_concept(ent)
            ent_tokens = ent_norm.split()
            if ent_norm in ref or (ent_tokens and all(tok in ref for tok in ent_tokens)):
                concept_score += WEIGHT_ENTITY_MATCH
            elif ent_norm in t or (ent_tokens and all(tok in t for tok in ent_tokens)):
                concept_score += (WEIGHT_ENTITY_MATCH * 0.75)

        # 3. Symbol matches: symbol is mentioned in query or matches query terms/entities
        query_terms = set(kws) | {normalize_concept(e) for e in qi.entities if normalize_concept(e)}
        for s_tok in catalog.get("symbols", set()):
            s_l = s_tok.lower()
            if s_l in q_lower or any(qt in s_l for qt in query_terms if len(qt) > 2):
                if s_l in ref:
                    sym_score += 6.0
                elif s_l in t:
                    sym_score += 3.0

        # 4. Knowledge Graph expansion / trace
        for ts in traced_symbols:
            if ts in ref:
                graph_score += 6.0
            elif ts in t:
                graph_score += 2.0
        if graph_score == 0:
            for tf in traced_files:
                if tf in ref:
                    graph_score += 3.0
                    break

        # 5. Workflow / Actions
        for act in qi.actions:
            act_l = act.lower()
            if act_l in ref:
                wf_score += WEIGHT_ACTION_MATCH
            elif act_l in t:
                wf_score += (WEIGHT_ACTION_MATCH * 0.5)
            elif act_l in SUBMIT_ACTION_VOCAB:
                if any(w in ref for w in ["submit", "form", "create", "insert"]):
                    wf_score += WEIGHT_ACTION_MATCH
                elif any(w in t for w in ["submit", "form", "create", "insert"]):
                    wf_score += (WEIGHT_ACTION_MATCH * 0.5)

        for mod in qi.modules:
            mod_l = mod.lower()
            if mod_l in ref:
                wf_score += WEIGHT_MODULE_MATCH

        # 6. Query-Specific Layer Prioritization
        is_persistence_query = (
            any(i in rich_intents for i in ["DATABASE", "DATA_ENTITY"])
            or "where is" in q_lower
            or "stored" in q_lower
            or "database" in q_lower
            or "table" in q_lower
        )
        is_input_entry_query = (
            any(act in qi.actions for act in ["provide", "enter", "input", "fill", "submit"])
            or "form" in q_lower
            or "ui" in q_lower
            or "template" in q_lower
        )
        is_auth_role_query = (
            any(i in rich_intents for i in ["PERMISSION_AUTH", "USER_ROLE"])
            or "who is allowed" in q_lower
            or "who can" in q_lower
            or "permission" in q_lower
            or "role" in q_lower
        )
        is_post_state_query = (
            any(i in rich_intents for i in ["NOTIFICATION", "LIFECYCLE_STATUS"])
            or "after" in q_lower
            or "succeeds" in q_lower
            or "placed" in q_lower
            or "callback" in q_lower
        )
        is_error_query = (
            "ERROR_HANDLING" in rich_intents
            or "fails" in q_lower
            or "failure" in q_lower
            or "error" in q_lower
        )

        if is_persistence_query:
            if any(db_pat in ref or db_pat in t for db_pat in ["models.py", "schema", "models", "create table", "migration", "foreignkey", "sql"]):
                layer_score += 14.0
            if any(ui_pat in ref for ui_pat in [".html", "template", ".css", ".js", "datatables", "snippet"]):
                layer_score -= 8.0

        if is_input_entry_query:
            if any(ui_pat in ref or ui_pat in t for ui_pat in ["form", "template", ".html", "field:", "input", "button"]):
                layer_score += 14.0
            if any(v_pat in ref or v_pat in t for v_pat in ["views.py", "view", "route", "checkoutview", "controller"]):
                layer_score += 8.0
            if "migration" in ref or ".js" in ref:
                layer_score -= 4.0

        if is_auth_role_query:
            if any(auth_pat in ref or auth_pat in t for auth_pat in ["permission", "role", "auth", "is_admin", "login_required", "guard", "is_authenticated"]):
                layer_score += 16.0
            if "template" in ref and not ("login" in ref or "auth" in ref or "profile" in ref):
                layer_score -= 6.0

        if is_post_state_query:
            if any(post_pat in ref or post_pat in t for post_pat in ["post_save", "signal", "status", "ordered = true", "notification", "notify", "email", "callback", "complete"]):
                layer_score += 14.0

        if is_error_query:
            if any(err_pat in t for err_pat in ["except ", "raise ", "try:", "error", "fail", "messages.warning", "messages.error"]):
                layer_score += 14.0

        # General intent boosts
        if qi.intent == "why/business rule":
            if ref.startswith("rule:") or "rule" in ref or "validation" in t or "raise" in t:
                wf_score += WEIGHT_RULE_MATCH
        elif qi.intent == "workflow":
            if ref.startswith("endpoint:") or "router" in t or "route" in t or "form" in ref:
                wf_score += WEIGHT_WORKFLOW_MATCH
        elif qi.intent == "purpose":
            if "readme" in ref or "overview" in ref or "purpose" in ref or "readme" in t:
                layer_score += 16.0

        # 7. Implementation vs Documentation weighting
        impl_type = "raw_code"
        if is_vendor_asset_file(ref):
            impl_type = "vendor"
            impl_score -= PENALTY_VENDOR_FILE
        elif is_test_file(ref):
            impl_type = "test"
            if not is_test_query:
                impl_score -= PENALTY_TEST_FILE
        elif is_util_file(ref):
            impl_type = "util"
            if not is_util_query:
                impl_score -= PENALTY_UTIL_FILE
        elif is_doc_file(ref):
            impl_type = "doc"
            if qi.intent != "purpose":
                impl_score -= PENALTY_DOC_FOR_WORKFLOW
            else:
                impl_score += 12.0
        else:
            if c.chunk_type == "raw_code" or any(ref.endswith(ext) for ext in [".py", ".ts", ".js", ".go", ".java", ".sql"]) or ":" in ref:
                impl_score += WEIGHT_IMPLEMENTATION_BOOST
            if any(db_kw in t for db_kw in ["insert into", "c.execute", "db.session", "lastrowid", "conn.commit", "create table", "select ", "update "]):
                impl_score += WEIGHT_DB_LOGIC_BOOST

        total_struct = lex_score + concept_score + sym_score + graph_score + wf_score + layer_score + impl_score
        breakdown = {
            "lexical": round(lex_score, 3),
            "concept": round(concept_score, 3),
            "symbol": round(sym_score, 3),
            "graph_distance": round(graph_score, 3),
            "workflow": round(wf_score, 3),
            "layer": round(layer_score, 3),
            "impl_type": impl_type,
            "structured_total": round(total_struct, 3),
        }
        return max(0.0, total_struct), breakdown

    # Calculate structured scores with breakdown
    scored_struct = []
    for c in chunks:
        score_val, breakdown = compute_chunk_scores(c)
        scored_struct.append((score_val, c, breakdown))

    scored_struct.sort(key=lambda x: x[0], reverse=True)

    # Vector search over candidate pool
    emb = get_embedder(settings.EMBEDDING_BACKEND)
    qv = emb.embed(question)
    pool = [c for _, c, _ in scored_struct[:400]] or chunks[:400]
    vec: list[tuple[float, KnowledgeChunk, float, float, dict]] = []

    # Map chunks to their breakdown
    chunk_breakdowns = {c.id: b for _, c, b in scored_struct}

    for c in pool:
        try:
            v = json.loads(c.embedding_vector or "[]")
        except Exception:
            v = []
        if not v:
            continue
        breakdown = chunk_breakdowns.get(c.id, {})
        s_struct = breakdown.get("structured_total", 0.0)
        sem_score = max(0.0, cosine(qv, v)) * WEIGHT_SEMANTIC
        composite = 0.7 * s_struct + sem_score
        vec.append((composite, c, s_struct, sem_score, breakdown))

    vec.sort(key=lambda x: x[0], reverse=True)

    candidates = []
    for comp_score, c, s_struct, sem_score, breakdown in vec:
        c_scores = dict(breakdown)
        c_scores["semantic"] = round(sem_score, 3)
        c_scores["final_score"] = round(comp_score, 3)

        candidates.append({
            "source_ref": c.source_ref,
            "text": redact_secrets(c.chunk_text[:2500]),
            "chunk_type": c.chunk_type,
            "score": round(comp_score, 3),
            "scores": c_scores,
        })

    # Evaluate evidence sufficiency gate
    is_suff, reason, missing = evaluate_sufficiency(db, project_id, question, candidates, catalog)

    if not is_suff and not allow_insufficient:
        # Mandatory gate: Unsupported queries return empty evidence
        return []

    # Precision Filtering:
    # Filter candidates to retain those that are genuinely relevant (above cutoff
    # or with positive concept/layer signals), avoiding polluting evidence with unrelated chunks.
    top_score = candidates[0]["score"] if candidates else 0.0
    cutoff = max(MIN_EVIDENCE_SCORE_THRESHOLD, top_score * 0.35 if top_score > 0 else 0)

    filtered = [
        c for c in candidates
        if c["score"] >= cutoff or c.get("scores", {}).get("concept", 0) > 0 or c.get("scores", {}).get("layer", 0) > 0
    ]

    out = filtered[:top_k] if len(filtered) >= 4 else candidates[:min(len(candidates), top_k)]

    # Guarantee top structured hit is represented if valid
    if scored_struct and scored_struct[0][0] >= MIN_EVIDENCE_SCORE_THRESHOLD:
        top_struct = scored_struct[0][1]
        if all(r["source_ref"] != top_struct.source_ref for r in out):
            top_b = scored_struct[0][2]
            top_b["final_score"] = 999.0
            out = [{
                "source_ref": top_struct.source_ref,
                "text": redact_secrets(top_struct.chunk_text[:2500]),
                "chunk_type": top_struct.chunk_type,
                "score": 999.0,
                "scores": top_b,
            }] + out[:top_k - 1]

    return out

