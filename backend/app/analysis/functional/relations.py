"""Relation graph: endpoint->handler, symbol calls, frontend->API, model reads/writes."""
from __future__ import annotations
import os, re, json
from sqlalchemy.orm import Session
from app.models.models import CodeSymbol, SourceFile, ApiEndpoint, Relation
from app.analysis.functional.modules import infer_module_name

CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
FETCH_RE = re.compile(r"""(?:fetch\(\s*['"`]([^'"`]+)['"`]|axios\.(?:get|post|put|patch|delete)\(\s*['"`]([^'"`]+)['"`]|['"`](/(?:api|v\d)[^'"`]*|https?://[^'"`]+)['"`])""")
ROUTE_SYM_RE = re.compile(r"^(GET|POST|PUT|PATCH|DELETE|DJANGO)\s+(\S+)")


def _file_text(repo_dir: str, rel: str) -> str:
    try:
        with open(os.path.join(repo_dir, rel), "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return ""


def run_relation_build(db: Session, project_id: int, repo_dir: str,
                       module_map: dict[str, int]) -> int:
    symbols = db.query(CodeSymbol).filter(CodeSymbol.project_id == project_id).all()
    files = {sf.id: sf for sf in db.query(SourceFile).filter(SourceFile.project_id == project_id).all()}
    db.query(Relation).filter(Relation.project_id == project_id).delete()
    db.query(ApiEndpoint).filter(ApiEndpoint.project_id == project_id).delete()
    db.commit()
    by_name: dict[str, list[CodeSymbol]] = {}
    for s in symbols:
        by_name.setdefault(s.name.split(":")[-1].strip().split()[-1], []).append(s)
    n = 0

    def add(ft, fid, tt, tid, kind):
        nonlocal n
        db.add(Relation(project_id=project_id, from_type=ft, from_id=fid,
                        to_type=tt, to_id=tid, relation_kind=kind))
        n += 1

    # 1) endpoints from route symbols
    for s in symbols:
        if s.kind != "route":
            continue
        m = ROUTE_SYM_RE.match(s.name)
        if not m:
            continue
        method, path = m.group(1), m.group(2)
        mod_id = module_map.get(infer_module_name(files[s.source_file_id].path))
        ep = ApiEndpoint(project_id=project_id, method=method, path=path,
                         handler_symbol_id=s.id, module_id=mod_id,
                         auth_required="unknown", roles_allowed="[]")
        db.add(ep)
        db.flush()
        add("endpoint", ep.id, "symbol", s.id, "calls")
    # 2) calls: function body mentions another symbol name
    for s in symbols:
        if s.kind not in ("function", "component", "class", "route"):
            continue
        sf = files.get(s.source_file_id)
        if not sf:
            continue
        text = _file_text(repo_dir, sf.path)
        for callee in set(CALL_RE.findall(text)):
            for target in by_name.get(callee, [])[:3]:
                if target.id != s.id:
                    add("symbol", s.id, "symbol", target.id, "calls")
        # 3) frontend -> API
        for url in set(u for tup in FETCH_RE.findall(text) for u in tup if u):
            ep = db.query(ApiEndpoint).filter(
                ApiEndpoint.project_id == project_id,
                ApiEndpoint.path == url.split("?")[0].split("http")[-1]).first()
            if ep:
                add("symbol", s.id, "endpoint", ep.id, "calls")
        # 4) DB reads/writes mentions
        for kw, kind in (("SELECT", "reads"), ("INSERT", "writes"), ("UPDATE", "writes"),
                         ("DELETE", "writes"), ("objects.", "reads"), (".save()", "writes"),
                         ("session.add", "writes"), ("db.session", "writes")):
            if kw in text:
                add("symbol", s.id, "entity", 0, kind)
                break
        if n > 20000:  # safety cap
            break
    # 5) symbol -> module membership
    for s in symbols:
        sf = files.get(s.source_file_id)
        if sf and (mid := module_map.get(infer_module_name(sf.path))):
            add("symbol", s.id, "module", mid, "belongs_to_module")
    db.commit()
    return n
