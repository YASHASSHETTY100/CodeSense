"""Repository Knowledge Graph: multi-entity, multi-layer semantic graph.

Supports 24 node types and 18 relationship types.
Provides multi-hop neighborhood expansion, cross-layer functional tracing
(UI -> Form -> Route -> Controller -> Service -> Model -> Database -> Integration),
and project isolation.
"""
from __future__ import annotations
import os, json, re
from dataclasses import dataclass, field
from typing import Any
from sqlalchemy.orm import Session
from app.models.models import (
    Project, Module, SourceFile, CodeSymbol, ApiEndpoint, DataEntity, BusinessRule, Role, Relation
)

# 24 Canonical Node Kinds
NODE_PROJECT = "project"
NODE_MODULE = "module"
NODE_FILE = "file"
NODE_CLASS = "class"
NODE_FUNCTION = "function"
NODE_METHOD = "method"
NODE_ROUTE = "route"
NODE_API = "api"
NODE_MODEL = "model"
NODE_DB_TABLE = "database_table"
NODE_DB_FIELD = "database_field"
NODE_UI_COMPONENT = "ui_component"
NODE_TEMPLATE = "template"
NODE_FORM = "form"
NODE_FORM_FIELD = "form_field"
NODE_SERIALIZER = "serializer"
NODE_SERVICE = "service"
NODE_INTEGRATION = "integration"
NODE_CONFIGURATION = "configuration"
NODE_PERMISSION = "permission"
NODE_ROLE = "role"
NODE_BUSINESS_RULE = "business_rule"
NODE_WORKFLOW = "workflow"
NODE_ERROR = "error"
NODE_DEPENDENCY = "dependency"

# 18 Canonical Edge Kinds
EDGE_CALLS = "CALLS"
EDGE_CALLED_BY = "CALLED_BY"
EDGE_IMPORTS = "IMPORTS"
EDGE_IMPLEMENTS = "IMPLEMENTS"
EDGE_INHERITS = "INHERITS"
EDGE_READS = "READS"
EDGE_WRITES = "WRITES"
EDGE_ROUTES_TO = "ROUTES_TO"
EDGE_USES_MODEL = "USES_MODEL"
EDGE_USES_SERVICE = "USES_SERVICE"
EDGE_USES_API = "USES_API"
EDGE_USES_DATABASE = "USES_DATABASE"
EDGE_RENDERS = "RENDERS"
EDGE_VALIDATES = "VALIDATES"
EDGE_AUTHORIZES = "AUTHORIZES"
EDGE_NOTIFIES = "NOTIFIES"
EDGE_INTEGRATES_WITH = "INTEGRATES_WITH"
EDGE_DEPENDS_ON = "DEPENDS_ON"
EDGE_CONTAINS = "CONTAINS"
EDGE_BELONGS_TO = "BELONGS_TO"

NODE_VALIDATION = "validation"

# Convenient aliases for relationship constants
REL_CALLS = EDGE_CALLS
REL_CALLED_BY = EDGE_CALLED_BY
REL_IMPORTS = EDGE_IMPORTS
REL_IMPLEMENTS = EDGE_IMPLEMENTS
REL_INHERITS = EDGE_INHERITS
REL_READS = EDGE_READS
REL_WRITES = EDGE_WRITES
REL_ROUTES_TO = EDGE_ROUTES_TO
REL_USES_MODEL = EDGE_USES_MODEL
REL_USES_SERVICE = EDGE_USES_SERVICE
REL_USES_API = EDGE_USES_API
REL_USES_DATABASE = EDGE_USES_DATABASE
REL_RENDERS = EDGE_RENDERS
REL_VALIDATES = EDGE_VALIDATES
REL_AUTHORIZES = EDGE_AUTHORIZES
REL_NOTIFIES = EDGE_NOTIFIES
REL_INTEGRATES_WITH = EDGE_INTEGRATES_WITH
REL_DEPENDS_ON = EDGE_DEPENDS_ON


@dataclass
class GraphNode:
    id: str
    kind: str
    name: str
    file_path: str = ""
    start_line: int = 0
    end_line: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GraphNode:
        return cls(
            id=d["id"],
            kind=d["kind"],
            name=d["name"],
            file_path=d.get("file_path", ""),
            start_line=d.get("start_line", 0),
            end_line=d.get("end_line", 0),
            metadata=d.get("metadata", {}),
        )


@dataclass
class GraphEdge:
    source_id: str
    target_id: str
    kind: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "kind": self.kind,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GraphEdge:
        return cls(
            source_id=d["source_id"],
            target_id=d["target_id"],
            kind=d["kind"],
            metadata=d.get("metadata", {}),
        )


class RepositoryKnowledgeGraph:
    """Directed, multi-relational knowledge graph representing repository architecture."""

    def __init__(self, project_id: int):
        self.project_id = project_id
        self.nodes: dict[str, GraphNode] = {}
        self.outgoing: dict[str, list[GraphEdge]] = {}
        self.incoming: dict[str, list[GraphEdge]] = {}
        self.by_kind: dict[str, list[str]] = {}
        self.by_name: dict[str, list[str]] = {}

    def add_node(self, node: GraphNode) -> GraphNode:
        if not node.id:
            node.id = f"{node.kind}:{node.name}"
        self.nodes[node.id] = node
        self.outgoing.setdefault(node.id, [])
        self.incoming.setdefault(node.id, [])
        self.by_kind.setdefault(node.kind, []).append(node.id)

        # Index by normalized name tokens
        norm_name = node.name.lower().strip()
        self.by_name.setdefault(norm_name, []).append(node.id)
        # Also index alphanumeric parts
        parts = re.split(r"[^a-zA-Z0-9]+", norm_name)
        for p in parts:
            if len(p) > 2:
                self.by_name.setdefault(p, []).append(node.id)
        return node

    def add_edge(
        self,
        source_id: str | GraphEdge,
        target_id: str | None = None,
        kind: str | None = None,
        metadata: dict[str, Any] | None = None
    ) -> GraphEdge | None:
        if isinstance(source_id, GraphEdge):
            edge = source_id
            s_id = edge.source_id
            t_id = edge.target_id
            k = edge.kind
            m = edge.metadata
        else:
            s_id = source_id
            t_id = target_id or ""
            k = kind or ""
            m = metadata or {}
            edge = GraphEdge(source_id=s_id, target_id=t_id, kind=k, metadata=m)

        if s_id not in self.nodes or t_id not in self.nodes:
            # Edges must connect existing nodes
            return None

        self.outgoing[s_id].append(edge)
        self.incoming[t_id].append(edge)
        kind = k
        metadata = m
        target_id = t_id
        source_id = s_id

        # Automatically record inverse for directional relations if useful
        if kind == EDGE_CALLS:
            rev = GraphEdge(source_id=target_id, target_id=source_id, kind=EDGE_CALLED_BY, metadata=metadata or {})
            self.outgoing[target_id].append(rev)
            self.incoming[source_id].append(rev)

        return edge

    def get_node(self, node_id: str) -> GraphNode | None:
        return self.nodes.get(node_id)

    def find_nodes(
        self,
        kind: str | None = None,
        name_substring: str | None = None,
        file_path: str | None = None
    ) -> list[GraphNode]:
        candidates = self.nodes.values()
        if kind:
            node_ids = set(self.by_kind.get(kind, []))
            candidates = [self.nodes[nid] for nid in node_ids if nid in self.nodes]
        if file_path:
            fp_l = file_path.lower()
            candidates = [n for n in candidates if fp_l in n.file_path.lower()]
        if name_substring:
            sub = name_substring.lower()
            candidates = [n for n in candidates if sub in n.name.lower()]
        return list(candidates)

    def search_nodes(self, query_tokens: list[str]) -> list[tuple[float, GraphNode]]:
        """Search nodes by token match and relevance score."""
        scores: dict[str, float] = {}
        for tok in query_tokens:
            tok_l = tok.lower().strip()
            if not tok_l or len(tok_l) <= 2:
                continue
            matched_ids = self.by_name.get(tok_l, [])
            for nid in matched_ids:
                scores[nid] = scores.get(nid, 0.0) + 2.0
            # Partial substring matches
            for nid, node in self.nodes.items():
                if tok_l in node.name.lower():
                    scores[nid] = scores.get(nid, 0.0) + 1.0
                if node.file_path and tok_l in node.file_path.lower():
                    scores[nid] = scores.get(nid, 0.0) + 0.5

        ranked = [(score, self.nodes[nid]) for nid, score in scores.items() if nid in self.nodes]
        ranked.sort(key=lambda x: x[0], reverse=True)
        return ranked

    def expand_neighborhood(
        self,
        seed_node_ids: list[str],
        max_hops: int = 2,
        allowed_edge_kinds: set[str] | None = None
    ) -> set[str]:
        """Expand neighborhood around seed nodes up to max_hops."""
        visited: set[str] = set(seed_node_ids)
        current_frontier: set[str] = set(seed_node_ids)

        for _ in range(max_hops):
            next_frontier: set[str] = set()
            for nid in current_frontier:
                for edge in self.outgoing.get(nid, []):
                    if allowed_edge_kinds and edge.kind not in allowed_edge_kinds:
                        continue
                    if edge.target_id not in visited:
                        visited.add(edge.target_id)
                        next_frontier.add(edge.target_id)
                for edge in self.incoming.get(nid, []):
                    if allowed_edge_kinds and edge.kind not in allowed_edge_kinds:
                        continue
                    if edge.source_id not in visited:
                        visited.add(edge.source_id)
                        next_frontier.add(edge.source_id)
            current_frontier = next_frontier
            if not current_frontier:
                break

        return visited

    def trace_cross_layer(self, concept: str) -> dict[str, list[GraphNode]]:
        """Reconstruct cross-layer functional trace for a concept:

        UI -> Form -> Route -> Controller -> Service -> Model -> Database -> Integration.
        """
        concept_lower = concept.lower()
        concept_tokens = [t for t in re.split(r"[^a-zA-Z0-9]+", concept_lower) if len(t) > 2]

        matched_nodes = [node for _, node in self.search_nodes(concept_tokens)]
        if not matched_nodes:
            return {}

        seed_ids = [n.id for n in matched_nodes[:10]]
        expanded_ids = self.expand_neighborhood(seed_ids, max_hops=2)
        all_relevant = [self.nodes[nid] for nid in expanded_ids if nid in self.nodes]

        layers: dict[str, list[GraphNode]] = {
            "ui": [],
            "form": [],
            "route": [],
            "controller": [],
            "service": [],
            "model": [],
            "database": [],
            "rule_validation": [],
            "integration": [],
        }

        for n in all_relevant:
            if n.kind in (NODE_UI_COMPONENT, NODE_TEMPLATE):
                layers["ui"].append(n)
            elif n.kind in (NODE_FORM, NODE_FORM_FIELD):
                layers["form"].append(n)
            elif n.kind in (NODE_ROUTE, NODE_API):
                layers["route"].append(n)
            elif n.kind in (NODE_CLASS, NODE_FUNCTION, NODE_METHOD) and ("view" in n.name.lower() or "controller" in n.name.lower() or "handler" in n.name.lower()):
                layers["controller"].append(n)
            elif n.kind in (NODE_SERVICE, NODE_FUNCTION, NODE_METHOD):
                layers["service"].append(n)
            elif n.kind == NODE_MODEL:
                layers["model"].append(n)
            elif n.kind in (NODE_DB_TABLE, NODE_DB_FIELD):
                layers["database"].append(n)
            elif n.kind in (NODE_BUSINESS_RULE, NODE_PERMISSION, NODE_ROLE):
                layers["rule_validation"].append(n)
            elif n.kind == NODE_INTEGRATION:
                layers["integration"].append(n)

        # Filter out empty layers
        return {k: v for k, v in layers.items() if v}

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [
                edge.to_dict()
                for edge_list in self.outgoing.values()
                for edge in edge_list
            ],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RepositoryKnowledgeGraph:
        g = cls(project_id=d["project_id"])
        for nd in d.get("nodes", []):
            g.add_node(GraphNode.from_dict(nd))
        for ed in d.get("edges", []):
            g.add_edge(ed["source_id"], ed["target_id"], ed["kind"], ed.get("metadata", {}))
        return g


# In-memory graph cache keyed by project_id
_GRAPH_CACHE: dict[int, RepositoryKnowledgeGraph] = {}


def get_knowledge_graph(db: Session, project_id: int, repo_dir: str | None = None) -> RepositoryKnowledgeGraph:
    """Retrieve or build repository-specific knowledge graph."""
    if project_id in _GRAPH_CACHE:
        return _GRAPH_CACHE[project_id]

    graph = build_knowledge_graph(db, project_id, repo_dir)
    _GRAPH_CACHE[project_id] = graph
    return graph


def clear_graph_cache(project_id: int | None = None):
    if project_id is not None:
        _GRAPH_CACHE.pop(project_id, None)
    else:
        _GRAPH_CACHE.clear()


def build_knowledge_graph(db: Session, project_id: int, repo_dir: str | None = None) -> RepositoryKnowledgeGraph:
    """Build knowledge graph from database entities, symbols, routes, relations, and filesystem."""
    if not repo_dir:
        from app.ingestion.orchestrator import project_dir
        try:
            p_path = project_dir(project_id)
            if os.path.exists(p_path):
                repo_dir = p_path
        except Exception:
            pass

    g = RepositoryKnowledgeGraph(project_id=project_id)

    # 1. Project node
    proj = db.query(Project).filter(Project.id == project_id).first()
    proj_name = proj.name if proj else f"Project_{project_id}"
    proj_node = GraphNode(id=f"project:{project_id}", kind=NODE_PROJECT, name=proj_name)
    g.add_node(proj_node)

    # 2. Modules
    modules = db.query(Module).filter(Module.project_id == project_id).all()
    mod_map: dict[int, str] = {}
    for m in modules:
        mname = m.name.replace("module:", "")
        nid = f"module:{mname}"
        mod_node = GraphNode(id=nid, kind=NODE_MODULE, name=mname, metadata={"description": m.description})
        g.add_node(mod_node)
        g.add_edge(proj_node.id, nid, EDGE_CONTAINS)
        mod_map[m.id] = nid

    # 3. Source Files
    files = db.query(SourceFile).filter(SourceFile.project_id == project_id).all()
    file_map: dict[int, str] = {}
    for sf in files:
        fnid = f"file:{sf.path}"
        fnode = GraphNode(id=fnid, kind=NODE_FILE, name=sf.path, file_path=sf.path, metadata={"language": sf.language})
        g.add_node(fnode)
        file_map[sf.id] = fnid

        # Determine file type node (e.g. template, config)
        path_l = sf.path.lower()
        if any(path_l.endswith(ext) for ext in [".html", ".jinja", ".jinja2", ".j2", ".ejs", ".hbs", ".mustache"]):
            tnid = f"template:{sf.path}"
            g.add_node(GraphNode(id=tnid, kind=NODE_TEMPLATE, name=os.path.basename(sf.path), file_path=sf.path))
            g.add_edge(fnid, tnid, EDGE_CONTAINS)
        elif any(term in path_l for term in ["settings", "config", ".ini", ".env", ".yaml", ".yml", ".toml"]):
            cnid = f"config:{sf.path}"
            g.add_node(GraphNode(id=cnid, kind=NODE_CONFIGURATION, name=os.path.basename(sf.path), file_path=sf.path))
            g.add_edge(fnid, cnid, EDGE_CONTAINS)

    # 4. Code Symbols
    symbols = db.query(CodeSymbol).filter(CodeSymbol.project_id == project_id).all()
    sym_map: dict[int, str] = {}
    for s in symbols:
        sf = next((f for f in files if f.id == s.source_file_id), None)
        path = sf.path if sf else ""
        snid = f"symbol:{s.id}:{s.name}"

        # Map symbol kind to canonical node kind
        skind = NODE_FUNCTION
        if s.kind == "class":
            skind = NODE_CLASS
        elif s.kind == "model":
            skind = NODE_MODEL
        elif s.kind == "route":
            skind = NODE_ROUTE
        elif s.kind == "component":
            skind = NODE_UI_COMPONENT
        elif s.kind == "form":
            skind = NODE_FORM
        elif s.kind == "serializer":
            skind = NODE_SERIALIZER
        elif "service" in s.name.lower():
            skind = NODE_SERVICE

        snode = GraphNode(
            id=snid,
            kind=skind,
            name=s.name,
            file_path=path,
            start_line=s.start_line,
            end_line=s.end_line,
            metadata={"signature": s.signature, "docstring": s.docstring}
        )
        g.add_node(snode)
        sym_map[s.id] = snid

        if s.source_file_id in file_map:
            g.add_edge(file_map[s.source_file_id], snid, EDGE_CONTAINS)

    # 5. API Endpoints
    endpoints = db.query(ApiEndpoint).filter(ApiEndpoint.project_id == project_id).all()
    for ep in endpoints:
        enid = f"endpoint:{ep.method}_{ep.path}"
        enode = GraphNode(
            id=enid,
            kind=NODE_API,
            name=f"{ep.method} {ep.path}",
            metadata={"method": ep.method, "path": ep.path, "auth": ep.auth_required, "roles": ep.roles_allowed}
        )
        g.add_node(enode)
        if ep.handler_symbol_id and ep.handler_symbol_id in sym_map:
            g.add_edge(enid, sym_map[ep.handler_symbol_id], EDGE_ROUTES_TO)

    # 6. Data Entities & Fields
    entities = db.query(DataEntity).filter(DataEntity.project_id == project_id).all()
    for de in entities:
        dnid = f"entity:{de.name}"
        dnode = GraphNode(id=dnid, kind=NODE_DB_TABLE, name=de.name, metadata={"fields": de.fields_json, "relations": de.relations_json})
        g.add_node(dnode)

        # Add fields as nodes
        try:
            fields_list = json.loads(de.fields_json or "[]")
        except Exception:
            fields_list = []
        for fld in fields_list:
            # Handle both string and dict field entries
            fld_name = fld.get("name", "") if isinstance(fld, dict) else str(fld)
            if not fld_name:
                continue
            fnid = f"field:{de.name}.{fld_name}"
            fnode = GraphNode(id=fnid, kind=NODE_DB_FIELD, name=fld_name, metadata={"table": de.name})
            g.add_node(fnode)
            g.add_edge(dnid, fnid, EDGE_CONTAINS)

        if de.source_symbol_id and de.source_symbol_id in sym_map:
            g.add_edge(sym_map[de.source_symbol_id], dnid, EDGE_USES_DATABASE)

    # 7. Business Rules
    rules = db.query(BusinessRule).filter(BusinessRule.project_id == project_id).all()
    for r in rules:
        rnid = f"rule:{r.id}"
        rnode = GraphNode(id=rnid, kind=NODE_BUSINESS_RULE, name=r.description[:80], metadata={"trigger": r.trigger_condition, "description": r.description})
        g.add_node(rnode)
        if r.source_symbol_id and r.source_symbol_id in sym_map:
            g.add_edge(sym_map[r.source_symbol_id], rnid, EDGE_VALIDATES)

    # 8. Roles & Permissions
    roles = db.query(Role).filter(Role.project_id == project_id).all()
    for ro in roles:
        rnid = f"role:{ro.name}"
        rnode = GraphNode(id=rnid, kind=NODE_ROLE, name=ro.name, metadata={"permissions": ro.permissions_json})
        g.add_node(rnode)

    # 9. Relations table integration
    rels = db.query(Relation).filter(Relation.project_id == project_id).all()
    for rel in rels:
        # Resolve from/to ids
        src_id = None
        tgt_id = None
        if rel.from_type == "symbol" and rel.from_id in sym_map:
            src_id = sym_map[rel.from_id]
        elif rel.from_type == "endpoint":
            src_id = next((n.id for n in g.nodes.values() if n.kind == NODE_API and f"_{rel.from_id}" in n.id), None)
        if rel.to_type == "symbol" and rel.to_id in sym_map:
            tgt_id = sym_map[rel.to_id]
        elif rel.to_type == "module" and rel.to_id in mod_map:
            tgt_id = mod_map[rel.to_id]

        if src_id and tgt_id:
            ekind = EDGE_CALLS
            if rel.relation_kind == "reads":
                ekind = EDGE_READS
            elif rel.relation_kind == "writes":
                ekind = EDGE_WRITES
            elif rel.relation_kind == "belongs_to_module":
                ekind = EDGE_BELONGS_TO
            g.add_edge(src_id, tgt_id, ekind)

    # 10. File-level inspection for templates, forms, renders and integrations
    if repo_dir and os.path.exists(repo_dir):
        _enrich_graph_from_disk(g, repo_dir)

    return g


def _enrich_graph_from_disk(g: RepositoryKnowledgeGraph, repo_dir: str):
    """Scan disk for template forms, input fields, view renders, and third-party integrations."""
    for root, _, files in os.walk(repo_dir):
        for f in files:
            rel_path = os.path.relpath(os.path.join(root, f), repo_dir).replace("\\", "/")
            path_l = rel_path.lower()

            # Inspect HTML / Jinja / Django templates
            if any(path_l.endswith(ext) for ext in [".html", ".jinja", ".jinja2", ".j2", ".htm"]):
                full_path = os.path.join(root, f)
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as fh:
                        content = fh.read()
                except OSError:
                    continue

                tmpl_id = f"template:{rel_path}"
                if tmpl_id not in g.nodes:
                    g.add_node(GraphNode(id=tmpl_id, kind=NODE_TEMPLATE, name=f, file_path=rel_path))

                # Extract forms
                for form_m in re.finditer(r"<form\b([^>]*)>([\s\S]*?)</form>", content, re.I):
                    attrs = form_m.group(1)
                    body = form_m.group(2)
                    action_m = re.search(r'action=["\']([^"\']+)["\']', attrs, re.I)
                    action = action_m.group(1) if action_m else ""
                    form_name = f"{f}_form"
                    form_id = f"form:{rel_path}:{form_name}"
                    g.add_node(GraphNode(id=form_id, kind=NODE_FORM, name=form_name, file_path=rel_path, metadata={"action": action}))
                    g.add_edge(tmpl_id, form_id, EDGE_CONTAINS)

                    # Extract input elements inside form
                    for inp_m in re.finditer(r'<(?:input|select|textarea)\b([^>]*)/?>', body, re.I):
                        inp_attrs = inp_m.group(1)
                        name_m = re.search(r'name=["\']([^"\']+)["\']', inp_attrs, re.I)
                        id_m = re.search(r'id=["\']([^"\']+)["\']', inp_attrs, re.I)
                        inp_name = name_m.group(1) if name_m else (id_m.group(1) if id_m else "")
                        if inp_name:
                            fld_id = f"form_field:{rel_path}:{inp_name}"
                            g.add_node(GraphNode(id=fld_id, kind=NODE_FORM_FIELD, name=inp_name, file_path=rel_path, metadata={"form": form_name}))
                            g.add_edge(form_id, fld_id, EDGE_CONTAINS)

                    # Connect form action to existing API routes
                    if action:
                        clean_action = action.split("?")[0].strip()
                        for ep_node in g.find_nodes(kind=NODE_API):
                            ep_path = ep_node.metadata.get("path", "")
                            if ep_path and (clean_action == ep_path or clean_action.endswith(ep_path) or ep_path.endswith(clean_action)):
                                g.add_edge(form_id, ep_node.id, EDGE_ROUTES_TO)

            # Inspect python views for render() calls connecting controllers to templates
            elif path_l.endswith(".py"):
                full_path = os.path.join(root, f)
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as fh:
                        code = fh.read()
                except OSError:
                    continue

                # Detect render(request, "template.html")
                for r_m in re.finditer(r'render\s*\(\s*[^,]+,\s*["\']([^"\']+\.html)["\']', code, re.I):
                    target_tmpl = r_m.group(1)
                    tmpl_basename = os.path.basename(target_tmpl)
                    matched_tmpl = next((n for n in g.find_nodes(kind=NODE_TEMPLATE) if tmpl_basename in n.name), None)
                    if matched_tmpl:
                        # Find python view/class in this file
                        caller_node = next((n for n in g.find_nodes(file_path=rel_path) if n.kind in (NODE_CLASS, NODE_FUNCTION, NODE_METHOD)), None)
                        if caller_node:
                            g.add_edge(caller_node.id, matched_tmpl.id, EDGE_RENDERS)

# Alias for external API convenience
KnowledgeGraph = RepositoryKnowledgeGraph
