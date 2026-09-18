"""Module inference heuristic (documented): top-level dir (or first 2 path parts
for src/ nesting) + route-prefix grouping. Stable, explainable, language-agnostic."""
from __future__ import annotations
import os
from sqlalchemy.orm import Session
from app.models.models import SourceFile, Module, Project


def infer_module_name(rel_path: str) -> str:
    parts = [p for p in rel_path.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts:
        return "root"
    # drop filename
    dirs = parts[:-1] if len(parts) > 1 else []
    if not dirs:
        return "root"
    # skip generic roots
    while dirs and dirs[0].lower() in ("src", "app", "apps", "backend", "frontend", "lib", "pkg"):
        dirs = dirs[1:]
    if not dirs:
        return "root"
    name = "/".join(dirs[:2]) if len(dirs) >= 2 else dirs[0]
    return name.lower().replace("_", "-")


def run_module_inference(db: Session, project_id: int) -> dict[str, int]:
    files = db.query(SourceFile).filter(SourceFile.project_id == project_id).all()
    groups: dict[str, list[str]] = {}
    for f in files:
        groups.setdefault(infer_module_name(f.path), []).append(f.path)
    db.query(Module).filter(Module.project_id == project_id).delete()
    db.commit()
    mapping: dict[str, int] = {}
    for name in sorted(groups):
        m = Module(project_id=project_id, name=name,
                   description=f"Files under {name} ({len(groups[name])} files).",
                   inferred_from=";".join(sorted(groups[name])[:50]))
        db.add(m)
        db.flush()
        mapping[name] = m.id
    db.commit()
    return mapping
