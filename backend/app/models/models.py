"""SQLAlchemy models matching spec Section 5 (superset where useful)."""
from __future__ import annotations
import datetime as dt
from sqlalchemy import (Column, Integer, String, Text, DateTime, ForeignKey, JSON,
                        UniqueConstraint)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _now():
    return dt.datetime.utcnow()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), default="")
    password_hash = Column(String(255), default="")
    oauth_id = Column(String(255), default="")
    role = Column(String(32), default="pm")  # admin|pm|ba
    created_at = Column(DateTime, default=_now)


class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    repo_provider = Column(String(32), default="github")
    repo_url = Column(String(1024), nullable=False)
    default_branch = Column(String(128), default="")  # effective branch
    configured_branch = Column(String(128), default="")  # user-specified branch
    detected_branch = Column(String(128), default="")  # auto-detected default branch
    auth_credential_ref = Column(Text, default="")  # encrypted PAT/token
    ingestion_status = Column(String(32), default="pending")  # pending|connecting|authenticating|branch_discovery|cloning|scanning|parsing|domain_analysis|functional_analysis|workflow_analysis|indexing|summary_generation|quality_check|ready|stale|failed
    ingestion_progress = Column(Integer, default=0)
    ingestion_message = Column(Text, default="")
    ingestion_error = Column(Text, default="")  # clean failure details
    analyzed_commit_sha = Column(String(64), default="")  # tracked git commit hash
    analysis_health_json = Column(Text, default="{}")  # analysis health indicators
    summary_cache = Column(Text, default="")  # cached functional summary
    suggested_questions_cache = Column(Text, default="[]")  # cached suggested questions
    is_stale = Column(Integer, default=0)  # 1 if repo changed since last analysis
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)


class UserProjectAccess(Base):
    __tablename__ = "user_project_access"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    access_level = Column(String(32), default="viewer")  # owner|contributor|viewer
    __table_args__ = (UniqueConstraint("user_id", "project_id", name="uq_user_project"),)


class SourceFile(Base):
    __tablename__ = "source_files"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), index=True, nullable=False)
    path = Column(String(1024), nullable=False)
    language = Column(String(64), default="")
    hash = Column(String(64), default="")
    last_parsed_at = Column(DateTime, default=_now)


class CodeSymbol(Base):
    __tablename__ = "code_symbols"
    id = Column(Integer, primary_key=True)
    source_file_id = Column(Integer, ForeignKey("source_files.id"), index=True, nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), index=True, nullable=False)
    kind = Column(String(32), default="function")  # class|function|route|component|model
    name = Column(String(512), default="")
    start_line = Column(Integer, default=0)
    end_line = Column(Integer, default=0)
    signature = Column(Text, default="")
    docstring = Column(Text, default="")


class Module(Base):
    __tablename__ = "modules"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), index=True, nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    inferred_from = Column(Text, default="")


class ApiEndpoint(Base):
    __tablename__ = "api_endpoints"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), index=True, nullable=False)
    method = Column(String(16), default="GET")
    path = Column(String(1024), default="")
    handler_symbol_id = Column(Integer, ForeignKey("code_symbols.id"), nullable=True)
    module_id = Column(Integer, ForeignKey("modules.id"), nullable=True)
    request_shape = Column(Text, default="")
    response_shape = Column(Text, default="")
    auth_required = Column(String(16), default="unknown")
    roles_allowed = Column(Text, default="")  # JSON list as text


class DataEntity(Base):
    __tablename__ = "data_entities"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), index=True, nullable=False)
    name = Column(String(255), nullable=False)
    source_symbol_id = Column(Integer, ForeignKey("code_symbols.id"), nullable=True)
    fields_json = Column(Text, default="[]")
    relations_json = Column(Text, default="[]")


class BusinessRule(Base):
    __tablename__ = "business_rules"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), index=True, nullable=False)
    description = Column(Text, default="")
    source_symbol_id = Column(Integer, ForeignKey("code_symbols.id"), nullable=True)
    module_id = Column(Integer, ForeignKey("modules.id"), nullable=True)
    trigger_condition = Column(Text, default="")


class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), index=True, nullable=False)
    name = Column(String(255), nullable=False)
    permissions_json = Column(Text, default="[]")


class Relation(Base):
    __tablename__ = "relations"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), index=True, nullable=False)
    from_type = Column(String(64), default="")
    from_id = Column(Integer, default=0)
    to_type = Column(String(64), default="")
    to_id = Column(Integer, default=0)
    relation_kind = Column(String(32), default="calls")  # calls|reads|writes|validates|triggers|belongs_to_module


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), index=True, nullable=False)
    source_ref = Column(String(1024), default="")
    chunk_text = Column(Text, default="")
    embedding_vector = Column(Text, default="")  # JSON list[float] (portable across sqlite/pg)
    chunk_type = Column(String(32), default="raw_code")  # raw_code|generated_summary


class QueryLog(Base):
    __tablename__ = "query_log"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    question = Column(Text, default="")
    answer = Column(Text, default="")
    evidence_refs_json = Column(Text, default="[]")
    created_at = Column(DateTime, default=_now)


class GeneratedDocument(Base):
    __tablename__ = "generated_documents"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), index=True, nullable=False)
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    scope = Column(String(512), default="")
    format = Column(String(16), default="docx")
    file_ref = Column(String(1024), default="")
    created_at = Column(DateTime, default=_now)
