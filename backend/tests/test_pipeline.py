"""Integration: full pipeline on a tiny synthetic repo (offline, no network/LLM)."""
import os, tempfile, json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.models import Base, Project, SourceFile, CodeSymbol, Module, ApiEndpoint, BusinessRule
from app.analysis.structural.pipeline import run_structural_analysis
from app.analysis.functional.pipeline import run_functional_analysis
from app.knowledge_base.pipeline import run_kb_indexing
from app.knowledge_base.retrieval import retrieve
from app.reasoning import summarize_project, answer_functional_question, trace_flow, analyze_enhancement

REPO = {
    "orders/api.py": '''
from fastapi import APIRouter
router = APIRouter()
@router.post("/orders/submit")
def submit_order(order_id: int):
    """Submit an order for approval."""
    if order.status == "approved":
        raise ValueError("approved orders cannot be edited")
    db.session.add(order)
    return {"ok": True}
''',
    "orders/models.py": '''
class Order(Base):
    status = Column(String)
    total = Column(Float)
''',
    "inventory/stock.py": '''
def check_stock(sku: str):
    if stock == 0:
        raise ValueError("out of stock")
    return stock
''',
    "frontend/Cart.jsx": '''
export default function Cart() {
  const res = await fetch('/orders/submit');
  return null;
}
''',
}


def _db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=eng)
    return sessionmaker(bind=eng)()


def _repo():
    d = tempfile.mkdtemp()
    for rel, src in REPO.items():
        fp = os.path.join(d, rel)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        open(fp, "w").write(src)
    return d


def test_full_pipeline():
    db = _db()
    d = _repo()
    p = Project(name="shop", repo_url="https://github.com/acme/shop", repo_provider="github")
    db.add(p)
    db.flush()
    for rel in REPO:
        db.add(SourceFile(project_id=p.id, path=rel, language="python", hash="x"))
    db.commit()
    assert run_structural_analysis(db, p.id, d) >= 5
    stats = run_functional_analysis(db, p.id, d)
    assert stats["modules"] >= 2 and stats["rules"] >= 1
    assert db.query(ApiEndpoint).filter(ApiEndpoint.project_id == p.id).count() >= 1
    assert run_kb_indexing(db, p.id, d) > 5
    hits = retrieve(db, p.id, "how does order submission work", top_k=5)
    assert any("orders" in h["source_ref"] for h in hits), hits
    s = summarize_project(db, p.id)
    assert "orders" in s["summary"].lower()
    q = answer_functional_question(db, p.id, "why can't approved orders be edited?", user_id=0)
    assert q["evidence"], "answer must carry evidence"
    t = trace_flow(db, p.id, "order submission flow", user_id=0)
    assert t["steps"]
    e = analyze_enhancement(db, p.id, "allow editing approved orders", user_id=0)
    assert e["complexity"] in ("Low", "Medium", "High")


def test_isolation():
    db = _db()
    d = _repo()
    a = Project(name="A", repo_url="https://github.com/a/a")
    b = Project(name="B", repo_url="https://github.com/b/b")
    db.add_all([a, b])
    db.flush()
    db.add(SourceFile(project_id=a.id, path="orders/api.py", language="python", hash="x"))
    db.add(SourceFile(project_id=b.id, path="unrelated/other.py", language="python", hash="y"))
    db.commit()
    run_structural_analysis(db, a.id, d)
    run_functional_analysis(db, a.id, d)
    run_kb_indexing(db, a.id, d)
    hits = retrieve(db, b.id, "orders", top_k=5)
    assert hits == [], "project B has no chunks; must never leak A's knowledge"
