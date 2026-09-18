"""DB entity extraction: SQLAlchemy/Django/Prisma/TypeORM models + SQL CREATE TABLE."""
from __future__ import annotations
import os, re, json
from sqlalchemy.orm import Session
from app.models.models import CodeSymbol, SourceFile, DataEntity

APP_FIELD_RE = re.compile(
    r"^\s*(\w+)\s*(?::\s*[^=]+)?\s*=\s*(?:models\.|Column\(|Field\(|mapped_column\(|serializers\.|CharField|IntegerField|FloatField|BooleanField|DateTimeField|ForeignKey|relationship)"
)
SQL_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:[`\"']?(\w+)[`\"']?\.)?[`\"']?(\w+)[`\"']?\s*\(([\s\S]*?)\)(?:;|\s*$)",
    re.IGNORECASE,
)
SQL_COL_RE = re.compile(
    r"^\s*[`\"']?([a-zA-Z_]\w*)[`\"']?\s+([a-zA-Z_]\w*)",
    re.IGNORECASE,
)
SQL_FK_RE = re.compile(
    r"REFERENCES\s+[`\"']?(\w+)[`\"']?",
    re.IGNORECASE,
)
PRISMA_MODEL_RE = re.compile(
    r"model\s+(\w+)\s*\{([\s\S]*?)\}",
    re.IGNORECASE,
)


def _extract_sql_entities(text: str) -> list[dict]:
    """Parse CREATE TABLE statements to extract table names, columns, and foreign keys."""
    results = []
    for tm in SQL_TABLE_RE.finditer(text):
        table_name = tm.group(2) or tm.group(1)
        body = tm.group(3)
        fields = []
        relations = []
        for raw_line in body.split("\n"):
            line = raw_line.strip().rstrip(",")
            if not line or line.startswith(("--", "/*")):
                continue
            # Skip standalone table-level constraints
            if re.match(r"^(?:CONSTRAINT|PRIMARY\s+KEY|UNIQUE|CHECK|FOREIGN\s+KEY|INDEX|KEY)\b", line, re.IGNORECASE):
                fk_m = SQL_FK_RE.search(line)
                if fk_m:
                    relations.append(fk_m.group(1))
                continue
            col_m = SQL_COL_RE.match(line)
            if col_m:
                col_name = col_m.group(1)
                fields.append(col_name)
                fk_m = SQL_FK_RE.search(line)
                if fk_m:
                    relations.append(fk_m.group(1))
        results.append({"name": table_name, "fields": fields[:50], "relations": sorted(set(relations))})
    return results


def run_entity_extraction(db: Session, project_id: int, repo_dir: str) -> int:
    models = db.query(CodeSymbol).filter(
        CodeSymbol.project_id == project_id, CodeSymbol.kind == "model").all()
    files = {sf.id: sf for sf in db.query(SourceFile).filter(SourceFile.project_id == project_id).all()}
    db.query(DataEntity).filter(DataEntity.project_id == project_id).delete()
    db.commit()

    seen_entities: dict[str, dict] = {}

    # 1. Application code models (SQLAlchemy, Django, etc.)
    for m in models:
        sf = files.get(m.source_file_id)
        if m.name.endswith("Admin") or (sf and ("admin.py" in sf.path.lower() or "/admin/" in sf.path.lower() or "\\admin\\" in sf.path.lower())):
            continue
        fields: list[str] = []
        relations: list[str] = []
        if sf:
            try:
                with open(os.path.join(repo_dir, sf.path), encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                for ln in lines[m.start_line:m.end_line + 30]:
                    fm = APP_FIELD_RE.match(ln)
                    if fm:
                        fields.append(fm.group(1))
                    rel_m = re.search(r"(?:ForeignKey|relationship)\(['\"](\w+)", ln)
                    if rel_m:
                        relations.append(rel_m.group(1))
            except OSError:
                pass
        seen_entities[m.name.lower()] = {
            "name": m.name,
            "source_symbol_id": m.id,
            "fields": fields[:50],
            "relations": sorted(set(relations)),
        }

    # 2. SQL schema & migration files (runs together with application code models)
    for sf in files.values():
        if sf.path.endswith((".sql",)) or "migration" in sf.path.lower() or "schema" in sf.path.lower():
            try:
                with open(os.path.join(repo_dir, sf.path), encoding="utf-8", errors="ignore") as f:
                    txt = f.read()
            except OSError:
                continue

            # SQL tables
            for ent in _extract_sql_entities(txt):
                k = ent["name"].lower()
                if k in seen_entities:
                    # Merge fields and relations
                    cur = seen_entities[k]
                    cur["fields"] = sorted(set(cur["fields"] + ent["fields"]))[:50]
                    cur["relations"] = sorted(set(cur["relations"] + ent["relations"]))
                else:
                    seen_entities[k] = {
                        "name": ent["name"],
                        "source_symbol_id": 0,
                        "fields": ent["fields"],
                        "relations": ent["relations"],
                    }

            # Prisma models
            if sf.path.endswith(".prisma"):
                for pm in PRISMA_MODEL_RE.finditer(txt):
                    pname = pm.group(1)
                    pfields = [
                        ln.strip().split()[0]
                        for ln in pm.group(2).splitlines()
                        if ln.strip() and not ln.strip().startswith(("//", "@@"))
                    ]
                    k = pname.lower()
                    if k not in seen_entities:
                        seen_entities[k] = {
                            "name": pname,
                            "source_symbol_id": 0,
                            "fields": pfields[:50],
                            "relations": [],
                        }

    # Persist all extracted entities
    for ent in seen_entities.values():
        db.add(DataEntity(
            project_id=project_id,
            name=ent["name"],
            source_symbol_id=ent["source_symbol_id"],
            fields_json=json.dumps(ent["fields"]),
            relations_json=json.dumps(ent["relations"]),
        ))
    db.commit()
    return len(seen_entities)

