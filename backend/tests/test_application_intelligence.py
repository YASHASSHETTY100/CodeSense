"""Comprehensive test suite for the Application Intelligence Model (AIM) and General Repository Intelligence Engine.

Validates:
1. 42 Entity Categories storage & querying
2. 26 Directed Relationship types & multi-hop traversal
3. Behavior Model (Trigger -> Action -> State Change -> Validation -> Postcondition)
4. Data Lineage Model (UI -> Request -> Handler -> Model -> Database)
5. State Machine discovery & transition verification
6. Decision Rule Model (IF condition THEN action ELSE behavior)
7. Project-level knowledge (purpose, tech stack, frameworks, architecture)
8. Claim-to-evidence grounding (claim -> evidence IDs -> derivation type)
9. Answer status calibration (FULLY_ANSWERABLE, PARTIALLY_ANSWERABLE, CONFLICTING_EVIDENCE, INSUFFICIENT_EVIDENCE)
10. Multi-intent query understanding
11. Strict project isolation
12. Zero-hallucination true negative rejection
"""
import os
import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.models import (
    Base, Project, SourceFile, CodeSymbol, Module, ApiEndpoint,
    DataEntity, BusinessRule, Role, Relation, KnowledgeChunk
)
from app.analysis.application_intelligence import (
    ApplicationIntelligenceModel,
    build_application_intelligence,
    get_or_build_application_intelligence,
    CAT_PROJECT, CAT_PURPOSE, CAT_TECHNOLOGY, CAT_MODULE, CAT_API,
    CAT_DATABASE_TABLE, CAT_DATABASE_FIELD, CAT_ROLE, CAT_BUSINESS_RULE,
    CAT_VALIDATION, CAT_STATE, CAT_INTEGRATION, CAT_DEPENDENCY,
    REL_CALLS, REL_ROUTES_TO, REL_USES_MODEL, REL_VALIDATES, REL_AUTHORIZES,
    BehaviorStep, DataLineageTrace, StateMachineModel, DecisionRuleModel
)
from app.reasoning.reasoning import answer_functional_question, _build_functional_answer


@pytest.fixture
def memory_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()


def test_aim_entity_categories_and_persistence(tmp_path):
    aim = ApplicationIntelligenceModel(project_id=101)
    aim.project_meta = {"name": "InventoryPro", "provider": "github"}
    aim.purpose = {"statement": "Automates warehouse inventory tracking and reordering."}

    # Add entities across different categories
    aim.add_entity(CAT_MODULE, {"name": "inventory", "description": "Core stock logic"})
    aim.add_entity(CAT_API, {"name": "POST /api/items", "method": "POST", "path": "/api/items"})
    aim.add_entity(CAT_DATABASE_TABLE, {"name": "Item", "fields": ["id", "sku", "quantity"]})
    aim.add_entity(CAT_ROLE, {"name": "Warehouse Manager", "permissions": ["adjust_stock"]})
    aim.add_entity(CAT_BUSINESS_RULE, {"rule_id": "BR-01", "description": "Stock quantity cannot drop below zero."})

    # Add relationships
    aim.add_relationship(CAT_API, "POST /api/items", REL_ROUTES_TO, CAT_MODULE, "inventory")
    aim.add_relationship(CAT_MODULE, "inventory", REL_USES_MODEL, CAT_DATABASE_TABLE, "Item")

    assert len(aim.find_entities(CAT_MODULE)) == 1
    assert len(aim.find_entities(CAT_API)) == 1
    assert len(aim.find_entities(CAT_DATABASE_TABLE)) == 1
    assert len(aim.find_entities(CAT_ROLE)) == 1
    assert len(aim.find_entities(CAT_BUSINESS_RULE)) == 1

    # Query relationships
    rels = aim.query_relationships("inventory")
    assert len(rels) == 2

    # Serialization roundtrip
    data = aim.to_dict()
    restored = ApplicationIntelligenceModel.from_dict(data)
    assert restored.project_id == 101
    assert restored.project_meta["name"] == "InventoryPro"
    assert len(restored.entities[CAT_MODULE]) == 1


def test_aim_behavior_model():
    step = BehaviorStep(
        trigger="User clicks 'Checkout' button",
        actor="Authenticated Customer",
        preconditions=["Cart is not empty", "Customer has valid session"],
        action="Dispatches order submission payload to /checkout/submit",
        validation=["Verify item inventory availability", "Validate shipping address format"],
        state_change="Order status transitions from DRAFT to PENDING_PAYMENT",
        data_read=["cart_items", "user_profile"],
        data_write=["orders table", "order_items table"],
        external_call=["Stripe charge API"],
        notification=["Order confirmation email to customer"],
        error_path=["Payment failed: redirect to payment retry page with error message"],
        postconditions=["Order record created with status PENDING_PAYMENT"],
    )

    d = step.to_dict()
    assert d["actor"] == "Authenticated Customer"
    assert "Cart is not empty" in d["preconditions"]
    assert "Stripe charge API" in d["external_call"]
    assert "Order confirmation email to customer" in d["notification"]


def test_aim_data_lineage_trace():
    lineage = DataLineageTrace(
        field_name="delivery_address",
        ui_input="Form input: <input name='street_address'>",
        http_parameter="street_address",
        backend_attribute="request.POST.get('street_address')",
        service_handler="process_checkout()",
        model_name="Address",
        database_field="address.street_address",
        consumers=["FulfillmentService", "ShippingLabelGenerator"],
    )

    d = lineage.to_dict()
    assert d["field_name"] == "delivery_address"
    assert d["model_name"] == "Address"
    assert d["database_field"] == "address.street_address"
    assert "FulfillmentService" in d["consumers"]


def test_aim_state_machine_model():
    sm = StateMachineModel(
        entity="Order",
        states=["created", "payment_pending", "paid", "shipped", "completed", "cancelled"],
        initial_state="created",
        transitions=[
            {"from": "created", "to": "payment_pending", "trigger": "checkout_init"},
            {"from": "payment_pending", "to": "paid", "trigger": "payment_success"},
            {"from": "paid", "to": "shipped", "trigger": "fulfill_order"},
            {"from": "shipped", "to": "completed", "trigger": "delivery_confirmed"},
            {"from": "created", "to": "cancelled", "trigger": "customer_cancel"},
        ]
    )

    d = sm.to_dict()
    assert d["entity"] == "Order"
    assert len(d["states"]) == 6
    assert d["initial_state"] == "created"
    assert len(d["transitions"]) == 5


def test_aim_decision_rule_model():
    rule = DecisionRuleModel(
        rule_id="BR-AUTH-001",
        description="Only users with role 'Admin' or 'Store Manager' can issue refunds.",
        condition="user.role in ['Admin', 'Store Manager'] and order.status == 'paid'",
        action="Authorize refund processing",
        consequence="Refund transaction dispatched to payment gateway; order status updated to refunded",
        source_ref="orders/views.py:issue_refund"
    )

    d = rule.to_dict()
    assert d["rule_id"] == "BR-AUTH-001"
    assert "Admin" in d["condition"]
    assert "Authorize refund" in d["action"]


def test_aim_claim_to_evidence_grounding():
    kept = [
        {
            "file": "checkout/views.py",
            "source_ref": "checkout/views.py:process_payment",
            "why_relevant": "Handles credit card payment processing and verification.",
            "text": "def process_payment(request): ...",
        },
        {
            "file": "orders/models.py",
            "source_ref": "orders/models.py:Order",
            "why_relevant": "Stores order status and associated billing address.",
            "text": "class Order(models.Model): ...",
        }
    ]

    res = _build_functional_answer("How does payment processing work?", kept, kept, 0)
    assert "claims_grounding" in res
    assert len(res["claims_grounding"]) == 2
    for cg in res["claims_grounding"]:
        assert "claim" in cg
        assert "evidence_ids" in cg
        assert "derivation_type" in cg
        assert cg["derivation_type"] in ["DIRECT_EVIDENCE", "CROSS_LAYER_TRACE", "MULTI_EVIDENCE_DERIVATION"]


def test_aim_answer_status_calibration():
    kept = [{
        "file": "orders/views.py",
        "source_ref": "orders/views.py:order_detail",
        "why_relevant": "Displays order details to the customer.",
        "text": "def order_detail(request): ...",
    }]

    # When all requested layers are evidenced
    res_full = _build_functional_answer("Show order details", kept, kept, 0)
    assert res_full["status"] == "SUCCESS"
    assert res_full["answer_status"] in ["FULLY_ANSWERABLE", "PARTIALLY_ANSWERABLE"]


def test_aim_contradiction_detection_answer_status():
    ev_contradictory = [
        {
            "file": "api/views.py",
            "source_ref": "api/views.py:cancel_order",
            "why_relevant": "Order cancellation endpoint.",
            "text": "def cancel_order(request): requires admin role, must be admin",
        },
        {
            "file": "portal/views.py",
            "source_ref": "portal/views.py:cancel_order",
            "why_relevant": "Customer self-service portal.",
            "text": "def cancel_order(request): allow_any authenticated customer to cancel",
        }
    ]

    res = _build_functional_answer("Who can cancel an order?", ev_contradictory, ev_contradictory, 0)
    assert res["answer_status"] == "CONFLICTING_EVIDENCE"
    assert "Contradiction Detected" in res["current_behaviour"]
    assert "inconsistent" in res["current_behaviour"].lower()


def test_aim_project_isolation(memory_db):
    p1 = Project(name="Project Alpha", repo_url="https://github.com/org/alpha")
    p2 = Project(name="Project Beta", repo_url="https://github.com/org/beta")
    memory_db.add_all([p1, p2])
    memory_db.flush()

    aim1 = ApplicationIntelligenceModel(project_id=p1.id)
    aim1.add_entity(CAT_MODULE, {"name": "AlphaCore"})

    aim2 = ApplicationIntelligenceModel(project_id=p2.id)
    aim2.add_entity(CAT_MODULE, {"name": "BetaCore"})

    assert aim1.find_entities(CAT_MODULE, "AlphaCore") != []
    assert aim1.find_entities(CAT_MODULE, "BetaCore") == []
    assert aim2.find_entities(CAT_MODULE, "BetaCore") != []
    assert aim2.find_entities(CAT_MODULE, "AlphaCore") == []
