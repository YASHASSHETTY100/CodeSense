"""Capability-Driven Functional Reasoning Engine Test Suite.

Verifies the 22 required capability categories without memorized question mappings
or domain-specific hardcoding.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.models import Base, Project, SourceFile, CodeSymbol, KnowledgeChunk, Role
from app.knowledge_graph import (
    KnowledgeGraph, GraphNode, GraphEdge,
    NODE_FILE, NODE_MODEL, NODE_DB_FIELD, NODE_ROUTE, NODE_FUNCTION,
    NODE_TEMPLATE, NODE_FORM, NODE_FORM_FIELD, NODE_VALIDATION,
    REL_CALLS, REL_RENDERS, REL_ROUTES_TO, REL_VALIDATES, REL_WRITES, REL_USES_MODEL
)
from app.domain_vocabulary import (
    RepositoryDomainVocabulary, DomainConcept, decompose_tokens, singularize, ACTION_SYNONYMS
)
from app.query_planner import (
    create_query_plan, decompose_multi_intent_query,
    INTENT_GENERAL_FUNCTIONAL, INTENT_WORKFLOW, INTENT_PERMISSION, INTENT_DATA_STORAGE
)
from app.analysis.query_intent import analyze_query, INTENT_PURPOSE
from app.analysis.structural.parsers import parse_html_template, parse_python, parse_js_ts
from app.knowledge_base.retrieval import retrieve, get_project_catalog, evaluate_sufficiency
from app.reasoning.reasoning import answer_functional_question, trace_flow


@pytest.fixture
def db_session():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng)()
    try:
        yield session
    finally:
        session.close()


# 1. Paraphrase Understanding
def test_capability_1_paraphrase_understanding():
    q1 = "How does the customer provide an address?"
    q2 = "Where does the buyer submit shipping location details?"
    q3 = "In what way can users enter their delivery address?"

    p1 = create_query_plan(q1)
    p2 = create_query_plan(q2)
    p3 = create_query_plan(q3)

    assert p1.primary_intent in [INTENT_GENERAL_FUNCTIONAL, INTENT_WORKFLOW]
    assert p2.primary_intent in [INTENT_GENERAL_FUNCTIONAL, INTENT_WORKFLOW]
    assert p3.primary_intent in [INTENT_GENERAL_FUNCTIONAL, INTENT_WORKFLOW]

    assert p1.actor in ["customer", "user", "buyer"]
    assert p2.actor in ["customer", "user", "buyer"]
    assert p3.actor in ["customer", "user", "buyer"]

    assert any(a in p1.actions for a in ["provide", "enter", "submit"])
    assert any(a in p2.actions for a in ["provide", "enter", "submit"])
    assert any(a in p3.actions for a in ["provide", "enter", "submit"])


# 2. Synonym Resolution
def test_capability_2_synonym_resolution():
    assert "enter" in ACTION_SYNONYMS["provide"] or "submit" in ACTION_SYNONYMS["provide"]
    assert "save" in ACTION_SYNONYMS["submit"] or "provide" in ACTION_SYNONYMS["submit"]
    assert "modify" in ACTION_SYNONYMS["edit"] or "update" in ACTION_SYNONYMS["edit"]
    assert "lookup" in ACTION_SYNONYMS["search"] or "find" in ACTION_SYNONYMS["search"]


# 3. Actor, Action, Object Extraction
def test_capability_3_actor_action_object_extraction():
    plan = create_query_plan("Can an operator update patient records after admission?")
    assert plan.actor == "operator"
    assert "update" in plan.actions or "edit" in plan.actions
    assert any("patient" in c or "record" in c or "admission" in c for c in plan.concepts)


# 4. Semantic & Lexical Retrieval
def test_capability_4_semantic_lexical_retrieval(db_session):
    from app.knowledge_base.embeddings import get_embedder
    import json
    p = Project(name="TestProj4", repo_url="https://github.com/org/test4")
    db_session.add(p)
    db_session.flush()

    sf = SourceFile(project_id=p.id, path="services/billing.py", language="python")
    db_session.add(sf)
    db_session.flush()

    sym = CodeSymbol(
        project_id=p.id,
        source_file_id=sf.id,
        name="calculate_invoice_tax",
        kind="function",
        start_line=10,
        end_line=20,
        signature="def calculate_invoice_tax(subtotal, tax_rate):"
    )
    db_session.add(sym)

    code_text = "def calculate_invoice_tax(subtotal, tax_rate):\n    return subtotal * tax_rate"
    v = get_embedder().embed(code_text)
    chunk = KnowledgeChunk(
        project_id=p.id,
        source_ref="services/billing.py#L10",
        chunk_text=code_text,
        embedding_vector=json.dumps(v)
    )
    db_session.add(chunk)
    db_session.commit()

    ev = retrieve(db_session, p.id, "How is invoice tax calculated?", top_k=5)
    assert len(ev) >= 1
    assert "calculate_invoice_tax" in ev[0]["text"]


# 5. Symbol Retrieval
def test_capability_5_symbol_retrieval(db_session):
    p = Project(name="TestProj5", repo_url="https://github.com/org/test5")
    db_session.add(p)
    db_session.flush()

    sf = SourceFile(project_id=p.id, path="core/models.py", language="python")
    db_session.add(sf)
    db_session.flush()

    sym = CodeSymbol(
        project_id=p.id,
        source_file_id=sf.id,
        name="BillingProfile",
        kind="class",
        start_line=15,
        end_line=40,
        signature="class BillingProfile(models.Model):"
    )
    db_session.add(sym)
    chunk = KnowledgeChunk(
        project_id=p.id,
        source_ref="core/models.py:BillingProfile",
        chunk_text="class BillingProfile(models.Model):\n    user = models.OneToOneField(User)\n    card_token = models.CharField(max_length=120)"
    )
    db_session.add(chunk)
    db_session.commit()

    catalog = get_project_catalog(db_session, p.id)
    assert "billingprofile" in catalog["symbols"]


# 6. Graph Neighborhood Expansion
def test_capability_6_graph_expansion():
    kg = KnowledgeGraph(project_id=999)
    n1 = GraphNode(id="view:checkout", kind=NODE_FUNCTION, name="checkout_view", file_path="views.py")
    n2 = GraphNode(id="form:checkout", kind=NODE_FORM, name="CheckoutForm", file_path="forms.py")
    n3 = GraphNode(id="model:order", kind=NODE_MODEL, name="Order", file_path="models.py")

    kg.add_node(n1)
    kg.add_node(n2)
    kg.add_node(n3)

    kg.add_edge(GraphEdge(source_id=n1.id, target_id=n2.id, kind=REL_CALLS))
    kg.add_edge(GraphEdge(source_id=n2.id, target_id=n3.id, kind=REL_USES_MODEL))

    expanded = kg.expand_neighborhood([n1.id], max_hops=2)
    assert n1.id in expanded
    assert n2.id in expanded
    assert n3.id in expanded


# 7. UI-to-Backend Tracing
def test_capability_7_ui_to_backend_tracing():
    html = """
    <form action="/submit-claim/" method="POST">
        <input type="text" name="claim_number" placeholder="Enter Claim Number">
        <button type="submit">Submit Claim</button>
    </form>
    """
    res = parse_html_template(html)
    forms = [s for s in res if s.kind == "form"]
    fields = [s for s in res if s.kind == "form_field"]
    assert len(forms) == 1
    assert "/submit-claim/" in forms[0].name
    assert any("claim_number" in f.name for f in fields)


# 8. Backend-to-Database Tracing
def test_capability_8_backend_to_database_tracing():
    py_code = """
from django.db import models

class PatientRecord(models.Model):
    first_name = models.CharField(max_length=50)
    ssn = models.CharField(max_length=11)
    created_at = models.DateTimeField(auto_now_add=True)
"""
    res = parse_python(py_code)
    classes = [s.name for s in res if s.kind in ("class", "model")]
    fields = [s.name for s in res if s.kind == "field"]
    assert "PatientRecord" in classes
    assert any("first_name" in f for f in fields)


# 9. Cross-Layer Workflow Reconstruction
def test_capability_9_workflow_reconstruction():
    kg = KnowledgeGraph(project_id=100)
    tpl = GraphNode(id="tpl:intake", kind=NODE_TEMPLATE, name="intake.html", file_path="intake.html")
    form = GraphNode(id="form:intake", kind=NODE_FORM, name="IntakeForm", file_path="forms.py")
    route = GraphNode(id="route:intake", kind=NODE_ROUTE, name="/intake/submit", file_path="urls.py")
    view = GraphNode(id="func:intake_view", kind=NODE_FUNCTION, name="intake_view", file_path="views.py")
    model = GraphNode(id="model:intake", kind=NODE_MODEL, name="IntakeRecord", file_path="models.py")

    for n in [tpl, form, route, view, model]:
        kg.add_node(n)

    kg.add_edge(GraphEdge(source_id=tpl.id, target_id=form.id, kind=REL_RENDERS))
    kg.add_edge(GraphEdge(source_id=form.id, target_id=route.id, kind=REL_ROUTES_TO))
    kg.add_edge(GraphEdge(source_id=route.id, target_id=view.id, kind=REL_CALLS))
    kg.add_edge(GraphEdge(source_id=view.id, target_id=model.id, kind=REL_WRITES))

    chain = kg.trace_cross_layer("intake")
    assert "ui" in chain
    assert "form" in chain
    assert "route" in chain
    assert "controller" in chain
    assert "model" in chain


# 10. Business-Rule Discovery
def test_capability_10_business_rule_discovery():
    py_code = """
def validate_age(age):
    if age < 18:
        raise ValueError("Applicant must be at least 18 years old")
"""
    res = parse_python(py_code)
    assert any(s.kind == "function" and s.name == "validate_age" for s in res)


# 11. Validation Discovery
def test_capability_11_validation_discovery():
    django_form = """
from django import forms

class TransferForm(forms.Form):
    amount = forms.DecimalField()

    def clean_amount(self):
        amt = self.cleaned_data.get('amount')
        if amt <= 0:
            raise forms.ValidationError("Amount must be positive")
        return amt
"""
    res = parse_python(django_form)
    assert any(s.kind == "form" and s.name == "TransferForm" for s in res)
    assert any(s.name == "clean_amount" for s in res)


# 12. Role Discovery
def test_capability_12_role_discovery(db_session):
    p = Project(name="RoleProj", repo_url="https://github.com/org/role")
    db_session.add(p)
    db_session.commit()

    db_session.add(Role(project_id=p.id, name="ComplianceOfficer"))
    db_session.commit()

    catalog = get_project_catalog(db_session, p.id)
    assert "complianceofficer" in catalog["roles"]


# 13. Permission Discovery
def test_capability_13_permission_discovery():
    qi = analyze_query("Who is authorized to approve large wire transfers?")
    assert "PERMISSION_AUTH" in qi.intents or "USER_ROLE" in qi.intents


# 14. API Discovery
def test_capability_14_api_discovery():
    code = """
from fastapi import APIRouter
router = APIRouter()

@router.post("/api/v1/orders/cancel")
def cancel_order(order_id: str):
    pass
"""
    res = parse_python(code)
    assert any(s.kind == "route" and "/api/v1/orders/cancel" in s.name for s in res)


# 15. Integration Discovery
def test_capability_15_integration_discovery(db_session):
    from app.reasoning.reasoning import _detect_integrations
    p = Project(name="IntegProj", repo_url="https://github.com/org/integ")
    db_session.add(p)
    db_session.commit()

    c = KnowledgeChunk(
        project_id=p.id,
        source_ref="tasks.py",
        chunk_text="import celery\nfrom celery import Celery\napp = Celery('tasks', broker='redis://localhost:6379/0')"
    )
    db_session.add(c)
    db_session.commit()

    integs = _detect_integrations(db_session, p.id)
    assert any("Celery" in i or "Redis" in i for i in integs)


# 16. Multi-Intent Decomposition
def test_capability_16_multi_intent_decomposition():
    q = "How does checkout work, who can perform it, how is payment processed, and what happens to the order afterward?"
    sub_queries = decompose_multi_intent_query(q)
    assert len(sub_queries) >= 3
    assert any("checkout" in sq.lower() for sq in sub_queries)
    assert any("who" in sq.lower() or "perform" in sq.lower() for sq in sub_queries)
    assert any("payment" in sq.lower() for sq in sub_queries)


# 17. Ambiguity Handling
def test_capability_17_ambiguity_handling():
    # Pronoun query without context
    qi = analyze_query("What does it do?")
    assert qi.is_ambiguous is True
    assert "clarify" in qi.clarification_prompt.lower()


# 18. Unknown Phrasing Fallback
def test_capability_18_unknown_phrasing():
    plan = create_query_plan("Can you clarify the behavior when a novel edge situation transpires?")
    assert plan.primary_intent == INTENT_GENERAL_FUNCTIONAL
    assert plan.retrieval_strategies


# 19. Negative Evidence Rejection
def test_capability_19_negative_evidence(db_session):
    p = Project(name="EmptyProj", repo_url="https://github.com/org/empty")
    db_session.add(p)
    db_session.commit()

    res = answer_functional_question(db_session, p.id, "How does payroll distribution execute?")
    assert res["status"] == "INSUFFICIENT_EVIDENCE"
    assert res["confidence"] == "None"
    assert len(res["evidence"]) == 0


# 20. Project Isolation
def test_capability_20_project_isolation(db_session):
    p1 = Project(name="ProjA", repo_url="https://github.com/org/a")
    p2 = Project(name="ProjB", repo_url="https://github.com/org/b")
    db_session.add_all([p1, p2])
    db_session.commit()

    c1 = KnowledgeChunk(
        project_id=p1.id,
        source_ref="secret_algo.py",
        chunk_text="PROPRIETARY_TRADING_ALGORITHM_A = 999.5"
    )
    db_session.add(c1)
    db_session.commit()

    # Query project 2
    ev2 = retrieve(db_session, p2.id, "PROPRIETARY_TRADING_ALGORITHM_A", top_k=5)
    assert len(ev2) == 0


# 21. Cross-Language Support (TS, Python, HTML)
def test_capability_21_cross_language():
    js_code = """
export default function UserProfile() {
    return <div>Profile</div>;
}
app.post('/api/profile/update', handler);
"""
    res = parse_js_ts(js_code)
    assert any(s.kind == "component" and s.name == "UserProfile" for s in res)
    assert any(s.kind == "route" and "/api/profile/update" in s.name for s in res)


# 22. Cross-Domain Generalization
def test_capability_22_cross_domain_generalization():
    vocab = RepositoryDomainVocabulary(project_id=50)

    # Healthcare domain concepts
    c1 = DomainConcept(canonical_name="patient", aliases={"patient", "patients", "subject"})
    c2 = DomainConcept(canonical_name="vitals", aliases={"vital", "vitals", "blood_pressure"})
    vocab.add_concept(c1)
    vocab.add_concept(c2)

    plan = create_query_plan("How are patient vitals recorded and verified?", vocab=vocab)
    assert "patient" in plan.concepts
    assert "vitals" in plan.concepts
    assert any(a in plan.actions for a in ["record", "verify"])
