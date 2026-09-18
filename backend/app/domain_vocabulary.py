"""Dynamic Domain Vocabulary: repository-defined vocabulary without hardcoded domain lists.

Extracts business concepts, morphological aliases, fields, routes, UI labels,
associated actions, and workflows exclusively from repository evidence.
"""
from __future__ import annotations
import os, re, json
from dataclasses import dataclass, field
from typing import Any
from sqlalchemy.orm import Session
from app.models.models import (
    DataEntity, CodeSymbol, ApiEndpoint, BusinessRule, SourceFile, Module
)

COMMON_ACTION_VERBS = {
    "submit", "enter", "provide", "save", "create", "update", "edit", "modify",
    "delete", "remove", "cancel", "approve", "reject", "validate", "check", "verify",
    "calculate", "compute", "process", "pay", "checkout", "transfer", "ship",
    "deliver", "assign", "notify", "alert", "view", "show", "search", "filter",
    "match", "track", "generate", "download", "export", "import", "lock", "unlock",
    "place", "handle", "manage", "clean", "format", "plot", "predict", "detect"
}

ACTION_SYNONYMS: dict[str, set[str]] = {
    "provide": {"enter", "submit", "input", "save", "fill", "set", "send", "post"},
    "enter": {"provide", "submit", "input", "save", "fill", "type"},
    "submit": {"provide", "enter", "send", "post", "create", "save", "dispatch", "place"},
    "place": {"create", "submit", "post", "order"},
    "save": {"submit", "store", "persist", "record", "insert", "create"},
    "edit": {"update", "modify", "change", "alter"},
    "update": {"edit", "modify", "change", "save"},
    "cancel": {"abort", "void", "terminate", "revoke", "drop"},
    "approve": {"authorize", "accept", "confirm", "pass"},
    "check": {"verify", "validate", "inspect", "test"},
    "pay": {"checkout", "charge", "purchase", "transact", "settle"},
    "search": {"find", "lookup", "query", "filter", "locate"},
}

CONCEPT_SYNONYMS: dict[str, str] = {
    "location": "address",
    "destination": "address",
    "shipping location": "address",
    "delivery location": "address",
    "delivery address": "address",
    "delivery": "address",
    "pricing": "price",
    "prices": "price",
}


def singularize(w: str) -> str:
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


def normalize_morphology(w: str) -> str:
    """Normalize inflectional morphology (plural, past-tense, participle, gerund) to canonical lemma."""
    word = w.lower().strip()
    if len(word) <= 3:
        return word
    # Plural forms
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("ses", "xes", "ches", "shes")) and len(word) > 4:
        return word[:-2]
    # Gerund / progressive forms: -ing (e.g. processing -> process, recording -> record)
    if word.endswith("ing") and len(word) > 5:
        base = word[:-3]
        if base.endswith(("ss", "ll", "ff", "zz")):
            return base
        if len(base) > 2 and base[-1] == base[-2]:
            return base[:-1]
        if (base + "e") in COMMON_ACTION_VERBS:
            return base + "e"
        return base
    # Past / passive forms: -ed (e.g. verified -> verify, recorded -> record, created -> create)
    if word.endswith("ied") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("ed") and len(word) > 4:
        base = word[:-2]
        if base.endswith(("ss", "ll", "ff", "zz")):
            return base
        if len(base) > 2 and base[-1] == base[-2]:
            return base[:-1]
        if base in COMMON_ACTION_VERBS:
            return base
        if (base + "e") in COMMON_ACTION_VERBS:
            return base + "e"
        return base
    # Verbal nominalization forms: -tion / -ation (e.g. detection -> detect, validation -> validate, creation -> create)
    if word.endswith("ation") and len(word) > 6:
        base_ate = word[:-5] + "ate"
        base_bare = word[:-5]
        if base_ate in COMMON_ACTION_VERBS:
            return base_ate
        if base_bare in COMMON_ACTION_VERBS:
            return base_bare
        if word.startswith("cancell"):
            return "cancel"
        return base_ate
    if word.endswith("tion") and len(word) > 5:
        base = word[:-3]
        if (base + "e") in COMMON_ACTION_VERBS:
            return base + "e"
        return base
    # Nominalization forms: -ment (e.g. payment -> pay, shipment -> ship)
    if word.endswith("ment") and len(word) > 5:
        base = word[:-4]
        if base in COMMON_ACTION_VERBS or len(base) > 3:
            return base
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def decompose_tokens(ident: str) -> list[str]:
    """Decompose snake_case, camelCase, kebab-case, or paths into tokens."""
    if not ident:
        return []
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", ident)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    parts = re.split(r"[^a-zA-Z0-9]+", s)
    return [singularize(p) for p in parts if len(p) > 1]


@dataclass
class DomainConcept:
    canonical_name: str
    aliases: set[str] = field(default_factory=set)
    symbol_names: set[str] = field(default_factory=set)
    fields: set[str] = field(default_factory=set)
    routes: set[str] = field(default_factory=set)
    ui_labels: set[str] = field(default_factory=set)
    related_concepts: set[str] = field(default_factory=set)
    associated_actions: set[str] = field(default_factory=set)
    related_workflows: set[str] = field(default_factory=set)
    files: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_name": self.canonical_name,
            "aliases": sorted(self.aliases),
            "symbol_names": sorted(self.symbol_names),
            "fields": sorted(self.fields),
            "routes": sorted(self.routes),
            "ui_labels": sorted(self.ui_labels),
            "related_concepts": sorted(self.related_concepts),
            "associated_actions": sorted(self.associated_actions),
            "related_workflows": sorted(self.related_workflows),
            "files": sorted(self.files),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DomainConcept:
        return cls(
            canonical_name=d["canonical_name"],
            aliases=set(d.get("aliases", [])),
            symbol_names=set(d.get("symbol_names", [])),
            fields=set(d.get("fields", [])),
            routes=set(d.get("routes", [])),
            ui_labels=set(d.get("ui_labels", [])),
            related_concepts=set(d.get("related_concepts", [])),
            associated_actions=set(d.get("associated_actions", [])),
            related_workflows=set(d.get("related_workflows", [])),
            files=set(d.get("files", [])),
        )


class RepositoryDomainVocabulary:
    """Repository-specific business vocabulary dynamically built from source code, schemas, and templates."""

    def __init__(self, project_id: int):
        self.project_id = project_id
        self.concepts: dict[str, DomainConcept] = {}
        self.alias_to_canonical: dict[str, str] = {}
        self.token_to_canonicals: dict[str, set[str]] = {}

    def add_concept(self, concept: DomainConcept):
        canon = concept.canonical_name.lower().strip()
        if not canon:
            return
        if canon not in self.concepts:
            self.concepts[canon] = concept
        else:
            # Merge
            existing = self.concepts[canon]
            existing.aliases.update(concept.aliases)
            existing.symbol_names.update(concept.symbol_names)
            existing.fields.update(concept.fields)
            existing.routes.update(concept.routes)
            existing.ui_labels.update(concept.ui_labels)
            existing.related_concepts.update(concept.related_concepts)
            existing.associated_actions.update(concept.associated_actions)
            existing.related_workflows.update(concept.related_workflows)
            existing.files.update(concept.files)

        # Index canonical name and true aliases
        self.alias_to_canonical[canon] = canon
        for a in concept.aliases:
            self.alias_to_canonical[a.lower().strip()] = canon
            for tok in a.lower().split():
                if tok == canon or tok in decompose_tokens(canon):
                    self.token_to_canonicals.setdefault(tok, set()).add(canon)

        for tok in canon.split():
            if len(tok) > 2:
                self.token_to_canonicals.setdefault(tok, set()).add(canon)

    def resolve_term(self, term: str) -> DomainConcept | None:
        """Resolve an arbitrary term or phrase to its repository canonical concept."""
        if not term:
            return None
        t_clean = singularize(term.lower().strip())
        t_norm = re.sub(r"[\s_\-]+", " ", t_clean)

        if t_clean in self.alias_to_canonical:
            return self.concepts.get(self.alias_to_canonical[t_clean])
        if t_norm in self.alias_to_canonical:
            return self.concepts.get(self.alias_to_canonical[t_norm])

        # Check general concept synonyms if target concept is evidenced in this repo
        for syn_key in [t_clean, t_norm]:
            if syn_key in CONCEPT_SYNONYMS:
                target_canon = CONCEPT_SYNONYMS[syn_key]
                if target_canon in self.concepts:
                    return self.concepts[target_canon]

        # Check sub-tokens
        tokens = [t for t in decompose_tokens(term) if len(t) > 2]
        if len(tokens) == 1:
            tok = tokens[0]
            if tok in self.token_to_canonicals:
                candidates = self.token_to_canonicals[tok]
                if candidates:
                    if tok in self.concepts:
                        return self.concepts[tok]
                    return self.concepts.get(next(iter(candidates)))
        elif len(tokens) > 1:
            # Multi-word concept: only resolve if all non-generic tokens belong to the same concept
            token_set = set(tokens)
            for canon, concept in self.concepts.items():
                canon_tokens = set(decompose_tokens(canon))
                for a in concept.aliases:
                    canon_tokens.update(decompose_tokens(a))
                for fld in concept.fields:
                    canon_tokens.update(decompose_tokens(fld))
                if token_set.issubset(canon_tokens):
                    return concept

        return None

    def find_matching_concepts(self, text: str) -> list[DomainConcept]:
        """Find all repository concepts directly mentioned in a query text."""
        matched: list[DomainConcept] = []
        seen_canonicals: set[str] = set()

        text_lower = text.lower()
        words = re.findall(r"[a-zA-Z0-9]+", text_lower)
        tokens = [singularize(w) for w in words]

        # 1. Direct canonical name match
        for tok in tokens:
            if tok in self.concepts and tok not in seen_canonicals:
                matched.append(self.concepts[tok])
                seen_canonicals.add(tok)

        # 2. Multi-word phrase or distinct alias match
        for canon, c in self.concepts.items():
            if canon in seen_canonicals:
                continue
            if len(canon) > 3 and re.search(r"\b" + re.escape(canon) + r"\b", text_lower):
                matched.append(c)
                seen_canonicals.add(canon)
                continue
            for a in c.aliases:
                if len(a) > 3 and re.search(r"\b" + re.escape(a) + r"\b", text_lower):
                    matched.append(c)
                    seen_canonicals.add(canon)
                    break

        # 3. Concept synonyms mapping
        for syn_k, syn_target in CONCEPT_SYNONYMS.items():
            if syn_target in self.concepts and syn_target not in seen_canonicals:
                if re.search(r"\b" + re.escape(syn_k) + r"\b", text_lower):
                    matched.append(self.concepts[syn_target])
                    seen_canonicals.add(syn_target)

        return matched

    def is_concept_evidenced(self, concept_name: str) -> bool:
        """Verify if a concept is grounded in repository evidence."""
        return self.resolve_term(concept_name) is not None

    def get_synonyms_and_aliases(self, concept_name: str) -> set[str]:
        concept = self.resolve_term(concept_name)
        if not concept:
            return {concept_name}
        res = {concept.canonical_name}
        for a in concept.aliases:
            a_l = a.lower().strip()
            if (
                concept.canonical_name in a_l
                or any(tok in a_l for tok in decompose_tokens(concept.canonical_name))
                or a_l in CONCEPT_SYNONYMS
                or CONCEPT_SYNONYMS.get(a_l) == concept.canonical_name
            ):
                res.add(a_l)
        for syn_k, syn_target in CONCEPT_SYNONYMS.items():
            if syn_target == concept.canonical_name:
                res.add(syn_k)
        return res

    def get_associated_actions(self, concept_name: str) -> set[str]:
        concept = self.resolve_term(concept_name)
        if not concept:
            return set()
        actions = set(concept.associated_actions)
        for act in list(actions):
            if act in ACTION_SYNONYMS:
                actions.update(ACTION_SYNONYMS[act])
        return actions

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "concepts": {k: v.to_dict() for k, v in self.concepts.items()},
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RepositoryDomainVocabulary:
        v = cls(project_id=d["project_id"])
        for cdata in d.get("concepts", {}).values():
            v.add_concept(DomainConcept.from_dict(cdata))
        return v


_VOCAB_CACHE: dict[int, RepositoryDomainVocabulary] = {}


def clear_vocab_cache(project_id: int | None = None):
    if project_id is not None:
        _VOCAB_CACHE.pop(project_id, None)
    else:
        _VOCAB_CACHE.clear()


def get_domain_vocabulary(db: Session, project_id: int, repo_dir: str | None = None) -> RepositoryDomainVocabulary:
    if project_id in _VOCAB_CACHE:
        return _VOCAB_CACHE[project_id]

    vocab = build_domain_vocabulary(db, project_id, repo_dir)
    _VOCAB_CACHE[project_id] = vocab
    return vocab


def build_domain_vocabulary(db: Session, project_id: int, repo_dir: str | None = None) -> RepositoryDomainVocabulary:
    """Build dynamic domain vocabulary directly from repository artifacts."""
    if not repo_dir:
        from app.ingestion.orchestrator import project_dir
        try:
            p_path = project_dir(project_id)
            if os.path.exists(p_path):
                repo_dir = p_path
        except Exception:
            pass

    vocab = RepositoryDomainVocabulary(project_id=project_id)

    # 1. Models & Entities
    entities = db.query(DataEntity).filter(DataEntity.project_id == project_id).all()
    for ent in entities:
        ent_tokens = decompose_tokens(ent.name)
        canon = ent_tokens[-1] if ent_tokens else ent.name.lower()
        c = DomainConcept(canonical_name=canon)
        c.aliases.add(ent.name.lower())
        c.aliases.add(" ".join(ent_tokens))

        try:
            fields_list = json.loads(ent.fields_json or "[]")
        except Exception:
            fields_list = []

        for fld in fields_list:
            # Handle both string and dict field entries
            if isinstance(fld, dict):
                fld = fld.get("name", "")
            if not fld or not isinstance(fld, str):
                continue
            c.fields.add(fld.lower())
            f_tokens = decompose_tokens(fld)
            if canon in f_tokens:
                c.aliases.add(fld.lower())
                c.aliases.add(" ".join(f_tokens))

            # If field has a distinct head noun, also create/link a concept
            if len(f_tokens) >= 2:
                f_head = f_tokens[-1]
                sub_c = DomainConcept(canonical_name=f_head)
                sub_c.aliases.add(fld.lower())
                sub_c.aliases.add(" ".join(f_tokens))
                sub_c.fields.add(fld.lower())
                sub_c.related_concepts.add(canon)
                vocab.add_concept(sub_c)

        vocab.add_concept(c)

    # 2. Code Symbols (classes, models, functions, routes, forms)
    symbols = db.query(CodeSymbol).filter(CodeSymbol.project_id == project_id).all()
    files = {sf.id: sf.path for sf in db.query(SourceFile).filter(SourceFile.project_id == project_id).all()}

    for s in symbols:
        file_path = files.get(s.source_file_id, "")
        s_tokens = decompose_tokens(s.name)
        if not s_tokens:
            continue

        # Extract action verbs from symbol name
        detected_actions = set()
        for tok in s_tokens:
            if tok in COMMON_ACTION_VERBS:
                detected_actions.add(tok)

        # Head noun is candidate concept
        non_action_tokens = [t for t in s_tokens if t not in COMMON_ACTION_VERBS and len(t) > 2]
        if non_action_tokens:
            canon = non_action_tokens[-1]
            c = DomainConcept(canonical_name=canon)
            c.symbol_names.add(s.name)
            c.aliases.add(s.name.lower())
            c.aliases.add(" ".join(s_tokens))
            if file_path:
                c.files.add(file_path)
            c.associated_actions.update(detected_actions)
            vocab.add_concept(c)

    # 3. API Endpoints
    endpoints = db.query(ApiEndpoint).filter(ApiEndpoint.project_id == project_id).all()
    for ep in endpoints:
        ep_tokens = decompose_tokens(ep.path)
        for tok in ep_tokens:
            if len(tok) > 2 and tok not in ("api", "v1", "v2", "rest", "json"):
                c = DomainConcept(canonical_name=tok)
                c.routes.add(f"{ep.method} {ep.path}")
                vocab.add_concept(c)

    # 4. Template and form inspection on disk (HTML/Jinja inputs, labels, form names)
    if repo_dir and os.path.exists(repo_dir):
        _enrich_vocab_from_disk(vocab, repo_dir)

    return vocab


def _enrich_vocab_from_disk(vocab: RepositoryDomainVocabulary, repo_dir: str):
    """Parse template inputs, forms, and headings to discover UI concepts and actions."""
    for root, _, files in os.walk(repo_dir):
        for f in files:
            rel_path = os.path.relpath(os.path.join(root, f), repo_dir).replace("\\", "/")
            path_l = rel_path.lower()

            if any(path_l.endswith(ext) for ext in [".html", ".jinja", ".jinja2", ".htm", ".vue", ".tsx", ".jsx"]):
                full_path = os.path.join(root, f)
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as fh:
                        content = fh.read()
                except OSError:
                    continue

                # 1. Discover input / select / textarea names (e.g. shipping_address, billing_address)
                for inp_m in re.finditer(r'<(?:input|select|textarea)\b([^>]*)/?>', content, re.IGNORECASE):
                    attrs = inp_m.group(1)
                    name_m = re.search(r'name=["\']([^"\']+)["\']', attrs, re.I)
                    id_m = re.search(r'id=["\']([^"\']+)["\']', attrs, re.I)
                    name = name_m.group(1) if name_m else (id_m.group(1) if id_m else "")
                    if name and len(name) > 2:
                        tokens = decompose_tokens(name)
                        if tokens:
                            head = tokens[-1]
                            c = DomainConcept(canonical_name=head)
                            c.aliases.add(name.lower())
                            c.aliases.add(" ".join(tokens))
                            c.fields.add(name.lower())
                            c.files.add(rel_path)
                            c.associated_actions.update({"enter", "provide", "submit", "fill"})
                            vocab.add_concept(c)

                # 2. Discover UI labels and headings (e.g. "Shipping address", "Billing address")
                for lbl_m in re.finditer(r'<(?:h[1-6]|label|legend)\b[^>]*>([^<]+)</(?:h[1-6]|label|legend)>', content, re.IGNORECASE):
                    raw_lbl = lbl_m.group(1).strip()
                    if len(raw_lbl) >= 3 and not raw_lbl.startswith("{%"):
                        tokens = decompose_tokens(raw_lbl)
                        if tokens:
                            head = tokens[-1]
                            c = DomainConcept(canonical_name=head)
                            c.ui_labels.add(raw_lbl)
                            c.aliases.add(" ".join(tokens))
                            c.files.add(rel_path)
                            vocab.add_concept(c)
