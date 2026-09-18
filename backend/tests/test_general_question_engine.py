"""Automated Acceptance Test Suite: General Question Engine & Multi-Domain Repository Generalization.

Verifies:
1. Full 30+ Intent Taxonomy and Query Planning
2. Multi-Dimensional Intents & Compound Questions
3. Dynamic Noun Chunking without hardcoded domain vocabulary
4. Follow-up pronoun resolution & ambiguity detection
5. Multi-Domain Repository Generalization (E-Commerce, Healthcare, Missing Persons)
6. Dynamic Question Suggestion Generation per Repository Domain
7. Zero-hallucination negative query rejection across differing domains
"""
from __future__ import annotations
import os, tempfile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.models import Base, Project, SourceFile
from app.analysis.structural.pipeline import run_structural_analysis
from app.analysis.functional.pipeline import run_functional_analysis
from app.knowledge_base.pipeline import run_kb_indexing
from app.analysis.query_intent import (
    analyze_query,
    INTENT_PURPOSE, INTENT_USER_ROLE, INTENT_PERMISSION_AUTH,
    INTENT_WORKFLOW, INTENT_HOW_IT_WORKS, INTENT_WHY_BUSINESS_RULE,
    INTENT_VALIDATION, INTENT_ERROR_HANDLING, INTENT_DATABASE,
    INTENT_DATA_ENTITY, INTENT_API, INTENT_INTEGRATION
)
from app.reasoning import (
    answer_functional_question, trace_flow, analyze_enhancement,
    generate_suggested_questions
)


def _db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=eng)
    return sessionmaker(bind=eng)()


def test_taxonomy_and_query_plan_generation():
    # 1. Purpose
    q_purp = analyze_query("What is this application used for?")
    assert INTENT_PURPOSE in q_purp.intents
    assert q_purp.intent == "purpose"
    assert "overview" in q_purp.query_plan["target_layers"]

    # 2. Role & Permission
    q_role = analyze_query("Who can approve an order in this system?")
    assert INTENT_PERMISSION_AUTH in q_role.intents or INTENT_USER_ROLE in q_role.intents
    assert "security" in q_role.query_plan["target_layers"]

    # 3. Workflow
    q_wf = analyze_query("How does customer onboarding work end to end?")
    assert INTENT_WORKFLOW in q_wf.intents or INTENT_HOW_IT_WORKS in q_wf.intents
    assert "customer onboarding" in q_wf.entities or "customer" in q_wf.entities
    assert "backend" in q_wf.query_plan["target_layers"]

    # 4. Database
    q_db = analyze_query("What database tables store customer records?")
    assert INTENT_DATABASE in q_db.intents or INTENT_DATA_ENTITY in q_db.intents
    assert "database" in q_db.query_plan["target_layers"]
    assert "model" in q_db.query_plan["required_evidence_kinds"] or "sql" in q_db.query_plan["required_evidence_kinds"]

    # 5. API
    q_api = analyze_query("What APIs and endpoints handle the checkout request?")
    assert INTENT_API in q_api.intents
    assert "endpoints" in q_api.query_plan["target_layers"]

    # 6. Integration
    q_int = analyze_query("Which external systems and third-party services does this application integrate with?")
    assert INTENT_INTEGRATION in q_int.intents
    assert "integrations" in q_int.query_plan["target_layers"]

    # 7. Error handling
    q_err = analyze_query("What happens if payment processing fails?")
    assert INTENT_ERROR_HANDLING in q_err.intents
    assert "exceptions" in q_err.query_plan["target_layers"]

    # 8. Validation & Business rules
    q_val = analyze_query("What validations and business rules are enforced on invoice creation?")
    assert INTENT_VALIDATION in q_val.intents or INTENT_WHY_BUSINESS_RULE in q_val.intents

    # 9. Compound multi-dimensional intent
    q_comp = analyze_query("Who can approve an order and what happens after approval?")
    assert INTENT_PERMISSION_AUTH in q_comp.intents or INTENT_USER_ROLE in q_comp.intents
    assert INTENT_WORKFLOW in q_comp.intents or INTENT_HOW_IT_WORKS in q_comp.intents


def test_follow_up_pronoun_resolution_and_ambiguity():
    # Contextual follow up
    history = [
        {"question": "How does customer onboarding work?", "answer": "Customer onboarding validates user credentials."}
    ]
    follow_up = analyze_query("Who approves it?", history=history)
    assert not follow_up.is_ambiguous
    assert "customer" in follow_up.resolved_query.lower()

    # Ambiguous query without prior context
    ambig = analyze_query("Who approves it?", history=None)
    assert ambig.is_ambiguous
    assert "clarify" in ambig.clarification_prompt.lower()

    # Non-ambiguous purpose query (should never be flagged ambiguous)
    purp = analyze_query("What is this application used for?", history=None)
    assert not purp.is_ambiguous


def test_dynamic_noun_chunking_without_hardcoding():
    # New unseen domain: Medical prescription dispensing
    q1 = analyze_query("How does medical prescription dispensing work?")
    assert "medical prescription" in q1.entities or "prescription" in q1.entities

    # New unseen domain: Dental patient history
    q2 = analyze_query("Where is dental patient history stored?")
    assert "dental patient" in q2.entities or "patient" in q2.entities

    # Generic verbs are excluded
    for ent in q1.entities:
        assert ent not in {"used", "happen", "work", "make", "take", "run", "do"}


def test_multidomain_repository_generalization_ecommerce():
    """Repository B: E-Commerce store with Orders, Products, and Stripe checkout."""
    db = _db()
    d = tempfile.mkdtemp()
    p = Project(name="ecommerce_shop", repo_url="https://github.com/acme/shop")
    db.add(p)
    db.flush()

    files = {
        "README.md": """# E-Commerce Cloud Shop
A cloud-native online retail store application.
Allows customers to browse products, place orders, and make payments via Stripe.
Administrators can approve discounted orders and manage inventory.
""",
        "orders/models.py": """
from sqlalchemy import Column, Integer, String, Float

class Order(Base):
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer)
    total_amount = Column(Float)
    status = Column(String)
""",
        "orders/checkout.py": """
import httpx

def process_checkout(order_id: int, payment_token: str):
    \"\"\"Process customer order payment and trigger fulfillment.\"\"\"
    if not payment_token:
        raise ValueError("Payment token is required for checkout")
    # Call Stripe payment gateway
    return {"status": "paid", "order_id": order_id}

def approve_order(order_id: int, user_role: str):
    if user_role != "admin":
        raise PermissionError("Only admin can approve high-value orders")
    return {"status": "approved"}
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

    # 1. Purpose question
    ans1 = answer_functional_question(db, p.id, "What is this application used for?")
    assert ans1["status"] == "SUCCESS"
    assert "retail" in ans1["answer"].lower() or "shop" in ans1["answer"].lower() or "order" in ans1["answer"].lower()

    # 2. Workflow question
    ans2 = answer_functional_question(db, p.id, "How does process checkout work?")
    assert ans2["status"] == "SUCCESS"
    assert len(ans2["evidence"]) > 0

    # 3. Database question
    ans3 = answer_functional_question(db, p.id, "Where is order data stored?")
    assert ans3["status"] == "SUCCESS"
    assert any("order" in (ev.get("file") or ev.get("symbol", "")).lower() for ev in ans3["evidence"])

    # 4. Strict negative protection against unrelated domain (Missing Person)
    neg1 = answer_functional_question(db, p.id, "How does a missing-person report get submitted?")
    assert neg1["status"] == "INSUFFICIENT_EVIDENCE"
    assert neg1["evidence"] == []

    neg2 = answer_functional_question(db, p.id, "How is face detection performed?")
    assert neg2["status"] == "INSUFFICIENT_EVIDENCE"
    assert neg2["evidence"] == []

    # 5. Dynamic question suggestions must reflect E-Commerce domain
    sug = generate_suggested_questions(db, p.id)
    assert len(sug) >= 3
    sug_text = " ".join(sug).lower()
    assert "order" in sug_text or "application" in sug_text
    assert "missing person" not in sug_text


def test_multidomain_repository_generalization_healthcare():
    """Repository C: Healthcare clinic with Patient records and Appointments."""
    db = _db()
    d = tempfile.mkdtemp()
    p = Project(name="clinic_portal", repo_url="https://github.com/health/clinic")
    db.add(p)
    db.flush()

    files = {
        "README.md": """# Health Clinic Patient Portal
Manages outpatient visits, doctor schedules, and patient electronic health records.
Patients can request appointments and doctors review medical histories.
""",
        "patients/models.py": """
from sqlalchemy import Column, Integer, String, DateTime

class Patient(Base):
    id = Column(Integer, primary_key=True)
    full_name = Column(String)
    medical_record_number = Column(String)

class Appointment(Base):
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer)
    scheduled_at = Column(DateTime)
    status = Column(String)
""",
        "patients/service.py": """
def schedule_appointment(patient_id: int, date_time: str, doctor_id: int):
    \"\"\"Schedule a medical appointment for patient.\"\"\"
    if not date_time:
        raise ValueError("Appointment date and time required")
    return {"status": "scheduled", "patient_id": patient_id}
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

    # 1. Purpose question
    ans1 = answer_functional_question(db, p.id, "What is this application used for?")
    assert ans1["status"] == "SUCCESS"
    assert "clinic" in ans1["answer"].lower() or "patient" in ans1["answer"].lower()

    # 2. Workflow question
    ans2 = answer_functional_question(db, p.id, "How does schedule appointment work?")
    assert ans2["status"] == "SUCCESS"
    assert len(ans2["evidence"]) > 0

    # 3. Database question
    ans3 = answer_functional_question(db, p.id, "Where is patient data stored?")
    assert ans3["status"] == "SUCCESS"

    # 4. Strict negative protection against purchase orders and invoices
    neg1 = answer_functional_question(db, p.id, "How does purchase order approval work?")
    assert neg1["status"] == "INSUFFICIENT_EVIDENCE"
    assert neg1["evidence"] == []

    neg2 = answer_functional_question(db, p.id, "How is an invoice generated?")
    assert neg2["status"] == "INSUFFICIENT_EVIDENCE"
    assert neg2["evidence"] == []

    # 5. Dynamic question suggestions reflect Healthcare domain
    sug = generate_suggested_questions(db, p.id)
    assert len(sug) >= 3
    sug_text = " ".join(sug).lower()
    assert "patient" in sug_text or "appointment" in sug_text
    assert "missing person" not in sug_text
    assert "purchase order" not in sug_text


def test_informal_and_compound_questions():
    """Verify informal natural language queries and compound multi-intent questions."""
    db = _db()
    d = tempfile.mkdtemp()
    p = Project(name="fintech", repo_url="https://github.com/org/fintech", repo_provider="github")
    db.add(p)
    db.commit()

    files = {
        "README.md": "# WealthManager\nPersonal financial tracking, expense categorisation, and budget forecasting.",
        "accounts/service.py": '''
from fastapi import APIRouter
router = APIRouter()

class Account(Base):
    id = Column(Integer, primary_key=True)
    balance = Column(Float)
    status = Column(String)

@router.post("/api/accounts/transfer")
def transfer_funds(from_id: int, to_id: int, amount: float):
    """Execute funds transfer between accounts."""
    if amount <= 0:
        raise ValueError("Transfer amount must be strictly positive.")
    if from_acc.balance < amount:
        raise ValueError("Insufficient available funds for transfer.")
    from_acc.balance -= amount
    to_acc.balance += amount
    db.session.commit()
    return {"status": "completed"}
'''
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

    # 1. Informal / colloquial phrasing
    ans_informal = answer_functional_question(db, p.id, "can you tell me what this whole app actually does?")
    assert ans_informal["status"] == "SUCCESS"
    assert "wealthmanager" in ans_informal["answer"].lower() or "financial" in ans_informal["answer"].lower()

    # 2. Compound multi-intent question (workflow + database + validation)
    ans_compound = answer_functional_question(db, p.id, "how does transfer funds work and where is account balance stored?")
    assert ans_compound["status"] == "SUCCESS"
    assert len(ans_compound["evidence"]) >= 1
    assert "Answer" in ans_compound["answer"] or "How It Works" in ans_compound["answer"]

    # 3. Validation / business rule question
    ans_rules = answer_functional_question(db, p.id, "why would a transfer fail or get rejected?")
    assert ans_rules["status"] == "SUCCESS"
    assert any("positive" in r.lower() or "insufficient" in r.lower() for r in ans_rules["business_rules"]) or len(ans_rules["evidence"]) >= 1

    # 4. Contextual follow-up question
    history = [
        {"role": "user", "text": "How does transfer funds work?"},
        {"role": "assistant", "text": ans_compound["answer"]}
    ]
    ans_followup = answer_functional_question(db, p.id, "what happens when it fails?", history=history)
    assert ans_followup["status"] == "SUCCESS"
    assert len(ans_followup["evidence"]) >= 1

