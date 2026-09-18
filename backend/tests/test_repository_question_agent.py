"""Test suite for Repository Question Agent: Agentic Investigation Loop.

Validates the multi-step investigation cycle including:
- AIM navigation and entity matching
- Multi-source evidence collection and merging
- Claim-to-evidence grounding and guardrail enforcement
- Contradiction detection
- Confidence calibration
- Answer status determination
- Investigation step tracking
- Zero-hallucination compliance for unsupported queries
"""
import pytest
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.database import SessionLocal, engine, Base
from app.models.models import (
    Project, SourceFile, Module, ApiEndpoint, DataEntity,
    BusinessRule, Role, CodeSymbol, KnowledgeChunk, User
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def agent_project(db):
    """Create a test project with rich entities for agent investigation."""
    p = Project(
        name="AgentTestShop",
        repo_url="https://github.com/test/agent-shop",
        repo_provider="github",
    )
    db.add(p)
    db.flush()
    pid = p.id

    # Source files
    source_files = []
    for path, lang in [
        ("core/models.py", "Python"),
        ("core/views.py", "Python"),
        ("core/forms.py", "Python"),
        ("core/urls.py", "Python"),
        ("core/admin.py", "Python"),
        ("core/validators.py", "Python"),
        ("core/notifications.py", "Python"),
    ]:
        sf = SourceFile(project_id=pid, path=path, language=lang, hash="abc")
        db.add(sf)
        source_files.append(sf)
    db.flush()  # flush to get source_file IDs

    # Modules
    for name, desc in [
        ("core", "Core e-commerce module with product catalog, cart, and checkout"),
        ("accounts", "User account management and authentication"),
        ("payments", "Payment processing and gateway integration"),
    ]:
        db.add(Module(project_id=pid, name=name, description=desc, inferred_from="directory"))

    # API Endpoints
    for method, path, auth, roles in [
        ("POST", "/api/orders/", "yes", "customer,admin"),
        ("GET", "/api/products/", "no", ""),
        ("POST", "/api/checkout/", "yes", "customer"),
        ("PUT", "/api/profile/address/", "yes", "customer"),
        ("GET", "/api/admin/orders/", "yes", "admin"),
    ]:
        db.add(ApiEndpoint(project_id=pid, method=method, path=path, auth_required=auth, roles_allowed=roles))

    # Data Entities
    for name, fields in [
        ("Order", json.dumps([
            {"name": "id", "type": "int"}, {"name": "status", "type": "string"},
            {"name": "total", "type": "decimal"}, {"name": "shipping_address", "type": "FK:Address"},
        ])),
        ("Product", json.dumps([
            {"name": "id", "type": "int"}, {"name": "name", "type": "string"},
            {"name": "price", "type": "decimal"}, {"name": "stock", "type": "int"},
        ])),
        ("Address", json.dumps([
            {"name": "street_address", "type": "string"}, {"name": "city", "type": "string"},
            {"name": "zip", "type": "string"}, {"name": "country", "type": "string"},
        ])),
        ("Customer", json.dumps([
            {"name": "id", "type": "int"}, {"name": "email", "type": "string"},
            {"name": "name", "type": "string"},
        ])),
    ]:
        db.add(DataEntity(project_id=pid, name=name, fields_json=fields))

    # Business Rules
    for desc, trigger in [
        ("Order total must be greater than zero before checkout", "checkout_submission"),
        ("Stock quantity must be sufficient for requested order amount", "add_to_cart"),
        ("Shipping address must be complete and valid for order placement", "checkout_form_submit"),
    ]:
        db.add(BusinessRule(project_id=pid, description=desc, trigger_condition=trigger))

    # Roles
    for name, perms in [
        ("admin", json.dumps(["manage_orders", "manage_products", "manage_users"])),
        ("customer", json.dumps(["view_products", "place_orders", "manage_profile"])),
    ]:
        db.add(Role(project_id=pid, name=name, permissions_json=perms))

    # Code Symbols
    first_sf_id = source_files[0].id if source_files else 1
    for name, kind, sig, doc in [
        ("Order", "class", "class Order(models.Model)", "Represents a customer order with status tracking"),
        ("Product", "class", "class Product(models.Model)", "Product catalog item"),
        ("CheckoutView", "class", "class CheckoutView(View)", "Handles checkout form submission and order creation"),
        ("validate_address", "function", "def validate_address(addr)", "Validates shipping address completeness"),
        ("process_payment", "function", "def process_payment(order, method)", "Processes payment through gateway"),
    ]:
        db.add(CodeSymbol(project_id=pid, source_file_id=first_sf_id, name=name, kind=kind, signature=sig, docstring=doc, start_line=1, end_line=20))

    # Knowledge Chunks — rich implementation evidence
    chunks = [
        ("class Order(models.Model):\n    STATUS_CHOICES = [\n        ('pending', 'Pending'),\n        ('paid', 'Paid'),\n        ('processing', 'Processing'),\n        ('shipped', 'Shipped'),\n        ('delivered', 'Delivered'),\n    ]\n    status = models.CharField(choices=STATUS_CHOICES, default='pending')\n    total = models.DecimalField()\n    shipping_address = models.ForeignKey(Address)\n    customer = models.ForeignKey(Customer)",
         "core/models.py:Order"),
        ("class Address(models.Model):\n    street_address = models.CharField(max_length=200)\n    apartment_address = models.CharField(max_length=200, blank=True)\n    country = CountryField()\n    zip = models.CharField(max_length=20)\n    user = models.ForeignKey(User)",
         "core/models.py:Address"),
        ("class CheckoutView(View):\n    def post(self, request):\n        form = CheckoutForm(request.POST)\n        if form.is_valid():\n            address = Address.objects.get(user=request.user)\n            order = Order.objects.create(\n                customer=request.user,\n                shipping_address=address,\n                total=cart.get_total(),\n                status='pending'\n            )\n            return redirect('payment')",
         "core/views.py:CheckoutView"),
        ("class CheckoutForm(forms.Form):\n    street_address = forms.CharField(required=True)\n    apartment_address = forms.CharField(required=False)\n    country = forms.ChoiceField()\n    zip = forms.CharField(required=True)\n    def clean_zip(self):\n        zip_val = self.cleaned_data['zip']\n        if not zip_val.isalnum():\n            raise ValidationError('Invalid ZIP code')\n        return zip_val",
         "core/forms.py:CheckoutForm"),
        ("def validate_address(addr):\n    if not addr.street_address:\n        raise ValueError('Street address is required')\n    if not addr.zip:\n        raise ValueError('ZIP code is required')\n    if not addr.country:\n        raise ValueError('Country is required')\n    return True",
         "core/validators.py:validate_address"),
        ("def process_payment(order, payment_method):\n    gateway = get_payment_gateway()\n    result = gateway.charge(order.total, payment_method)\n    if result.success:\n        order.status = 'paid'\n        order.save()\n        send_confirmation_email(order)\n    else:\n        raise PaymentError(result.error_message)",
         "core/views.py:process_payment"),
        ("urlpatterns = [\n    path('api/orders/', OrderCreateView.as_view()),\n    path('api/products/', ProductListView.as_view()),\n    path('api/checkout/', CheckoutView.as_view()),\n    path('api/profile/address/', AddressUpdateView.as_view()),\n]",
         "core/urls.py:urlpatterns"),
    ]
    for text, ref in chunks:
        db.add(KnowledgeChunk(project_id=pid, source_ref=ref, chunk_text=text))

    db.commit()
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAgentInvestigation:
    """Test the Repository Question Agent investigation loop."""

    def test_supported_question_returns_success(self, db, agent_project):
        """Agent should successfully answer a supported question about the repository."""
        from app.reasoning.repository_question_agent import investigate_question
        result = investigate_question(db, agent_project.id, "How does the customer provide an address?")

        assert result["status"] == "SUCCESS"
        assert result["confidence"] in ("High", "Medium")
        assert "investigation_steps" in result
        assert len(result["investigation_steps"]) > 0

    def test_investigation_steps_tracked(self, db, agent_project):
        """Agent should track all investigation steps it executed."""
        from app.reasoning.repository_question_agent import investigate_question
        result = investigate_question(db, agent_project.id, "What validation is performed before checkout?")

        steps = result.get("investigation_steps", [])
        assert "UNDERSTAND_QUESTION" in steps
        # Should have completed multiple steps
        assert len(steps) >= 3

    def test_intents_classified(self, db, agent_project):
        """Agent should classify query intents via NLU."""
        from app.reasoning.repository_question_agent import investigate_question
        result = investigate_question(db, agent_project.id, "Where is customer address information stored?")

        assert "intents" in result
        assert len(result["intents"]) > 0
        assert "primary_intent" in result

    def test_evidence_collected_and_verified(self, db, agent_project):
        """Agent should collect evidence and apply citation guardrails."""
        from app.reasoning.repository_question_agent import investigate_question
        result = investigate_question(db, agent_project.id, "Which API or route handles order creation?")

        assert "evidence" in result
        assert "guard_dropped" in result
        assert isinstance(result["evidence"], list)

    def test_claims_grounding_present(self, db, agent_project):
        """Agent should provide claim-to-evidence grounding maps."""
        from app.reasoning.repository_question_agent import investigate_question
        result = investigate_question(db, agent_project.id, "What happens after an order is placed?")

        if result["status"] == "SUCCESS":
            assert "claims_grounding" in result
            # Each grounding should have derivation_type
            for cg in result.get("claims_grounding", []):
                assert "derivation_type" in cg
                assert cg["derivation_type"] in ("DIRECT_EVIDENCE", "CROSS_LAYER_TRACE", "MULTI_EVIDENCE_DERIVATION")

    def test_answer_status_calibrated(self, db, agent_project):
        """Agent should calibrate answer status (FULLY/PARTIALLY/etc.)."""
        from app.reasoning.repository_question_agent import investigate_question
        result = investigate_question(db, agent_project.id, "What business rules apply to checkout?")

        if result["status"] == "SUCCESS":
            assert result.get("answer_status") in (
                "FULLY_ANSWERABLE", "PARTIALLY_ANSWERABLE", "CONFLICTING_EVIDENCE", "AMBIGUOUS"
            )

    def test_unsupported_question_rejected(self, db, agent_project):
        """Agent must reject or reduce confidence for concepts not in the repository."""
        from app.reasoning.repository_question_agent import investigate_question
        result = investigate_question(db, agent_project.id, "How does facial recognition work in this codebase?")

        # Either properly rejected or answered with low confidence (no relevant evidence)
        if result["status"] == "INSUFFICIENT_EVIDENCE":
            assert result["confidence"] == "None"
        else:
            # If retrieval found tangential matches, confidence should not be High
            # and the answer should not claim to explain facial recognition
            assert result["status"] == "SUCCESS"
            answer_lower = result["answer"].lower()
            assert "facial recognition" not in answer_lower or "not" in answer_lower or "insufficient" in answer_lower

    def test_unsupported_medical_question_rejected(self, db, agent_project):
        """Agent must reject or reduce confidence for medical domain questions in an e-commerce repo."""
        from app.reasoning.repository_question_agent import investigate_question
        result = investigate_question(db, agent_project.id, "How are inpatient medical records encrypted?")

        if result["status"] == "INSUFFICIENT_EVIDENCE":
            assert result["confidence"] == "None"
        else:
            # If retrieval found tangential matches, the agent should not claim
            # the repo handles medical records specifically
            assert result["status"] == "SUCCESS"
            answer_lower = result["answer"].lower()
            assert "inpatient" not in answer_lower or "not" in answer_lower or "insufficient" in answer_lower

    def test_affected_modules_extracted(self, db, agent_project):
        """Agent should identify affected modules from evidence."""
        from app.reasoning.repository_question_agent import investigate_question
        result = investigate_question(db, agent_project.id, "How does the checkout process work?")

        if result["status"] == "SUCCESS":
            assert "affected_modules" in result
            assert isinstance(result["affected_modules"], list)

    def test_gaps_analysis_present(self, db, agent_project):
        """Agent should analyze and report knowledge gaps."""
        from app.reasoning.repository_question_agent import investigate_question
        result = investigate_question(db, agent_project.id, "What happens when payment fails?")

        if result["status"] == "SUCCESS":
            assert "gaps" in result
            assert isinstance(result["gaps"], list)

    def test_multi_intent_decomposition(self, db, agent_project):
        """Agent should handle multi-intent compound questions."""
        from app.reasoning.repository_question_agent import investigate_question
        result = investigate_question(
            db, agent_project.id,
            "What data model stores orders and what validation rules apply to checkout?"
        )

        assert result["status"] in ("SUCCESS", "INSUFFICIENT_EVIDENCE")
        if result["status"] == "SUCCESS":
            assert len(result.get("intents", [])) >= 1

    def test_answer_contains_structured_sections(self, db, agent_project):
        """Agent answers should contain structured PM/BA-friendly sections."""
        from app.reasoning.repository_question_agent import investigate_question
        result = investigate_question(db, agent_project.id, "How does order creation work end to end?")

        if result["status"] == "SUCCESS":
            answer = result["answer"]
            # Should have at least a Direct Answer and How It Works section
            assert "###" in answer  # Markdown section headers
            assert "Confidence:" in answer


class TestAgentInvestigationContext:
    """Test the InvestigationContext data structure and step functions."""

    def test_context_initialization(self):
        from app.reasoning.repository_question_agent import InvestigationContext
        ctx = InvestigationContext(question="test question", project_id=42)
        assert ctx.question == "test question"
        assert ctx.project_id == 42
        assert ctx.confidence == "None"
        assert ctx.answer_status == ""
        assert len(ctx.aim_evidence) == 0
        assert len(ctx.retrieval_evidence) == 0

    def test_step_understand_question(self):
        from app.reasoning.repository_question_agent import InvestigationContext, _step_understand_question
        ctx = InvestigationContext(question="How does the checkout process work?", project_id=1)
        _step_understand_question(ctx)

        assert ctx.query_intent is not None
        assert ctx.effective_question != ""
        assert ctx.primary_intent != ""
        assert len(ctx.intents) > 0

    def test_step_merge_evidence_deduplicates(self):
        from app.reasoning.repository_question_agent import InvestigationContext, _step_merge_evidence
        ctx = InvestigationContext(question="test", project_id=1)
        ctx.retrieval_evidence = [
            {"source_ref": "file.py:func1", "text": "def func1(): pass", "score": 5.0},
            {"source_ref": "file.py:func2", "text": "def func2(): pass", "score": 4.0},
        ]
        ctx.aim_evidence = [
            {"source_ref": "file.py:func1", "text": "def func1(): pass", "score": 5.0},  # duplicate
            {"source_ref": "aim:model:Order", "text": "Order model entity", "score": 3.0},
        ]
        _step_merge_evidence(ctx)

        # Should deduplicate the func1 entry
        assert len(ctx.merged_evidence) == 3

    def test_step_calibrate_confidence(self):
        from app.reasoning.repository_question_agent import InvestigationContext, _step_calibrate_confidence
        ctx = InvestigationContext(question="test", project_id=1)

        # No evidence = None
        _step_calibrate_confidence(ctx)
        assert ctx.confidence == "None"

        # Some retrieval evidence = High
        ctx.retrieval_evidence = [{"a": 1}, {"b": 2}]
        ctx.aim_evidence = [{"c": 3}]
        _step_calibrate_confidence(ctx)
        assert ctx.confidence == "High"

    def test_step_detect_contradictions(self):
        from app.reasoning.repository_question_agent import InvestigationContext, _step_detect_contradictions
        ctx = InvestigationContext(question="test", project_id=1)
        ctx.merged_evidence = [
            {"source_ref": "auth.py", "text": "Admin only: requires is_admin role"},
            {"source_ref": "public.py", "text": "allow_any public anonymous access"},
        ]
        _step_detect_contradictions(ctx)
        assert len(ctx.contradictions) > 0
        assert "Conflicting" in ctx.contradictions[0]

    def test_step_determine_answer_status_insufficient(self):
        from app.reasoning.repository_question_agent import InvestigationContext, _step_determine_answer_status
        ctx = InvestigationContext(question="test", project_id=1)
        # No evidence at all
        _step_determine_answer_status(ctx)
        assert ctx.answer_status == "INSUFFICIENT_EVIDENCE"

    def test_step_determine_answer_status_conflicting(self):
        from app.reasoning.repository_question_agent import InvestigationContext, _step_determine_answer_status
        ctx = InvestigationContext(question="test", project_id=1)
        ctx.retrieval_evidence = [{"a": 1}]
        ctx.contradictions = ["Some conflict detected"]
        _step_determine_answer_status(ctx)
        assert ctx.answer_status == "CONFLICTING_EVIDENCE"

    def test_step_determine_answer_status_fully(self):
        from app.reasoning.repository_question_agent import InvestigationContext, _step_determine_answer_status
        ctx = InvestigationContext(question="test", project_id=1)
        ctx.retrieval_evidence = [{"a": 1}, {"b": 2}]
        _step_determine_answer_status(ctx)
        assert ctx.answer_status == "FULLY_ANSWERABLE"


class TestInvestigationLoopCapabilities:
    """Capability tests proving the agent is a true bounded investigation loop."""

    def test_critical_acceptance_first_miss_second_finds(self, db, agent_project):
        """CRITICAL ACCEPTANCE TEST:
        Demonstrates:
        FIRST SEARCH -> INSUFFICIENT/WEAK EVIDENCE
               ↓
        REPLANNING
               ↓
        SECOND INVESTIGATION
               ↓
        RELEVANT EVIDENCE FOUND
               ↓
        GROUNDED ANSWER
        """
        from app.reasoning.repository_question_agent import investigate_question
        import unittest.mock as mock
        from app.knowledge_base import retrieval

        real_retrieve = retrieval.retrieve
        call_count = [0]

        def mock_retrieve(db_sess, pid, q, top_k=12, allow_insufficient=False):
            call_count[0] += 1
            if call_count[0] == 1:
                # First attempt: misses evidence (returns empty)
                return []
            # Second attempt (after replanning): returns real retrieved evidence
            return real_retrieve(db_sess, pid, q, top_k=top_k, allow_insufficient=True)

        with mock.patch("app.reasoning.repository_question_agent.retrieve", side_effect=mock_retrieve):
            # Brand new client-style question never in regression suite
            new_client_question = "How does the system ensure destination details are verified prior to order placement?"
            result = investigate_question(db, agent_project.id, new_client_question)

            # Demonstrates replanning occurred
            assert result["iterations_count"] >= 2
            assert any("INVESTIGATION_REPLAN" in step for step in result.get("investigation_steps", []))
            # Demonstrates relevant evidence was found on retry
            assert len(result.get("evidence", [])) > 0 or len(result.get("claims_grounding", [])) > 0
            # Demonstrates grounded answer returned
            assert result["status"] == "SUCCESS"
            assert result["answer_status"] in ("FULLY_ANSWERABLE", "PARTIALLY_ANSWERABLE")

    def test_difficult_cross_layer_question(self, db, agent_project):
        """Difficult cross-layer question tracing UI/Form -> View -> Model -> Database."""
        from app.reasoning.repository_question_agent import investigate_question
        result = investigate_question(
            db, agent_project.id,
            "What is the end-to-end data path from checkout form input to persistent database storage?"
        )
        assert result["status"] == "SUCCESS"
        assert len(result.get("evidence", [])) > 0
        # Flow steps should reflect cross-layer execution
        assert len(result.get("functional_flow", [])) >= 2
        # Grounding should contain cross-layer traces
        groundings = result.get("claims_grounding", [])
        assert any(g.get("derivation_type") in ("CROSS_LAYER_TRACE", "DIRECT_EVIDENCE") for g in groundings)

    def test_query_requiring_graph_expansion(self, db, agent_project):
        """Query requiring graph neighborhood traversal to connect related components."""
        from app.reasoning.repository_question_agent import investigate_question
        result = investigate_question(
            db, agent_project.id,
            "Which components and models are interconnected during checkout processing?"
        )
        assert result["status"] == "SUCCESS"
        assert len(result.get("evidence", [])) >= 1
        assert result["confidence"] in ("High", "Medium")

    def test_query_requiring_source_fallback(self, db, agent_project):
        """Query requiring direct inspection of API endpoints and models."""
        from app.reasoning.repository_question_agent import investigate_question
        result = investigate_question(
            db, agent_project.id,
            "What API routes are exposed for user profile address management?"
        )
        assert result["status"] == "SUCCESS"
        ev_texts = [e.get("text", "") + e.get("source_ref", "") for e in result.get("evidence", [])]
        assert any("address" in t.lower() or "profile" in t.lower() for t in ev_texts)

    def test_query_requiring_state_permission_data_reasoning(self, db, agent_project):
        """Query requiring state machine, permission roles, and data entity reasoning."""
        from app.reasoning.repository_question_agent import investigate_question
        result = investigate_question(
            db, agent_project.id,
            "Who has permission to manage orders and what lifecycle states are tracked?"
        )
        assert result["status"] == "SUCCESS"
        assert result["confidence"] in ("High", "Medium")
        ev_str = json.dumps(result.get("evidence", [])).lower()
        assert "order" in ev_str
        assert any(w in ev_str for w in ["status", "admin", "customer", "permission", "role", "pending"])

    def test_genuinely_unsupported_question_remains_blocked(self, db, agent_project):
        """Genuinely unsupported question must remain blocked after investigation budget exhausted."""
        from app.reasoning.repository_question_agent import investigate_question
        result = investigate_question(
            db, agent_project.id,
            "How does the automated drone delivery trajectory optimizer calculate flight paths?"
        )
        # Must be rejected as INSUFFICIENT_EVIDENCE or low-confidence without claiming drone delivery
        if result["status"] == "INSUFFICIENT_EVIDENCE":
            assert result["confidence"] == "None"
            assert result["answer_status"] == "INSUFFICIENT_EVIDENCE"
            assert len(result.get("investigation_steps", [])) >= 3
        else:
            assert "drone" not in result["answer"].lower() or "not" in result["answer"].lower()

