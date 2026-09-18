from __future__ import annotations
import os
import time
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.config import settings
from app.models.database import get_db
from app.models.models import Project, GeneratedDocument
from app.api.deps import current_user, require_project_access

router = APIRouter(prefix="/projects/{pid}", tags=["qa"])

# naive in-memory rate limit (per process): 30 ask/min per user-project
_CALLS: dict[str, list[float]] = {}
def _ratelimit(key: str, limit: int = 30, window: int = 60):
    now = time.time()
    arr = [t for t in _CALLS.get(key, []) if now - t < window]
    if len(arr) >= limit:
        raise HTTPException(429, "rate limit exceeded, try again shortly")
    arr.append(now)
    _CALLS[key] = arr


class AskBody(BaseModel):
    question: str
    history: list[dict] = []


class EnhancementBody(BaseModel):
    request: str


class DocBody(BaseModel):
    scope: str
    format: str = "docx"


@router.get("/summary")
def summary(pid: int, u=Depends(current_user), db: Session = Depends(get_db)):
    require_project_access(pid, u, db)
    from app.reasoning import summarize_project
    return summarize_project(db, pid)


@router.get("/suggested-questions")
def suggested_questions(pid: int, u=Depends(current_user), db: Session = Depends(get_db)):
    require_project_access(pid, u, db)
    from app.reasoning import generate_suggested_questions
    return {"questions": generate_suggested_questions(db, pid)}


@router.post("/ask")
def ask(pid: int, b: AskBody, u=Depends(current_user), db: Session = Depends(get_db)):
    require_project_access(pid, u, db)
    _ratelimit(f"ask:{u.id}:{pid}")
    from app.reasoning import answer_functional_question
    return answer_functional_question(db, pid, b.question, u.id, history=b.history)


@router.post("/investigate")
def investigate(pid: int, b: AskBody, u=Depends(current_user), db: Session = Depends(get_db)):
    """Agentic investigation loop: navigates the Application Intelligence Model,
    collects multi-source evidence, verifies claims, and synthesizes grounded answers."""
    require_project_access(pid, u, db)
    _ratelimit(f"inv:{u.id}:{pid}")
    from app.reasoning import investigate_question
    return investigate_question(db, pid, b.question, u.id, history=b.history)


@router.post("/trace-flow")
def trace(pid: int, b: AskBody, u=Depends(current_user), db: Session = Depends(get_db)):
    require_project_access(pid, u, db)
    _ratelimit(f"trace:{u.id}:{pid}")
    from app.reasoning import trace_flow
    return trace_flow(db, pid, b.question, u.id)


@router.post("/analyze-enhancement")
def enhancement(pid: int, b: EnhancementBody, u=Depends(current_user), db: Session = Depends(get_db)):
    require_project_access(pid, u, db)
    _ratelimit(f"enh:{u.id}:{pid}", limit=15)
    from app.reasoning import analyze_enhancement
    return analyze_enhancement(db, pid, b.request, u.id)


@router.post("/generate-doc")
def gendoc(pid: int, b: DocBody, u=Depends(current_user), db: Session = Depends(get_db)):
    require_project_access(pid, u, db)
    if b.format not in ("docx", "pdf"):
        raise HTTPException(400, "format must be docx|pdf")
    p = db.query(Project).filter(Project.id == pid).first()
    doc = GeneratedDocument(project_id=pid, requested_by=u.id, scope=b.scope, format=b.format, file_ref="")
    db.add(doc)
    db.flush()
    from app.docgen.docgen import generate_doc
    path = generate_doc(db, pid, p.name, b.scope, b.format, u.id, doc.id)
    doc.file_ref = path
    db.add(doc)
    db.commit()
    return {"download_url": f"/projects/{pid}/docs/{doc.id}/download", "doc_id": doc.id}


@router.post("/generate-full-docs")
def generate_full_docs(pid: int, u=Depends(current_user), db: Session = Depends(get_db)):
    """Generate complete functional documentation bundle for all discovered modules."""
    require_project_access(pid, u, db)
    p = db.query(Project).filter(Project.id == pid).first()
    from app.docgen.docgen import generate_doc
    
    # 1. Generate DOCX
    docx_doc = GeneratedDocument(project_id=pid, requested_by=u.id, scope="Complete Functional Specification", format="docx", file_ref="")
    db.add(docx_doc)
    db.flush()
    docx_path = generate_doc(db, pid, p.name, "full", "docx", u.id, docx_doc.id)
    docx_doc.file_ref = docx_path
    db.add(docx_doc)

    # 2. Generate PDF
    pdf_doc = GeneratedDocument(project_id=pid, requested_by=u.id, scope="Complete Functional Specification", format="pdf", file_ref="")
    db.add(pdf_doc)
    db.flush()
    pdf_path = generate_doc(db, pid, p.name, "full", "pdf", u.id, pdf_doc.id)
    pdf_doc.file_ref = pdf_path
    db.add(pdf_doc)

    db.commit()
    return {
        "status": "SUCCESS",
        "message": "Complete functional documentation generated successfully",
        "docx": {"doc_id": docx_doc.id, "download_url": f"/projects/{pid}/docs/{docx_doc.id}/download"},
        "pdf": {"doc_id": pdf_doc.id, "download_url": f"/projects/{pid}/docs/{pdf_doc.id}/download"},
    }


@router.get("/docs/{doc_id}/download")
def download(pid: int, doc_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    require_project_access(pid, u, db)
    from fastapi.responses import FileResponse
    doc = db.query(GeneratedDocument).filter(
        GeneratedDocument.id == doc_id, GeneratedDocument.project_id == pid).first()
    if not doc or not doc.file_ref:
        raise HTTPException(404, "Document not found")

    real_path = os.path.abspath(doc.file_ref)
    doc_dir = os.path.abspath(settings.DOC_OUTPUT_DIR)
    # Prevent path traversal attacks and verify file exists on disk
    if not real_path.startswith(doc_dir) or not os.path.isfile(real_path):
        raise HTTPException(404, "Document file not found on disk")

    filename = f"{doc.scope}.{doc.format}"
    mt = "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if doc.format == "docx" else "application/pdf"
    return FileResponse(
        real_path,
        media_type=mt,
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
