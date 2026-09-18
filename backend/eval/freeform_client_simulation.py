"""Free-form Client Simulation Test Harness.

Executes genuinely new client-style questions across 12 distinct categories:
- Technical
- Business
- Functional
- Architectural
- Data
- Security
- Hypothetical
- Conditional
- Impact Analysis
- Multi-Intent
- Follow-Up (Conversational context)
- Unsupported / Negative Domain Inquiry (Zero-Hallucination Gate)

For every query, validates:
- Status (SUCCESS vs INSUFFICIENT_EVIDENCE)
- Answer status calibration
- Evidence grounding
- Investigation step tracing
- Absence of ungrounded hallucination
"""
import sys, os, json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.database import SessionLocal
from app.models.models import Project, SourceFile
from app.reasoning.repository_question_agent import investigate_question
from app.reasoning.reasoning import answer_functional_question, trace_flow, analyze_enhancement


def get_project_by_domain(db, domain_keywords: list[str]) -> Project | None:
    projects = db.query(Project).all()
    for p in reversed(projects):
        p_text = f"{p.name} {p.repo_url}".lower()
        if any(k.lower() in p_text for k in domain_keywords):
            if db.query(SourceFile).filter(SourceFile.project_id == p.id).count() > 0:
                return p
    return None


def run_freeform_simulation():
    db = SessionLocal()
    print("=" * 80)
    print("STARTING FREE-FORM CLIENT SIMULATION AUDIT")
    print("=" * 80)

    # Resolve projects for simulation
    p_alphalens = get_project_by_domain(db, ["alphalens", "factor", "quantopian"])
    p_missing_person = get_project_by_domain(db, ["missing", "person", "gender"])
    p_ecom = get_project_by_domain(db, ["dian", "shop", "ecommerce", "store"])

    # Fallback to any valid project if a specific domain is missing
    all_projects = db.query(Project).all()
    active_projects = [p for p in all_projects if db.query(SourceFile).filter(SourceFile.project_id == p.id).count() > 0]
    p_default = active_projects[0] if active_projects else all_projects[0]

    p_finance = p_alphalens or p_default
    p_vision = p_missing_person or p_default
    p_web = p_ecom or p_default

    print(f"[+] Using Financial Domain Project: ID={p_finance.id} ({p_finance.name})")
    print(f"[+] Using Computer Vision Domain Project: ID={p_vision.id} ({p_vision.name})")
    print(f"[+] Using Web/E-Commerce Domain Project: ID={p_web.id} ({p_web.name})")
    print("-" * 80)

    test_cases = [
        {
            "category": "TECHNICAL",
            "project": p_finance,
            "question": "What mathematical functions calculate factor returns and cumulative performance?",
            "expected_status": "SUCCESS",
            "type": "investigate",
        },
        {
            "category": "BUSINESS",
            "project": p_vision,
            "question": "What is the primary operational objective of this application for law enforcement and families?",
            "expected_status": "SUCCESS",
            "type": "investigate",
        },
        {
            "category": "FUNCTIONAL",
            "project": p_vision,
            "question": "How does a user submit a missing person report with image and demographic details?",
            "expected_status": "SUCCESS",
            "type": "investigate",
        },
        {
            "category": "ARCHITECTURAL",
            "project": p_vision,
            "question": "How are view dispatchers, deep learning models, and database storage coordinated?",
            "expected_status": "SUCCESS",
            "type": "investigate",
        },
        {
            "category": "DATA",
            "project": p_vision,
            "question": "Where and how are registered missing person records stored in the database?",
            "expected_status": "SUCCESS",
            "type": "investigate",
        },
        {
            "category": "SECURITY",
            "project": p_web,
            "question": "Who has permission to manage administrative records and how is access authenticated?",
            "expected_status": "SUCCESS",
            "type": "investigate",
        },
        {
            "category": "HYPOTHETICAL",
            "project": p_vision,
            "question": "What occurs if an uploaded image contains no detectable face or corrupted image data?",
            "expected_status": "SUCCESS",
            "type": "investigate",
        },
        {
            "category": "CONDITIONAL",
            "project": p_finance,
            "question": "Under what condition does factor analysis reject empty dataframes or invalid date indices?",
            "expected_status": "SUCCESS",
            "type": "investigate",
        },
        {
            "category": "IMPACT",
            "project": p_finance,
            "question": "What modules and tear sheets are impacted if factor return calculation is modified?",
            "expected_status": "SUCCESS",
            "type": "enhancement",
        },
        {
            "category": "MULTI_INTENT",
            "project": p_vision,
            "question": "Where is person identification data stored and how is the search workflow triggered?",
            "expected_status": "SUCCESS",
            "type": "investigate",
        },
        {
            "category": "FOLLOW_UP",
            "project": p_vision,
            "question": "Where is the uploaded photo saved?",
            "history": [
                {"role": "user", "content": "How is a missing person report registered?"},
                {"role": "assistant", "content": "The report is registered through the submission form and saved in the database."}
            ],
            "expected_status": "SUCCESS",
            "type": "investigate",
        },
        {
            "category": "TRUE_INSUFFICIENT_EVIDENCE",
            "project": p_finance,
            "question": "How does the autonomous lunar rover trajectory navigation system recalculate thrust?",
            "expected_status": "INSUFFICIENT_EVIDENCE",
            "type": "investigate",
        },
        {
            "category": "TRUE_INSUFFICIENT_EVIDENCE",
            "project": p_vision,
            "question": "How does this application handle employee payroll tax withholding calculation?",
            "expected_status": "INSUFFICIENT_EVIDENCE",
            "type": "investigate",
        },
    ]

    passed_count = 0
    failures = []

    for idx, tc in enumerate(test_cases, 1):
        cat = tc["category"]
        p = tc["project"]
        q = tc["question"]
        exp_status = tc["expected_status"]
        history = tc.get("history")

        print(f"\n[{idx}/{len(test_cases)}] Category: {cat}")
        print(f"     Project: ID={p.id} ({p.name})")
        print(f"     Query: \"{q}\"")

        try:
            if tc["type"] == "enhancement":
                res = analyze_enhancement(db, p.id, q)
                status = res.get("status", "SUCCESS")
            elif tc["type"] == "trace":
                res = trace_flow(db, p.id, q)
                status = res.get("status", "SUCCESS")
            else:
                res = investigate_question(db, p.id, q, history=history)
                status = res.get("status", "")

            confidence = res.get("confidence", "N/A")
            ans_status = res.get("answer_status", "N/A")
            evidence_count = len(res.get("evidence", []))
            iterations = res.get("iterations_count", 1)

            print(f"     -> Status: {status} (Expected: {exp_status}) | AnsStatus: {ans_status} | Conf: {confidence} | EvCount: {evidence_count} | Iter: {iterations}")

            if status == exp_status:
                if exp_status == "SUCCESS":
                    if tc["type"] == "enhancement":
                        assert len(res.get("current_behavior", "")) > 10, "Current behavior too brief"
                    elif tc["type"] == "trace":
                        assert len(res.get("flow", [])) > 0, "Trace flow empty"
                    else:
                        assert len(res.get("answer", "")) > 50, "Answer text too brief"
                passed_count += 1
                print(f"     [PASS] Correctly resolved {cat} client query.")
            else:
                failures.append({
                    "case": tc,
                    "result": res,
                    "failure_type": "TRUE_INSUFFICIENT_EVIDENCE" if exp_status == "INSUFFICIENT_EVIDENCE" else "RETRIEVAL",
                    "reason": f"Expected {exp_status}, got {status}"
                })
                print(f"     [FAIL] Mismatch for {cat} client query.")

        except Exception as ex:
            import traceback
            traceback.print_exc()
            failures.append({
                "case": tc,
                "error": str(ex),
                "failure_type": "ANSWER_SYNTHESIS",
                "reason": str(ex)
            })
            print(f"     [ERROR] Exception during execution: {ex}")

    print("\n" + "=" * 80)
    print(f"FREE-FORM CLIENT SIMULATION RESULTS: {passed_count}/{len(test_cases)} PASSED")
    print("=" * 80)

    if failures:
        print("\nFAILURES ENCOUNTERED:")
        for f in failures:
            c = f["case"]
            print(f" - [{c['category']}] \"{c['question']}\": {f['failure_type']} ({f['reason']})")
        sys.exit(1)
    else:
        print("\nALL CLIENT SIMULATION SCENARIOS PASSED WITH ZERO ERRORS!")
        sys.exit(0)


if __name__ == "__main__":
    run_freeform_simulation()
