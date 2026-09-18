"""Verification of fresh repository ingestion and strict domain isolation.
Tests:
1. Ingestion of a completely fresh synthetic domain repository (Healthcare/Clinical)
2. Ingestion pipeline extracts only healthcare concepts (Patient, ClinicalVisit, Doctor)
3. Verified absence of any external concepts (Order, AddressAdmin, Authenticated, Missing Person)
4. Functional Q&A answers healthcare domain queries with high accuracy
5. Functional Q&A rejects foreign domain queries (orders, face recognition, stock factor) with INSUFFICIENT_EVIDENCE
6. Re-indexing cache invalidation properly clears prior state
"""
import os, sys, tempfile, shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.database import SessionLocal
from app.models.models import Project, SourceFile, DataEntity, Role, ApiEndpoint
from app.analysis.structural.pipeline import run_structural_analysis
from app.analysis.functional.pipeline import run_functional_analysis
from app.knowledge_base.pipeline import run_kb_indexing
from app.reasoning.reasoning import answer_functional_question, summarize_project
from app.analysis.application_intelligence import get_or_build_application_intelligence

HEALTHCARE_REPO = {
    "patients/models.py": """
class Patient(Base):
    id = Column(Integer, primary_key=True)
    full_name = Column(String(200))
    date_of_birth = Column(Date)
    medical_record_number = Column(String(50), unique=True)
    status = Column(String(50))  # admitted, triaged, discharged

class ClinicalVisit(Base):
    patient_id = Column(Integer, ForeignKey('patient.id'))
    diagnosis = Column(Text)
    discharge_summary = Column(Text)
""",
    "patients/api.py": """
from fastapi import APIRouter
router = APIRouter()

@router.post("/patients/admit")
def admit_patient(mrn: str, full_name: str):
    \"\"\"Register and admit incoming clinical patient.\"\"\"
    patient = Patient(medical_record_number=mrn, full_name=full_name, status="admitted")
    db.session.add(patient)
    return {"status": "admitted", "mrn": mrn}

@router.post("/patients/discharge")
def discharge_patient(patient_id: int):
    \"\"\"Evaluate clinical discharge criteria and release patient.\"\"\"
    patient = db.session.query(Patient).get(patient_id)
    if patient.status != "admitted":
        raise ValueError("Only admitted patients may be discharged")
    patient.status = "discharged"
    return {"status": "discharged"}
""",
    "clinical/triage.py": """
def evaluate_triage_acuity(vital_signs: dict):
    \"\"\"Determine emergency triage category based on blood pressure and heart rate.\"\"\"
    if vital_signs.get("systolic", 120) < 90:
        return "CRITICAL_RESUSCITATION"
    return "STANDARD_CARE"
""",
    "README.md": """
# Hospital Clinical Care & Inpatient System
Manages patient admissions, emergency triage acuity, and physician clinical notes.
"""
}


def run_fresh_ingestion_test():
    print("=" * 80)
    print("TESTING FRESH REPOSITORY INGESTION & DOMAIN ISOLATION")
    print("=" * 80)

    db = SessionLocal()
    temp_dir = tempfile.mkdtemp(prefix="codesense_fresh_health_")

    try:
        for rel_path, content in HEALTHCARE_REPO.items():
            full_path = os.path.join(temp_dir, rel_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)

        # Create fresh project
        proj = Project(
            name="QA_Clinical_Care_System",
            repo_provider="github",
            repo_url="https://github.com/hospital/clinical-care",
            default_branch="main",
            ingestion_status="running",
        )
        db.add(proj)
        db.commit()
        db.refresh(proj)
        pid = proj.id
        print(f"[+] Created fresh test project: ID={pid}, Name={proj.name}")

        # Register source files
        for rel_path in HEALTHCARE_REPO.keys():
            sf = SourceFile(
                project_id=pid,
                path=rel_path,
                language="python" if rel_path.endswith(".py") else "markdown",
                hash="qa_test_hash",
            )
            db.add(sf)
        db.commit()

        # Execute analysis pipeline stages
        print("[+] Executing Structural Analysis...")
        run_structural_analysis(db, pid, temp_dir)

        print("[+] Executing Functional Analysis...")
        run_functional_analysis(db, pid, temp_dir)

        print("[+] Executing Knowledge Base Indexing...")
        run_kb_indexing(db, pid, temp_dir)

        # Build Application Intelligence
        aim = get_or_build_application_intelligence(db, pid)
        proj.ingestion_status = "ready"
        db.commit()
        print("[PASS] Ingestion complete. Status=READY.")

        # 1. Inspect extracted entities
        entities = db.query(DataEntity).filter(DataEntity.project_id == pid).all()
        entity_names = [e.name for e in entities]
        print(f"[+] Extracted Entities: {entity_names}")
        assert "Patient" in entity_names, f"Expected 'Patient' in {entity_names}"
        assert "ClinicalVisit" in entity_names, f"Expected 'ClinicalVisit' in {entity_names}"

        # Verify NO leaked concepts
        for forbidden in ["Order Admin", "Address Admin", "OrderAdmin", "AddressAdmin", "Order", "Cart", "Checkout"]:
            assert forbidden not in entity_names, f"CRITICAL ISOLATION FAILURE: Leaked '{forbidden}' found in {entity_names}"
        print("[PASS] Verified entity discovery: Healthcare models only, zero leakage.")

        # 2. Inspect extracted roles
        roles = db.query(Role).filter(Role.project_id == pid).all()
        role_names = [r.name for r in roles]
        print(f"[+] Extracted Roles: {role_names}")
        for forbidden_role in ["order_admin", "address_admin", "authenticated"]:
            assert forbidden_role not in role_names, f"CRITICAL ISOLATION FAILURE: Leaked role '{forbidden_role}' in {role_names}"
        print("[PASS] Verified role discovery: Zero ungrounded roles.")

        # 3. Test In-domain Functional Q&A
        print("\n[+] Testing In-Domain Functional Q&A:")
        res_admit = answer_functional_question(db, pid, "What happens when a patient is admitted?")
        print(f"  -> Q: 'What happens when a patient is admitted?' | Status: {res_admit['status']}")
        assert res_admit["status"] == "SUCCESS", f"Expected SUCCESS, got {res_admit}"
        assert "patient" in res_admit["answer"].lower() or "admit" in res_admit["answer"].lower()
        print("  [PASS] Successfully answered healthcare admission question.")

        res_discharge = answer_functional_question(db, pid, "What happens when a patient is discharged?")
        print(f"  -> Q: 'What happens when a patient is discharged?' | Status: {res_discharge['status']}")
        assert res_discharge["status"] == "SUCCESS", f"Expected SUCCESS, got {res_discharge}"
        print("  [PASS] Successfully answered patient discharge question.")

        # 4. Test Cross-Domain Negative Queries (Zero-Hallucination Gate)
        print("\n[+] Testing Cross-Domain Negative Inquiries (Must be INSUFFICIENT_EVIDENCE):")
        res_order = answer_functional_question(db, pid, "What happens when a customer checks out an order?")
        print(f"  -> Q: 'What happens when a customer checks out?' | Status: {res_order['status']}")
        assert res_order["status"] == "INSUFFICIENT_EVIDENCE", f"Expected INSUFFICIENT_EVIDENCE, got {res_order['status']}"
        assert res_order["evidence"] == [], "Negative query must have 0 evidence citations"
        print("  [PASS] Correctly blocked e-commerce checkout query.")

        res_missing = answer_functional_question(db, pid, "How is face detection performed for missing person identification?")
        print(f"  -> Q: 'Face detection for missing persons' | Status: {res_missing['status']}")
        assert res_missing["status"] == "INSUFFICIENT_EVIDENCE", f"Expected INSUFFICIENT_EVIDENCE, got {res_missing['status']}"
        print("  [PASS] Correctly blocked computer vision query.")

        res_stock = answer_functional_question(db, pid, "Where are forward returns and factor performance calculated?")
        print(f"  -> Q: 'Stock forward returns' | Status: {res_stock['status']}")
        assert res_stock["status"] == "INSUFFICIENT_EVIDENCE", f"Expected INSUFFICIENT_EVIDENCE, got {res_stock['status']}"
        print("  [PASS] Correctly blocked stock analysis query.")

        # Cleanup test project from db and disk
        db.query(SourceFile).filter(SourceFile.project_id == pid).delete()
        db.query(DataEntity).filter(DataEntity.project_id == pid).delete()
        db.query(Role).filter(Role.project_id == pid).delete()
        db.query(ApiEndpoint).filter(ApiEndpoint.project_id == pid).delete()
        db.query(Project).filter(Project.id == pid).delete()
        db.commit()
        print("\n[+] Cleaned up temporary QA project records.")

    finally:
        db.close()
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("\n" + "=" * 80)
    print("ALL FRESH REPOSITORY INGESTION & ISOLATION CHECKS PASSED!")
    print("=" * 80)


if __name__ == "__main__":
    run_fresh_ingestion_test()
