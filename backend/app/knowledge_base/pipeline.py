"""KB indexing: chunk raw code + generated summaries, embed, store."""
from __future__ import annotations
import os, json
from sqlalchemy.orm import Session
from app.config import settings
from app.models.models import SourceFile, CodeSymbol, KnowledgeChunk, Module, ApiEndpoint, BusinessRule
from app.knowledge_base.embeddings import get_embedder
from app.analysis.security import redact_secrets

SUMMARY_CHUNK = 60


def summarize_symbol(kind: str, name: str, sig: str, path: str) -> str:
    if kind == "route":
        return f"API endpoint {name} handled in {path} ({sig})."
    if kind == "model":
        return f"Data entity {name} defined in {path}."
    if kind == "component":
        return f"Frontend component {name} in {path}."
    if kind == "form":
        return f"Form {name} for user input intake defined in {path}."
    if kind == "form_field":
        return f"Form input field {name} in {path}."
    if kind == "ui_label":
        return f"UI label and heading {name} in template {path}."
    if kind == "serializer":
        return f"Serializer schema {name} defined in {path}."
    return f"{kind} {name} in {path} {sig}."



def run_kb_indexing(db: Session, project_id: int, repo_dir: str) -> int:
    files = db.query(SourceFile).filter(SourceFile.project_id == project_id).all()
    symbols = db.query(CodeSymbol).filter(CodeSymbol.project_id == project_id).all()
    db.query(KnowledgeChunk).filter(KnowledgeChunk.project_id == project_id).delete()
    db.commit()
    docs: list[tuple[str, str, str]] = []  # (source_ref, text, type)
    for sf in files:
        fp = os.path.join(repo_dir, sf.path)
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                src = f.read()
        except OSError:
            continue
        if not src.strip():
            continue
        # raw code chunks (120-line windows)
        lines = src.splitlines()
        for i in range(0, len(lines), 120):
            window = "\n".join(lines[i:i + 120])
            if len(window.strip()) < 40:
                continue
            sanitized_window = redact_secrets(window[:6000])
            docs.append((f"{sf.path}#L{i+1}-{i+len(window.splitlines())}",
                         f"File {sf.path} ({sf.language}):\n{sanitized_window}", "raw_code"))
            if len(docs) > 4000:
                break
    file_of = {sf.id: sf for sf in files}
    for s in symbols[:3000]:
        sf = file_of.get(s.source_file_id)
        path = sf.path if sf else "?"
        docs.append((f"{path}:{s.name}:{s.start_line}-{s.end_line}",
                     redact_secrets(summarize_symbol(s.kind, s.name, s.signature, path)), "generated_summary"))
    for m in db.query(Module).filter(Module.project_id == project_id).all():
        docs.append((f"module:{m.name}",
                     redact_secrets(f"Module {m.name}: {m.description} Evidence paths: {m.inferred_from[:1000]}"),
                     "generated_summary"))
    for e in db.query(ApiEndpoint).filter(ApiEndpoint.project_id == project_id).all():
        docs.append((f"endpoint:{e.method} {e.path}",
                     redact_secrets(f"API {e.method} {e.path} auth={e.auth_required} roles={e.roles_allowed}"),
                     "generated_summary"))
    for r in db.query(BusinessRule).filter(BusinessRule.project_id == project_id).all()[:500]:
        docs.append((f"rule:{r.id}", redact_secrets(f"Business rule: {r.description}"), "generated_summary"))

    try:
        from app.domain_vocabulary import get_domain_vocabulary
        vocab = get_domain_vocabulary(db, project_id, repo_dir)
        for cname, c in list(vocab.concepts.items())[:200]:
            alias_str = ", ".join(sorted(c.aliases)[:8])
            field_str = ", ".join(sorted(c.fields)[:8])
            file_str = ", ".join(sorted(c.files)[:4])
            act_str = ", ".join(sorted(c.associated_actions)[:6])
            summary_text = f"Domain concept {c.canonical_name}: aliases [{alias_str}] fields [{field_str}] actions [{act_str}] files [{file_str}]"
            docs.append((f"concept:{c.canonical_name}", redact_secrets(summary_text), "generated_summary"))
    except Exception:
        pass

    emb = get_embedder(settings.EMBEDDING_BACKEND)
    emb.fit([d[1] for d in docs])
    for ref, text, ctype in docs:
        db.add(KnowledgeChunk(project_id=project_id, source_ref=ref, chunk_text=text,
                              embedding_vector=json.dumps(emb.embed(text)), chunk_type=ctype))
    db.commit()
    return len(docs)
