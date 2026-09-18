"""Tests for Phase K: Automation, Orchestration, Intelligent Pipeline & Health."""
import os, json, tempfile, shutil
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.models import Base, Project, SourceFile, User, UserProjectAccess, CodeSymbol, KnowledgeChunk
from app.ingestion.orchestrator import (
    run_ingestion, set_status, check_and_mark_stale,
    compute_analysis_health, get_repo_commit_sha
)
from app.analysis.query_intent import analyze_query
from app.reasoning.reasoning import summarize_project, generate_suggested_questions, answer_functional_question


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_1_pipeline_status_progression(test_db):
    """Verify state machine transitions and normalization across Phase K states."""
    p = Project(
        name="Test Pipeline",
        repo_url="https://github.com/example/pipeline",
        ingestion_status="pending",
        ingestion_progress=0
    )
    test_db.add(p)
    test_db.commit()

    states = [
        ("connecting", 5),
        ("authenticating", 10),
        ("branch_discovery", 18),
        ("cloning", 28),
        ("scanning", 38),
        ("parsing", 50),
        ("domain_analysis", 62),
        ("functional_analysis", 72),
        ("workflow_analysis", 80),
        ("indexing", 88),
        ("summary_generation", 94),
        ("quality_check", 98),
        ("ready", 100),
    ]

    for st, prog in states:
        set_status(test_db, p, st, prog, f"In state {st}")
        assert p.ingestion_status == st
        assert p.ingestion_progress == prog

    # Verify failure state
    set_status(test_db, p, "failed", 0, "Failed at step", error="Network timeout")
    assert p.ingestion_status == "failed"
    assert p.ingestion_error == "Network timeout"
    assert p.ingestion_progress == 0


def test_2_analysis_health_computation(test_db):
    """Verify analysis health indicators calculation."""
    p = Project(name="Health Test", repo_url="https://github.com/example/health", ingestion_status="ready")
    test_db.add(p)
    test_db.commit()

    health = compute_analysis_health(test_db, p.id, n_analyzed=12, n_skipped=3, n_unsupported=1)
    assert health["files_analyzed"] == 12
    assert health["files_skipped"] == 3
    assert health["unsupported_files"] == 1
    assert "status" in health
    assert "index_completeness" in health
    assert health["security_findings"] == 0


def test_3_version_tracking_and_stale_detection(test_db, tmp_path):
    """Verify version tracking and transition to STALE when commit changes."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    git_dir = repo_dir / ".git"
    git_dir.mkdir()
    head_file = git_dir / "HEAD"
    head_file.write_text("0123456789abcdef0123456789abcdef01234567")

    p = Project(
        id=999,
        name="Stale Test",
        repo_url="https://github.com/example/stale",
        ingestion_status="ready",
        analyzed_commit_sha="0123456789abcdef0123456789abcdef01234567",
        is_stale=0
    )
    test_db.add(p)
    test_db.commit()

    import app.ingestion.orchestrator as orch
    orig_pdir = orch.project_dir
    orch.project_dir = lambda pid: str(repo_dir)

    try:
        # Commit unchanged -> not stale
        res = check_and_mark_stale(test_db, p)
        assert res["is_stale"] is False
        assert p.is_stale == 0

        # Change commit in repo -> now stale
        head_file.write_text("fedcba9876543210fedcba9876543210fedcba98")
        res2 = check_and_mark_stale(test_db, p)
        assert res2["is_stale"] is True
        assert p.is_stale == 1
        assert p.ingestion_status == "stale"
    finally:
        orch.project_dir = orig_pdir


def test_4_multi_intent_query_planning():
    """Verify multi-intent extraction and query plan generation."""
    q = "Who can approve an order and what happens after approval?"
    qi = analyze_query(q)

    # Should detect roles/permissions intent and workflow intent
    assert any(i in qi.intents for i in ["USER_ROLE", "PERMISSION_AUTH"])
    assert any(i in qi.intents for i in ["WORKFLOW", "HOW_IT_WORKS"])
    assert "order" in qi.entities or "order" in qi.query_plan.get("target_entities", [])
    assert "approve" in qi.actions or "approve" in qi.query_plan.get("target_actions", [])


def test_5_contradiction_detection_in_reasoning(test_db):
    """Verify that contradictory evidence produces an explicit inconsistency notice."""
    p = Project(id=888, name="Contradiction Test", repo_url="https://github.com/example/contradict", ingestion_status="ready")
    test_db.add(p)

    sf1 = SourceFile(project_id=888, path="app/security.py", hash="h1")
    sf2 = SourceFile(project_id=888, path="app/routes.py", hash="h2")
    test_db.add_all([sf1, sf2])
    test_db.commit()

    # Conflicting chunks: one enforces admin only, one allows public unauthenticated access
    c1 = KnowledgeChunk(
        project_id=888,
        source_ref="app/security.py#10",
        chunk_text="def approve_record(user): if not user.is_admin: raise PermissionDenied('admin required only')",
        chunk_type="raw_code",
        embedding_vector="[0.1, 0.2, 0.3]"
    )
    c2 = KnowledgeChunk(
        project_id=888,
        source_ref="app/routes.py#20",
        chunk_text="@router.post('/approve') @permission_classes([AllowAny]) def approve_view(): pass # public access",
        chunk_type="raw_code",
        embedding_vector="[0.1, 0.2, 0.3]"
    )
    test_db.add_all([c1, c2])
    test_db.commit()

    from app.reasoning.reasoning import _build_functional_answer
    ev = [
        {"source_ref": c1.source_ref, "text": c1.chunk_text},
        {"source_ref": c2.source_ref, "text": c2.chunk_text},
    ]
    ans = _build_functional_answer("Can anyone approve records?", ev, ev, 0)
    assert "Repository evidence is inconsistent." in ans["current_behaviour"]
    assert "app/security.py" in ans["current_behaviour"]
    assert "app/routes.py" in ans["current_behaviour"]


def test_6_automatic_summary_and_questions_caching(test_db):
    """Verify that cached summary and suggested questions are used when present."""
    p = Project(
        id=777,
        name="Cached Project",
        repo_url="https://github.com/example/cache",
        ingestion_status="ready",
        summary_cache=json.dumps({"summary": "# Cached Summary\nFast response", "facts": {}, "evidence": []}),
        suggested_questions_cache=json.dumps([
            "Question 1?", "Question 2?", "Question 3?", "Question 4?", "Question 5?"
        ])
    )
    test_db.add(p)
    test_db.commit()

    s = summarize_project(test_db, 777)
    assert s["summary"] == "# Cached Summary\nFast response"

    qs = generate_suggested_questions(test_db, 777)
    assert len(qs) == 5
    assert qs[0] == "Question 1?"


def test_7_project_isolation_across_health_and_qa(test_db):
    """Verify that project data and health metrics remain strictly isolated."""
    p1 = Project(id=101, name="Project A", repo_url="https://github.com/a/a", ingestion_status="ready")
    p2 = Project(id=102, name="Project B", repo_url="https://github.com/b/b", ingestion_status="ready")
    test_db.add_all([p1, p2])

    test_db.add(SourceFile(project_id=101, path="a.py", hash="h1"))
    test_db.add(SourceFile(project_id=102, path="b.py", hash="h2"))
    test_db.add(SourceFile(project_id=102, path="b2.py", hash="h3"))
    test_db.commit()

    h1 = compute_analysis_health(test_db, 101, n_analyzed=1, n_skipped=0, n_unsupported=0)
    h2 = compute_analysis_health(test_db, 102, n_analyzed=2, n_skipped=0, n_unsupported=0)

    assert h1["files_analyzed"] == 1
    assert h2["files_analyzed"] == 2
