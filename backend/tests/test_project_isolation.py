"""Tests for strict multi-project isolation."""
from __future__ import annotations
import os, tempfile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.models import Base, Project, SourceFile, KnowledgeChunk
from app.analysis.structural.pipeline import run_structural_analysis
from app.analysis.functional.pipeline import run_functional_analysis
from app.knowledge_base.pipeline import run_kb_indexing
from app.knowledge_base.retrieval import retrieve
from app.reasoning import answer_functional_question, trace_flow, analyze_enhancement


def _db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=eng)
    return sessionmaker(bind=eng)()


def test_multi_project_isolation_retrieval_and_qa():
    db = _db()

    # Project A: Shop
    dA = tempfile.mkdtemp()
    pA = Project(name="ProjectA_Shop", repo_url="https://github.com/test/shop")
    db.add(pA)
    db.flush()
    filesA = {
        "orders/api.py": "def submit_order(): return {'status': 'submitted'}\n",
        "README.md": "# Shop System\nHandles purchases and orders.\n",
    }
    for rel, c in filesA.items():
        fp = os.path.join(dA, rel)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        open(fp, "w", encoding="utf-8").write(c)
        db.add(SourceFile(project_id=pA.id, path=rel, language="python" if rel.endswith(".py") else "markdown", hash="a"))

    # Project B: Missing Persons
    dB = tempfile.mkdtemp()
    pB = Project(name="ProjectB_MissingPersons", repo_url="https://github.com/test/missing")
    db.add(pB)
    db.flush()
    filesB = {
        "cases/search.py": "def search_missing_persons(name: str): return []\n",
        "README.md": "# Missing Persons Portal\nTracks lost individuals.\n",
    }
    for rel, c in filesB.items():
        fp = os.path.join(dB, rel)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        open(fp, "w", encoding="utf-8").write(c)
        db.add(SourceFile(project_id=pB.id, path=rel, language="python" if rel.endswith(".py") else "markdown", hash="b"))

    db.commit()

    run_structural_analysis(db, pA.id, dA)
    run_functional_analysis(db, pA.id, dA)
    run_kb_indexing(db, pA.id, dA)

    run_structural_analysis(db, pB.id, dB)
    run_functional_analysis(db, pB.id, dB)
    run_kb_indexing(db, pB.id, dB)

    # 1. Project A queries must NEVER retrieve Project B evidence
    hitsA = retrieve(db, pA.id, "submit order", top_k=5)
    assert bool(hitsA)
    for h in hitsA:
        assert "cases/" not in h["source_ref"]
        assert "search_missing_persons" not in h["text"]

    hitsA_cross = retrieve(db, pA.id, "missing persons search", top_k=5)
    # Project A has no missing person content -> must return []
    assert hitsA_cross == []

    # 2. Project B queries must NEVER retrieve Project A evidence
    hitsB = retrieve(db, pB.id, "search missing persons", top_k=5)
    assert bool(hitsB)
    for h in hitsB:
        assert "orders/" not in h["source_ref"]
        assert "submit_order" not in h["text"]

    hitsB_cross = retrieve(db, pB.id, "submit order", top_k=5)
    # Project B has no order content -> must return []
    assert hitsB_cross == []

    # 3. Functional answers must strictly isolate
    ansA_cross = answer_functional_question(db, pA.id, "How does missing persons search work?")
    assert ansA_cross["status"] == "INSUFFICIENT_EVIDENCE"
    assert ansA_cross["evidence"] == []

    ansB_cross = answer_functional_question(db, pB.id, "How does order submission work?")
    assert ansB_cross["status"] == "INSUFFICIENT_EVIDENCE"
    assert ansB_cross["evidence"] == []
