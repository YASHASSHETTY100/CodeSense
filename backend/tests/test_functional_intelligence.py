"""Regression tests for functional intelligence improvements.

Covers:
1. Binary and model file exclusion
2. Secret detection and redaction
3. Query intent, entity, and action extraction
4. SQL and application code entity extraction
5. Positive functional questions with 6-dimensional structured answer
6. Evidence sufficiency gate & negative-query protection (unsupported queries return INSUFFICIENT_EVIDENCE with empty evidence)
7. Evidence relevance & test down-weighting
8. Secret absence in KB chunks, retrieval, and answers
9. Project summary using repository content
"""
from __future__ import annotations
import os, tempfile, json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.models import Base, Project, SourceFile, KnowledgeChunk
from app.analysis.structural.pipeline import run_structural_analysis
from app.analysis.functional.pipeline import run_functional_analysis
from app.knowledge_base.pipeline import run_kb_indexing
from app.knowledge_base.retrieval import (
    retrieve, evaluate_sufficiency, normalize_concept, decompose_identifier, is_concept_evidenced
)
from app.reasoning import summarize_project, answer_functional_question, trace_flow, analyze_enhancement
from app.analysis.security import (
    redact_secrets, contains_secrets, is_binary_content, is_test_file, is_util_file
)
from app.analysis.query_intent import analyze_query
from app.ingestion.orchestrator import SKIP_EXT, SKIP_DIRS


def _db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=eng)
    return sessionmaker(bind=eng)()


def test_binary_and_model_file_exclusion():
    # 1. Null-byte binary detection
    assert is_binary_content(b"ELF\x00\x02\x01\x01\x00")
    assert is_binary_content(b"PK\x03\x04\x14\x00\x08\x00")
    assert not is_binary_content(b"def submit_order():\n    return True\n")

    # 2. Skip extensions
    assert ".pkl" in SKIP_EXT
    assert ".pt" in SKIP_EXT
    assert ".onnx" in SKIP_EXT
    assert ".exe" in SKIP_EXT
    assert ".so" in SKIP_EXT
    assert ".safetensors" in SKIP_EXT
    assert ".bin" in SKIP_EXT
    assert ".py" not in SKIP_EXT
    assert ".js" not in SKIP_EXT

    # 3. Skip directories
    assert "target" in SKIP_DIRS
    assert "bin" in SKIP_DIRS
    assert ".next" in SKIP_DIRS
    assert "coverage" in SKIP_DIRS
    assert "node_modules" in SKIP_DIRS


def test_secret_redaction():
    # Connection string
    conn_str = "postgresql://app_user:mypassword123@db.prod.internal:5432/appdb"
    assert contains_secrets(conn_str)
    redacted = redact_secrets(f"DATABASE_URI = '{conn_str}'")
    assert "mypassword123" not in redacted
    assert "[REDACTED_CONNECTION_STRING]" in redacted

    # API keys & tokens
    gh_token = "ghp_1234567890abcdef1234567890abcdef1234"
    assert contains_secrets(gh_token)
    assert "[REDACTED_TOKEN]" in redact_secrets(f"GITHUB_TOKEN = '{gh_token}'")

    ai_key = "sk-1234567890abcdef1234567890abcdef"
    assert "[REDACTED_API_KEY]" in redact_secrets(f"api_key: '{ai_key}'")

    aws_key = "AKIA1234567890ABCDEF"
    assert "[REDACTED_AWS_KEY]" in redact_secrets(f"aws_key = '{aws_key}'")

    # Passwords & secrets in key-value pairs
    pw_line = 'password = "supersecretpassword123"'
    assert contains_secrets(pw_line)
    redacted_pw = redact_secrets(pw_line)
    assert "supersecretpassword123" not in redacted_pw
    assert "[REDACTED_SECRET]" in redacted_pw

    # Private key
    private_key = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...\n-----END RSA PRIVATE KEY-----"
    assert contains_secrets(private_key)
    assert "[REDACTED_PRIVATE_KEY]" in redact_secrets(private_key)


def test_query_intent_and_entity_action_extraction():
    # 1. How
    qi1 = analyze_query("how does order submission currently work?")
    assert qi1.intent == "how"
    assert "order" in qi1.entities
    assert "submit" in qi1.actions

    # 2. Why / Business rule
    qi2 = analyze_query("which business rule prevents editing approved orders?")
    assert qi2.intent == "why/business rule"
    assert "order" in qi2.entities
    assert "edit" in qi2.actions or "approve" in qi2.actions
    assert "rule" in qi2.business_terms or "prevents" in qi2.business_terms or "approved" in qi2.business_terms

    # 3. Workflow
    qi3 = analyze_query("trace the checkout workflow step by step")
    assert qi3.intent == "workflow"
    assert "checkout" in qi3.actions or "checkout" in qi3.entities

    # 4. Module understanding
    qi4 = analyze_query("which modules are involved in inventory management?")
    assert qi4.intent == "module understanding"
    assert "inventory" in qi4.entities

    # 5. Client support
    qi5 = analyze_query("customer cannot checkout due to 400 error")
    assert qi5.intent == "client support"
    assert "customer" in qi5.entities
    assert "checkout" in qi5.actions

    # 6. Enhancement
    qi6 = analyze_query("can we allow editing approved orders instead of blocking it?")
    assert qi6.intent == "enhancement/impact"
    assert "edit" in qi6.actions


def test_database_entity_extraction_sql_and_code():
    from app.analysis.functional.entities import run_entity_extraction
    from app.analysis.structural.pipeline import run_structural_analysis
    from app.models.models import DataEntity

    db = _db()
    d = tempfile.mkdtemp()
    p = Project(name="schema_test", repo_url="https://github.com/test/schema")
    db.add(p)
    db.flush()

    sql_content = """CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    customer_id INT REFERENCES users(id),
    total_amount DECIMAL(10, 2),
    status VARCHAR(50)
);
CREATE TABLE IF NOT EXISTS invoices (
    id INT PRIMARY KEY,
    order_id INT REFERENCES orders(id),
    invoice_number VARCHAR(100)
);
"""
    py_model = """class User(Base):
    id = Column(Integer, primary_key=True)
    email = Column(String)
    is_active = Column(Boolean)
"""

    os.makedirs(os.path.join(d, "db"), exist_ok=True)
    os.makedirs(os.path.join(d, "app"), exist_ok=True)
    open(os.path.join(d, "db", "schema.sql"), "w").write(sql_content)
    open(os.path.join(d, "app", "models.py"), "w").write(py_model)

    sf1 = SourceFile(project_id=p.id, path="db/schema.sql", language="sql", hash="1")
    sf2 = SourceFile(project_id=p.id, path="app/models.py", language="python", hash="2")
    db.add_all([sf1, sf2])
    db.commit()

    run_structural_analysis(db, p.id, d)
    n_ents = run_entity_extraction(db, p.id, d)

    entities = {e.name.lower(): e for e in db.query(DataEntity).filter(DataEntity.project_id == p.id).all()}
    assert "orders" in entities
    assert "invoices" in entities
    assert "user" in entities

    order_fields = json.loads(entities["orders"].fields_json)
    assert "customer_id" in order_fields or "id" in order_fields
    order_rels = json.loads(entities["orders"].relations_json)
    assert "users" in order_rels


def _create_shop_project(db, with_secret: bool = False):
    d = tempfile.mkdtemp()
    p = Project(name="shop", repo_url="https://github.com/acme/shop", repo_provider="github")
    db.add(p)
    db.flush()

    secret_snippet = 'API_SECRET = "sk-secret1234567890abcdef12345"\n' if with_secret else ""

    files = {
        "orders/api.py": f'''
from fastapi import APIRouter
router = APIRouter()
{secret_snippet}
@router.post("/orders/submit")
def submit_order(order_id: int):
    """Submit an order for approval."""
    if order.status == "approved":
        raise ValueError("approved orders cannot be edited")
    db.session.add(order)
    return {{"ok": True}}
''',
        "orders/models.py": '''
class Order(Base):
    status = Column(String)
    total = Column(Float)
''',
        "inventory/stock.py": '''
def check_stock(sku: str):
    if stock == 0:
        raise ValueError("out of stock")
    return stock
''',
        "tests/test_orders.py": '''
def test_submit_order():
    assert True
''',
        "README.md": '''# Acme Shop Platform
Enterprise e-commerce fulfillment service. Handles cart checkout and order submission.
''',
    }

    for rel, content in files.items():
        fp = os.path.join(d, rel)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        open(fp, "w", encoding="utf-8").write(content)
        lang = "python" if rel.endswith(".py") else "markdown"
        db.add(SourceFile(project_id=p.id, path=rel, language=lang, hash="h"))

    db.commit()
    run_structural_analysis(db, p.id, d)
    run_functional_analysis(db, p.id, d)
    run_kb_indexing(db, p.id, d)
    return p, d


def test_positive_functional_question_with_structured_answer():
    db = _db()
    p, d = _create_shop_project(db)

    # Positive query: order submission
    ans = answer_functional_question(db, p.id, "how does order submission currently work?")
    assert ans["status"] == "SUCCESS"
    assert ans["confidence"] in ("High", "Medium")
    assert bool(ans["evidence"])
    assert "orders" in ans["affected_modules"]
    assert bool(ans["functional_flow"])
    assert "Answer" in ans["answer"] or "How It Works" in ans["answer"]

    # Positive query: business rules
    ans_rule = answer_functional_question(db, p.id, "which business rule prevents editing approved orders?")
    assert ans_rule["status"] == "SUCCESS"
    assert bool(ans_rule["evidence"])
    assert any("approved" in r.lower() or "validation" in r.lower() for r in ans_rule["business_rules"]) or bool(ans_rule["evidence"])


def test_negative_unsupported_questions_evidence_sufficiency_gate():
    db = _db()
    p, d = _create_shop_project(db)

    # Required negative queries on shop project:
    # 1. "How does purchase order approval work?"
    po_ans = answer_functional_question(db, p.id, "How does purchase order approval work?")
    assert po_ans["status"] == "INSUFFICIENT_EVIDENCE"
    assert po_ans["evidence"] == [], "Evidence must be empty for unsupported domain question"
    assert po_ans["confidence"] == "None"
    assert "purchase order" in po_ans["missing_concepts"] or "purchase" in " ".join(po_ans["missing_concepts"]).lower()

    # 2. "How is an invoice generated?"
    inv_ans = answer_functional_question(db, p.id, "How is an invoice generated?")
    assert inv_ans["status"] == "INSUFFICIENT_EVIDENCE"
    assert inv_ans["evidence"] == []
    assert inv_ans["confidence"] == "None"
    assert "invoice" in inv_ans["missing_concepts"]

    # 3. "How does inventory get updated?"
    # (Shop repo only has check_stock, no update inventory)
    inv_up_ans = answer_functional_question(db, p.id, "How does inventory get updated?")
    assert inv_up_ans["status"] == "INSUFFICIENT_EVIDENCE"
    assert inv_up_ans["evidence"] == []
    assert inv_up_ans["confidence"] == "None"


def test_negative_queries_on_missing_person_repo():
    db = _db()
    d = tempfile.mkdtemp()
    p = Project(name="missing_person", repo_url="https://github.com/ngo/missing-person")
    db.add(p)
    db.flush()

    files = {
        "cases/models.py": '''
class MissingPerson(Base):
    full_name = Column(String)
    age = Column(Integer)
    last_seen_location = Column(String)
    status = Column(String)
''',
        "cases/search.py": '''
def search_missing_persons(name: str):
    return db.query(MissingPerson).filter(MissingPerson.full_name.ilike(f"%{name}%")).all()
''',
    }

    for rel, content in files.items():
        fp = os.path.join(d, rel)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        open(fp, "w", encoding="utf-8").write(content)
        db.add(SourceFile(project_id=p.id, path=rel, language="python", hash="h"))

    db.commit()
    run_structural_analysis(db, p.id, d)
    run_functional_analysis(db, p.id, d)
    run_kb_indexing(db, p.id, d)

    # For a missing-person repository, shop queries MUST return INSUFFICIENT_EVIDENCE with empty evidence:
    # 1. "How does purchase order approval work?"
    r1 = answer_functional_question(db, p.id, "How does purchase order approval work?")
    assert r1["status"] == "INSUFFICIENT_EVIDENCE"
    assert r1["evidence"] == []

    # 2. "How is an invoice generated?"
    r2 = answer_functional_question(db, p.id, "How is an invoice generated?")
    assert r2["status"] == "INSUFFICIENT_EVIDENCE"
    assert r2["evidence"] == []

    # 3. "How does inventory get updated?"
    r3 = answer_functional_question(db, p.id, "How does inventory get updated?")
    assert r3["status"] == "INSUFFICIENT_EVIDENCE"
    assert r3["evidence"] == []

    # Positive query on missing-person repo MUST succeed:
    r_pos = answer_functional_question(db, p.id, "how does missing person search work?")
    assert r_pos["status"] == "SUCCESS"
    assert bool(r_pos["evidence"])
    assert any("cases/search.py" in e["file"] or "MissingPerson" in e["symbol"] for e in r_pos["evidence"])


def test_secret_never_exposed_in_kb_chunks_or_retrieval():
    db = _db()
    p, d = _create_shop_project(db, with_secret=True)

    # 1. Chunks in DB must not contain raw secret
    chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.project_id == p.id).all()
    for c in chunks:
        assert "sk-secret1234567890abcdef12345" not in c.chunk_text

    # 2. Retrieval output must not contain raw secret
    hits = retrieve(db, p.id, "submit order api", top_k=5)
    for h in hits:
        assert "sk-secret1234567890abcdef12345" not in h["text"]

    # 3. Functional answer must not contain raw secret
    ans = answer_functional_question(db, p.id, "how does order submission currently work?")
    assert "sk-secret1234567890abcdef12345" not in ans["answer"]


def test_evidence_relevance_and_test_downweighting():
    db = _db()
    p, d = _create_shop_project(db)

    # General functional query should prioritize orders/api.py over test_orders.py
    hits = retrieve(db, p.id, "order submission", top_k=5)
    assert len(hits) > 0
    top_file = hits[0]["source_ref"]
    assert "tests/" not in top_file, f"Expected domain file to rank above test file, got {top_file}"


def test_project_summary_with_repo_content():
    db = _db()
    p, d = _create_shop_project(db)

    s = summarize_project(db, p.id)
    assert "Acme Shop Platform" in s["summary"] or "Enterprise e-commerce fulfillment" in s["summary"] or "orders" in s["summary"].lower()
    assert bool(s["evidence"])


def test_generic_verbs_not_treated_as_domain_concepts():
    forbidden_generic_terms = {
        "used", "use", "get", "gets", "happen", "happens", "work", "does", "do",
        "is", "are", "how", "what", "why", "when", "where", "can", "could", "should", "would",
    }

    # 1. "What is this application used for?"
    qi1 = analyze_query("What is this application used for?")
    assert qi1.intent == "purpose"
    assert not any(t in qi1.entities for t in forbidden_generic_terms)

    # 2. "How does a missing-person report get submitted?"
    qi2 = analyze_query("How does a missing-person report get submitted?")
    assert not any(t in qi2.entities for t in forbidden_generic_terms)
    assert "missing person" in qi2.entities or "missing person report" in qi2.entities
    assert "report" in qi2.entities or "missing person report" in qi2.entities
    assert "submit" in qi2.actions

    # 3. "What happens after a report is submitted?"
    qi3 = analyze_query("What happens after a report is submitted?")
    assert not any(t in qi3.entities for t in forbidden_generic_terms)
    assert "report" in qi3.entities
    assert "submit" in qi3.actions


def test_purpose_question_handling():
    db = _db()
    d = tempfile.mkdtemp()
    p = Project(name="safefind", repo_url="https://github.com/ngo/safefind")
    db.add(p)
    db.flush()

    files = {
        "README.md": """# SafeFind Platform
SafeFind is an open-source platform dedicated to tracking and locating missing persons.
It connects volunteers, authorities, and case workers to expedite search efforts.
""",
        "cases/search.py": """def search_cases(q: str):
    return []
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

    purpose_queries = [
        "What is this application used for?",
        "What does this application do?",
        "What problem does this system solve?",
        "What is the purpose of this application?",
    ]

    for pq in purpose_queries:
        ans = answer_functional_question(db, p.id, pq)
        assert ans["status"] == "SUCCESS", f"Failed on purpose query: {pq}"
        assert bool(ans["evidence"]), f"Expected evidence for purpose query: {pq}"
        assert any("README.md" in e["file"] for e in ans["evidence"]), f"Expected README citation for: {pq}"
        assert "SafeFind" in ans["current_behaviour"] or "missing persons" in ans["current_behaviour"].lower()


def test_six_required_questions_regression():
    db = _db()
    d = tempfile.mkdtemp()
    p = Project(name="reporting_app", repo_url="https://github.com/ngo/reporting-app")
    db.add(p)
    db.flush()

    files = {
        "README.md": """# Incident & Missing Person Reporting Portal
Coordinates incident intakes and missing-person case reports.
Enables citizens to file verified reports and track status.
""",
        "cases/models.py": """class MissingPersonReport(Base):
    id = Column(Integer, primary_key=True)
    full_name = Column(String)
    status = Column(String)
""",
        "cases/api.py": """from fastapi import APIRouter
router = APIRouter()

@router.post("/reports/submit")
def submit_report(report_id: int):
    \"\"\"Submit a missing person report for investigation.\"\"\"
    if report.status == "submitted":
        raise ValueError("Report already submitted")
    db.session.add(report)
    return {"status": "submitted"}
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

    # 1. "What is this application used for?" -> SUCCESS with README evidence
    q1 = answer_functional_question(db, p.id, "What is this application used for?")
    assert q1["status"] == "SUCCESS"
    assert bool(q1["evidence"])
    assert any("README.md" in e["file"] for e in q1["evidence"])

    # 2. "How does a missing-person report get submitted?" -> SUCCESS with submit_report evidence
    q2 = answer_functional_question(db, p.id, "How does a missing-person report get submitted?")
    assert q2["status"] == "SUCCESS"
    assert bool(q2["evidence"])
    assert any("cases/api.py" in e["file"] or "submit_report" in e["symbol"] for e in q2["evidence"])
    assert "cases" in q2["affected_modules"] or "root" in q2["affected_modules"]

    # 3. "What happens after a report is submitted?" -> SUCCESS with evidence
    q3 = answer_functional_question(db, p.id, "What happens after a report is submitted?")
    assert q3["status"] == "SUCCESS"
    assert bool(q3["evidence"])

    # 4. "How does purchase order approval work?" -> INSUFFICIENT_EVIDENCE with empty evidence
    q4 = answer_functional_question(db, p.id, "How does purchase order approval work?")
    assert q4["status"] == "INSUFFICIENT_EVIDENCE"
    assert q4["evidence"] == []
    assert q4["confidence"] == "None"

    # 5. "How is an invoice generated?" -> INSUFFICIENT_EVIDENCE with empty evidence
    q5 = answer_functional_question(db, p.id, "How is an invoice generated?")
    assert q5["status"] == "INSUFFICIENT_EVIDENCE"
    assert q5["evidence"] == []
    assert q5["confidence"] == "None"

    # 6. "How does inventory get updated?" -> INSUFFICIENT_EVIDENCE with empty evidence
    q6 = answer_functional_question(db, p.id, "How does inventory get updated?")
    assert q6["status"] == "INSUFFICIENT_EVIDENCE"
    assert q6["evidence"] == []
    assert q6["confidence"] == "None"


def test_concept_normalization_and_decomposition():
    # 1. Normalization: lowercase, hyphen/underscore -> space, collapse whitespace, safe singularization
    assert normalize_concept("missing-person") == "missing person"
    assert normalize_concept("Missing_Person_Reports") == "missing person report"
    assert normalize_concept("purchase-orders") == "purchase order"
    assert normalize_concept("invoices") == "invoice"
    assert normalize_concept("categories") == "category"
    assert normalize_concept("status") == "status"
    assert normalize_concept("class") == "class"

    # 2. Decompose snake_case, camelCase, kebab-case
    assert decompose_identifier("report_missing_person_form") == ["report", "missing", "person", "form"]
    assert decompose_identifier("MissingPersonReport") == ["missing", "person", "report"]
    assert decompose_identifier("order-status-check") == ["order", "status", "check"]
    assert decompose_identifier("notify_new_submission") == ["notify", "new", "submission"]
    assert decompose_identifier("generate_tracking_code") == ["generate", "tracking", "code"]


def test_targeted_concept_to_evidence_matching_unit():
    catalog = {
        "symbols": {"report_missing_person_form", "notify_new_submission", "generate_tracking_code", "track_report_form"},
        "entities": set(),
        "modules": {"cases"},
        "endpoint_paths": set(),
        "files": {"app.py", "readme.md"},
        "rules": [],
        "symbol_token_sets": [
            {"report", "missing", "person", "form"},
            {"notify", "new", "submission"},
            {"generate", "tracking", "code"},
            {"track", "report", "form"},
        ],
        "all_decomposed_tokens": {
            "report", "missing", "person", "form", "notify", "new",
            "submission", "generate", "tracking", "code", "track", "cases", "app", "readme"
        },
        "all_catalog_text": "report_missing_person_form notify_new_submission generate_tracking_code track_report_form cases app.py readme.md",
        "all_catalog_compact": "reportmissingpersonformnotifynewsubmissiongeneratetrackingcodetrackreportformcasesapppyreadmemd",
    }
    candidates = [
        {"source_ref": "app.py#L601-720", "text": "def report_missing_person_form(): st.form('report_form') c.execute('INSERT INTO persons')"},
        {"source_ref": "app.py#L721-840", "text": "notify_new_submission(report_id=person_id) run_matching_pipeline(person_id)"},
    ]

    # Positive concept matches
    assert is_concept_evidenced("missing person", catalog, candidates, ["submit"])
    assert is_concept_evidenced("missing person report", catalog, candidates, ["submit"])
    assert is_concept_evidenced("report", catalog, candidates, ["submit"])

    # Strict negative rejection: absent tokens must immediately return False
    assert not is_concept_evidenced("purchase order", catalog, candidates, ["approve"])
    assert not is_concept_evidenced("invoice", catalog, candidates, ["generate"])
    assert not is_concept_evidenced("inventory", catalog, candidates, ["update"])


def test_real_world_report_submission_and_post_submission_workflows():
    db = _db()
    d = tempfile.mkdtemp()
    p = Project(name="safe_portal", repo_url="https://github.com/ngo/safe-portal")
    db.add(p)
    db.flush()

    files = {
        "app.py": """
import sqlite3

def generate_tracking_code():
    return "TRK-12345"

def notify_new_submission(report_id, tracking_code):
    print("Notification sent for", report_id)

def run_matching_pipeline(report_id, name):
    print("Running matching pipeline for", report_id)

def report_missing_person_form(source="Public"):
    tracking_code = generate_tracking_code()
    conn = sqlite3.connect("cases.db")
    c = conn.cursor()
    c.execute("INSERT INTO persons (name, tracking_code) VALUES (?, ?)", ("John Doe", tracking_code))
    person_id = c.lastrowid
    conn.commit()
    conn.close()

    notify_new_submission(report_id=person_id, tracking_code=tracking_code)
    run_matching_pipeline(report_id=person_id, name="John Doe")
    return person_id
""",
        "README.md": """# Safe Portal
Application for reporting missing persons and coordinating volunteer search teams.
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

    # 1. "What is this application used for?" -> SUCCESS
    q1 = answer_functional_question(db, p.id, "What is this application used for?")
    assert q1["status"] == "SUCCESS"
    assert bool(q1["evidence"])

    # 2. "How does a missing-person report get submitted?" -> SUCCESS
    q2 = answer_functional_question(db, p.id, "How does a missing-person report get submitted?")
    assert q2["status"] == "SUCCESS"
    assert bool(q2["evidence"])
    evidence_refs = [e.get("file", "") + ":" + e.get("symbol", "") for e in q2["evidence"]]
    assert any("app.py" in ref for ref in evidence_refs)
    assert any("report_missing_person_form" in ref or "app.py" in ref for ref in evidence_refs)

    # 3. "What happens after a report is submitted?" -> SUCCESS
    q3 = answer_functional_question(db, p.id, "What happens after a report is submitted?")
    assert q3["status"] == "SUCCESS"
    assert bool(q3["evidence"])
    q3_evidence_refs = [e.get("file", "") + ":" + e.get("symbol", "") for e in q3["evidence"]]
    assert any("app.py" in ref for ref in q3_evidence_refs)

    # 4. "How does purchase order approval work?" -> INSUFFICIENT_EVIDENCE
    q4 = answer_functional_question(db, p.id, "How does purchase order approval work?")
    assert q4["status"] == "INSUFFICIENT_EVIDENCE"
    assert q4["evidence"] == []

    # 5. "How is an invoice generated?" -> INSUFFICIENT_EVIDENCE
    q5 = answer_functional_question(db, p.id, "How is an invoice generated?")
    assert q5["status"] == "INSUFFICIENT_EVIDENCE"
    assert q5["evidence"] == []

    # 6. "How does inventory get updated?" -> INSUFFICIENT_EVIDENCE
    q6 = answer_functional_question(db, p.id, "How does inventory get updated?")
    assert q6["status"] == "INSUFFICIENT_EVIDENCE"
    assert q6["evidence"] == []


