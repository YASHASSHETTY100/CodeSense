from __future__ import annotations
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.models.models import Project, UserProjectAccess, User
from app.api.deps import current_user
from app.auth.security import encrypt_credential
from app.ingestion.orchestrator import check_and_mark_stale

router = APIRouter(prefix="/projects", tags=["projects"])


class CreateProject(BaseModel):
    name: str
    repo_url: str
    provider: str = "github"
    default_branch: str = ""  # empty means auto-detect repository's default branch
    credential: str = ""  # PAT/token, stored encrypted


def _safe_health(json_str: str | None) -> dict:
    try:
        return json.loads(json_str or "{}")
    except Exception:
        return {}


def _visible(db: Session, u: User):
    if u.role == "admin":
        return db.query(Project).all()
    ids = [r.project_id for r in db.query(UserProjectAccess).filter(
        UserProjectAccess.user_id == u.id).all()]
    return db.query(Project).filter(Project.id.in_(ids)).all() if ids else []


@router.get("")
def list_projects(u: User = Depends(current_user), db: Session = Depends(get_db)):
    return [
        {
            "id": p.id,
            "name": p.name,
            "repo_url": p.repo_url,
            "provider": p.repo_provider,
            "status": p.ingestion_status,
            "stage": p.ingestion_status.upper(),
            "progress": p.ingestion_progress,
            "message": p.ingestion_message,
            "error": p.ingestion_error or "",
            "configured_branch": p.configured_branch or "",
            "detected_branch": p.detected_branch or "",
            "default_branch": p.default_branch or "",
            "branch": p.default_branch or p.detected_branch or p.configured_branch or "",
            "analyzed_commit_sha": p.analyzed_commit_sha or "",
            "is_stale": bool(p.is_stale),
            "analysis_health": _safe_health(p.analysis_health_json),
            "last_synced": str(p.last_synced_at) if p.last_synced_at else None,
        }
        for p in _visible(db, u)
    ]


@router.post("")
def create_project(b: CreateProject, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if b.provider not in ("github", "gitlab"):
        raise HTTPException(400, "provider must be github|gitlab")
    configured = (b.default_branch or "").strip()
    p = Project(
        name=b.name.strip(),
        repo_url=b.repo_url.strip(),
        repo_provider=b.provider,
        configured_branch=configured,
        default_branch=configured,
        detected_branch="",
        auth_credential_ref=encrypt_credential(b.credential or ""),
        ingestion_status="pending",
        ingestion_progress=0,
        ingestion_message="Initializing repository connection...",
        ingestion_error="",
        analyzed_commit_sha="",
        analysis_health_json="{}",
        is_stale=0,
    )
    db.add(p)
    db.flush()
    db.add(UserProjectAccess(user_id=u.id, project_id=p.id, access_level="owner"))
    db.commit()

    from worker.tasks import enqueue_ingest
    try:
        enqueue_ingest(p.id)
    except Exception as e:
        p.ingestion_status = "failed"
        p.ingestion_progress = 0
        p.ingestion_message = f"Connection failed: {e}"
        p.ingestion_error = str(e)
        db.add(p)
        db.commit()

    # Refresh instance to reflect current DB status
    db.refresh(p)
    return {
        "id": p.id,
        "status": p.ingestion_status,
        "stage": p.ingestion_status.upper(),
        "branch": p.default_branch or p.detected_branch or p.configured_branch or "",
        "message": p.ingestion_message,
        "error": p.ingestion_error or "",
        "analyzed_commit_sha": p.analyzed_commit_sha or "",
        "is_stale": bool(p.is_stale),
        "analysis_health": _safe_health(p.analysis_health_json),
    }


@router.get("/{pid}")
def get_project(pid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    from app.api.deps import require_project_access
    require_project_access(pid, u, db)
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(404, "not found")
    return {
        "id": p.id,
        "name": p.name,
        "repo_url": p.repo_url,
        "provider": p.repo_provider,
        "status": p.ingestion_status,
        "stage": p.ingestion_status.upper(),
        "progress": p.ingestion_progress,
        "message": p.ingestion_message,
        "error": p.ingestion_error or "",
        "configured_branch": p.configured_branch or "",
        "detected_branch": p.detected_branch or "",
        "default_branch": p.default_branch or "",
        "branch": p.default_branch or p.detected_branch or p.configured_branch or "",
        "analyzed_commit_sha": p.analyzed_commit_sha or "",
        "is_stale": bool(p.is_stale),
        "analysis_health": _safe_health(p.analysis_health_json),
        "last_synced": str(p.last_synced_at) if p.last_synced_at else None,
    }


@router.get("/{pid}/ingestion-status")
def ingestion_status(pid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    from app.api.deps import require_project_access
    require_project_access(pid, u, db)
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(404, "not found")
    return {
        "status": p.ingestion_status,
        "stage": p.ingestion_status.upper(),
        "progress": p.ingestion_progress,
        "message": p.ingestion_message,
        "error": p.ingestion_error or "",
        "configured_branch": p.configured_branch or "",
        "detected_branch": p.detected_branch or "",
        "default_branch": p.default_branch or "",
        "branch": p.default_branch or p.detected_branch or p.configured_branch or "",
        "analyzed_commit_sha": p.analyzed_commit_sha or "",
        "is_stale": bool(p.is_stale),
        "analysis_health": _safe_health(p.analysis_health_json),
    }


@router.get("/{pid}/freshness")
def check_freshness(pid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    from app.api.deps import require_project_access
    require_project_access(pid, u, db)
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(404, "not found")
    return check_and_mark_stale(db, p)


@router.get("/{pid}/health-metrics")
def health_metrics(pid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    from app.api.deps import require_project_access
    require_project_access(pid, u, db)
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(404, "not found")
    return _safe_health(p.analysis_health_json)


@router.post("/{pid}/resync")
def resync(pid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    from app.api.deps import require_project_access
    require_project_access(pid, u, db, "contributor")
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(404, "not found")

    p.ingestion_status = "pending"
    p.ingestion_progress = 0
    p.ingestion_message = "Resync queued"
    p.ingestion_error = ""
    p.is_stale = 0
    db.add(p)
    db.commit()

    from worker.tasks import enqueue_ingest
    try:
        enqueue_ingest(pid)
    except Exception as e:
        p.ingestion_status = "failed"
        p.ingestion_progress = 0
        p.ingestion_message = f"Resync failed: {e}"
        p.ingestion_error = str(e)
        db.add(p)
        db.commit()

    db.refresh(p)
    return {
        "queued": True,
        "status": p.ingestion_status,
        "stage": p.ingestion_status.upper(),
        "message": p.ingestion_message,
        "error": p.ingestion_error or "",
        "is_stale": bool(p.is_stale),
    }
