from __future__ import annotations
from worker.celery_app import celery_app
from app.models.database import SessionLocal
from app.models.models import Project
from app.ingestion.orchestrator import run_ingestion, set_status


@celery_app.task(name="ingest_project", bind=True, max_retries=1)
def ingest_project(self, project_id: int):
    db = SessionLocal()
    try:
        run_ingestion(db, project_id)
    except Exception as e:  # noqa: BLE001
        try:
            p = db.query(Project).filter(Project.id == project_id).one_or_none()
            if p:
                set_status(db, p, "failed", 0, str(e)[-1000:], error=str(e))
        except Exception:
            pass
        raise
    finally:
        db.close()


def enqueue_ingest(project_id: int) -> None:
    """Run inline when Celery eager / Redis unavailable, else queue."""
    import app.config as cfg
    redis_up = False
    if not cfg.settings.CELERY_EAGER:
        try:
            import socket
            s = socket.create_connection(("127.0.0.1", 6379), timeout=0.3)
            s.close()
            redis_up = True
        except Exception:
            redis_up = False

    if redis_up and not cfg.settings.CELERY_EAGER:
        try:
            ingest_project.delay(project_id)
            return
        except Exception:
            pass

    # Synchronous execution when Redis unavailable or Celery eager
    db = SessionLocal()
    try:
        run_ingestion(db, project_id)
    except Exception as e:
        p = db.query(Project).filter(Project.id == project_id).one_or_none()
        if p:
            set_status(db, p, "failed", 0, f"Ingestion failed: {e}", error=str(e))
    finally:
        db.close()
