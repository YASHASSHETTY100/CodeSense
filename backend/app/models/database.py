from __future__ import annotations
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.models.models import Base

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


from sqlalchemy import text


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    # Safe non-destructive column migration for SQLite
    try:
        with engine.connect() as conn:
            res = conn.execute(text("PRAGMA table_info(projects)")).fetchall()
            existing_cols = {row[1] for row in res}
            cols_to_add = [
                ("configured_branch", "VARCHAR(128) DEFAULT ''"),
                ("detected_branch", "VARCHAR(128) DEFAULT ''"),
                ("ingestion_error", "TEXT DEFAULT ''"),
                ("analyzed_commit_sha", "VARCHAR(64) DEFAULT ''"),
                ("analysis_health_json", "TEXT DEFAULT '{}'"),
                ("summary_cache", "TEXT DEFAULT ''"),
                ("suggested_questions_cache", "TEXT DEFAULT '[]'"),
                ("is_stale", "INTEGER DEFAULT 0"),
            ]
            for col_name, col_type in cols_to_add:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE projects ADD COLUMN {col_name} {col_type}"))
            conn.commit()
    except Exception:
        pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
