"""Tests for Trace Flow and Enhancement Impact Analysis hardening."""
from __future__ import annotations
import os, tempfile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.models import Base, Project, SourceFile
from app.analysis.structural.pipeline import run_structural_analysis
from app.analysis.functional.pipeline import run_functional_analysis
from app.knowledge_base.pipeline import run_kb_indexing
from app.reasoning import trace_flow, analyze_enhancement


def _db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=eng)
    return sessionmaker(bind=eng)()


def _setup_missing_person_repo(db):
    d = tempfile.mkdtemp()
    p = Project(name="mp_portal", repo_url="https://github.com/ngo/mp-portal")
    db.add(p)
    db.flush()

    files = {
        "app.py": """
import sqlite3

def generate_tracking_code():
    return "TRK-9999"

def notify_new_submission(report_id, tracking_code):
    print("Dispatching intake alert for", report_id)

def run_matching_pipeline(report_id, name):
    print("Executing facial recognition & matching for", report_id)

def report_missing_person_form():
    tracking_code = generate_tracking_code()
    conn = sqlite3.connect("cases.db")
    c = conn.cursor()
    c.execute("INSERT INTO persons (name, tracking_code) VALUES (?, ?)", ("Jane Doe", tracking_code))
    person_id = c.lastrowid
    conn.commit()
    conn.close()

    notify_new_submission(report_id=person_id, tracking_code=tracking_code)
    run_matching_pipeline(report_id=person_id, name="Jane Doe")
    return person_id
""",
        "README.md": """# Missing Persons Intake Portal
Community tracking and report filing system.
""",
    }

    for rel, content in files.items():
        fp = os.path.join(d, rel)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        open(fp, "w", encoding="utf-8").write(content)
        lang = "markdown" if rel.endswith(".md") else "python"
        db.add(SourceFile(project_id=p.id, path=rel, language=lang, hash="h"))

    db.commit()
    run_structural_analysis(db, p.id, d)
    run_functional_analysis(db, p.id, d)
    run_kb_indexing(db, p.id, d)
    return p, d


def test_trace_flow_multi_layer_grounding():
    db = _db()
    p, _ = _setup_missing_person_repo(db)

    res = trace_flow(db, p.id, "How does a missing-person report get submitted?")
    assert res["status"] == "SUCCESS"
    assert len(res["steps"]) >= 2
    assert bool(res["flow"])
    assert bool(res["evidence"])
    assert res["confidence"] in ("High", "Medium")

    stages = [s["stage"] for s in res["steps"]]
    # Must categorize into actual implementation layers
    assert any("Frontend" in st or "Entry" in st for st in stages)
    assert any("Notifications" in st or "Matching" in st or "Backend" in st or "Persistence" in st for st in stages)

    for step in res["steps"]:
        assert "stage" in step
        assert "description" in step
        assert "component" in step
        assert "evidence" in step
        assert "file" in step["evidence"]


def test_trace_flow_unsupported_domain_query():
    db = _db()
    p, _ = _setup_missing_person_repo(db)

    res = trace_flow(db, p.id, "How does purchase order approval work?")
    assert res["status"] == "INSUFFICIENT_EVIDENCE"
    assert res["steps"] == []
    assert res["evidence"] == []
    assert res["confidence"] == "None"


def test_enhancement_analysis_supported_request():
    db = _db()
    p, _ = _setup_missing_person_repo(db)

    req = "Add email notifications to administrators whenever a new missing-person report is submitted."
    res = analyze_enhancement(db, p.id, req)
    assert res["status"] == "SUCCESS"
    assert res["complexity"] in ("Low", "Medium", "High")
    assert bool(res["impacted_areas"])
    assert bool(res["evidence"])
    assert "backend_impact" in res
    assert "frontend_impact" in res
    assert "db_impact" in res
    assert "permission_impact" in res
    assert "notifications" in res
    assert "external_integrations" in res
    assert "needs_dev_validation" in res
    assert len(res["needs_dev_validation"]) >= 3


def test_enhancement_analysis_unsupported_domain_request():
    db = _db()
    p, _ = _setup_missing_person_repo(db)

    req = "Add purchase-order approval functionality."
    res = analyze_enhancement(db, p.id, req)
    assert res["status"] == "INSUFFICIENT_EVIDENCE"
    assert res["evidence"] == []
    assert res["confidence"] == "None"
