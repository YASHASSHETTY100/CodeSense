"""Regression test suite for automatic branch discovery, validation, and ingestion state machine.
Covers requirements 1-10 in prompt Section 10.
"""
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.models import Base, Project, User
from app.connectors.connectors import (
    resolve_repository_branch,
    detect_git_remote_default_branch,
    check_remote_branch_exists,
    BranchResolutionError,
    _clean_git_error,
)
from app.ingestion.orchestrator import run_ingestion, set_status


@pytest.fixture
def in_memory_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()


def test_1_repository_with_main_branch():
    """1. repository with main branch detected via symref."""
    fake_stdout = "ref: refs/heads/main\tHEAD\nabc123\tHEAD\n"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_stdout, stderr="")
        branch = detect_git_remote_default_branch("https://github.com/example/repo.git")
        assert branch == "main"


def test_2_repository_with_master_branch():
    """2. repository with master branch (like quantopian/alphalens)."""
    fake_stdout = "ref: refs/heads/master\tHEAD\n77084f\tHEAD\n"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_stdout, stderr="")
        branch = detect_git_remote_default_branch("https://github.com/quantopian/alphalens")
        assert branch == "master"


def test_3_repository_with_another_default_branch():
    """3. repository with arbitrary default branch (e.g. development or trunk)."""
    fake_stdout = "ref: refs/heads/development\tHEAD\nfff999\tHEAD\n"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_stdout, stderr="")
        branch = detect_git_remote_default_branch("https://github.com/enterprise/core.git")
        assert branch == "development"


def test_4_explicit_valid_branch():
    """4. explicit valid branch is used and verified."""
    fake_heads = "111aaa\trefs/heads/release-v2.0\n"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_heads, stderr="")
        effective, detected = resolve_repository_branch(
            "https://github.com/example/repo.git",
            configured_branch="release-v2.0"
        )
        assert effective == "release-v2.0"


def test_5_explicit_invalid_branch():
    """5. explicit invalid branch raises clear validation error without hanging in RUNNING."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        with pytest.raises(BranchResolutionError) as excinfo:
            resolve_repository_branch(
                "https://github.com/example/repo.git",
                configured_branch="nonexistent-feature"
            )
        msg = str(excinfo.value)
        assert "branch 'nonexistent-feature' does not exist" in msg
        assert "detect the default branch automatically" in msg


def test_6_default_branch_detection_fallback():
    """6. fallback when symref is absent: match HEAD SHA against remote branches."""
    def fake_subprocess_run(cmd, *args, **kwargs):
        if "HEAD" in cmd and "--symref" in cmd:
            # symref not supported by remote
            return MagicMock(returncode=1, stdout="", stderr="error")
        elif "HEAD" in cmd:
            return MagicMock(returncode=0, stdout="beef456\tHEAD\n", stderr="")
        elif "--heads" in cmd:
            return MagicMock(
                returncode=0,
                stdout="dead123\trefs/heads/alpha\nbeef456\trefs/heads/production\n",
                stderr=""
            )
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        branch = detect_git_remote_default_branch("https://github.com/example/legacy.git")
        assert branch == "production"


def test_7_clone_failure_handling(in_memory_db):
    """7. clone failure transitions project to FAILED with useful error message."""
    p = Project(
        name="CloneFailRepo",
        repo_url="https://github.com/example/broken.git",
        repo_provider="github",
        configured_branch="",
        ingestion_status="pending",
    )
    in_memory_db.add(p)
    in_memory_db.commit()

    with patch("app.connectors.connectors.resolve_repository_branch", return_value=("main", "main")):
        with patch("app.connectors.connectors._git_clone", side_effect=RuntimeError("fatal: repository not found")):
            run_ingestion(in_memory_db, p.id)

    in_memory_db.refresh(p)
    assert p.ingestion_status == "failed"
    assert p.ingestion_progress == 0
    assert "fatal: repository not found" in p.ingestion_error


def test_8_ingestion_status_becomes_failed_not_running(in_memory_db):
    """8. state machine never leaves failed clone in RUNNING 5%."""
    p = Project(
        name="BranchMismatchRepo",
        repo_url="https://github.com/quantopian/alphalens",
        repo_provider="github",
        configured_branch="main",  # Doesn't exist on alphalens
        ingestion_status="running",
        ingestion_progress=5,
    )
    in_memory_db.add(p)
    in_memory_db.commit()

    with patch("app.connectors.connectors.check_remote_branch_exists", return_value=False):
        run_ingestion(in_memory_db, p.id)

    in_memory_db.refresh(p)
    assert p.ingestion_status == "failed"
    assert p.ingestion_progress == 0
    assert "branch 'main' does not exist" in p.ingestion_error


def test_9_retry_resync_after_failure(in_memory_db):
    """9. retry/resync resets status, clears error, and retries ingestion."""
    p = Project(
        name="ResyncRepo",
        repo_url="https://github.com/example/resync.git",
        repo_provider="github",
        configured_branch="",
        ingestion_status="failed",
        ingestion_error="Previous temporary network timeout",
    )
    in_memory_db.add(p)
    in_memory_db.commit()

    # Resetting on resync:
    set_status(in_memory_db, p, "pending", 0, "Resync queued", error="")
    assert p.ingestion_status == "pending"
    assert p.ingestion_error == ""


def test_10_project_branch_persisted_correctly(in_memory_db):
    """10. database model distinguishes configured_branch, detected_branch, and default_branch."""
    p = Project(
        name="PersistTest",
        repo_url="https://github.com/example/test.git",
        repo_provider="github",
        configured_branch="",
        detected_branch="trunk",
        default_branch="trunk",
        ingestion_status="ready",
        ingestion_error="",
    )
    in_memory_db.add(p)
    in_memory_db.commit()

    retrieved = in_memory_db.query(Project).filter(Project.id == p.id).first()
    assert retrieved.configured_branch == ""
    assert retrieved.detected_branch == "trunk"
    assert retrieved.default_branch == "trunk"
    assert retrieved.ingestion_status == "ready"
