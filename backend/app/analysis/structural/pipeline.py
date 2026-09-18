"""Persist structural symbols for every tracked SourceFile."""
from __future__ import annotations
import os
from sqlalchemy.orm import Session
from app.models.models import SourceFile, CodeSymbol, Project
from .languages import detect_language
from .parsers import parse_source


def run_structural_analysis(db: Session, project_id: int, repo_dir: str) -> int:
    files = db.query(SourceFile).filter(SourceFile.project_id == project_id).all()
    # wipe previous symbols for re-runs
    sym_ids = [s.id for s in db.query(CodeSymbol.id).filter(CodeSymbol.project_id == project_id).all()]
    if sym_ids:
        db.query(CodeSymbol).filter(CodeSymbol.id.in_(sym_ids)).delete(synchronize_session=False)
        db.commit()
    total = 0
    for sf in files:
        fp = os.path.join(repo_dir, sf.path)
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                src = f.read()
        except OSError:
            continue
        lang = sf.language or detect_language(sf.path)
        for sym in parse_source(src, lang):
            db.add(CodeSymbol(source_file_id=sf.id, project_id=project_id, kind=sym.kind,
                              name=sym.name[:500], start_line=sym.start_line, end_line=sym.end_line,
                              signature=sym.signature[:2000], docstring=sym.docstring[:2000]))
            total += 1
    db.commit()
    return total
