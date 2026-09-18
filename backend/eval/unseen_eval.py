"""Unseen Question Evaluation Harness.

Evaluates repository understanding across multiple domains using an external dataset
without hardcoding question lists or domain mappings in production code.

Metrics Evaluated:
- Answerability Rate
- Evidence Precision
- Evidence Recall
- False-Negative Rate
- Unsupported-Answer Rate (Zero-Hallucination Gate)
- Confidence Calibration
"""
import os, sys, json, re
from typing import Any
from app.models.database import SessionLocal
from app.models.models import Project
from app.reasoning.reasoning import answer_functional_question


def find_project_by_identifier(db, identifier: str) -> Project | None:
    from app.models.models import SourceFile
    projects = db.query(Project).all()
    matching = [
        p for p in reversed(projects)
        if identifier.lower() in (p.repo_url or "").lower() or identifier.lower() in (p.name or "").lower()
    ]
    # Prefer project that has source files
    for p in matching:
        if db.query(SourceFile).filter(SourceFile.project_id == p.id).count() > 0:
            return p
    return matching[0] if matching else None


def run_evaluation(data_path: str = "") -> dict[str, Any]:
    if not data_path:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        data_path = os.path.join(base_dir, "unseen_questions.json")

    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    db = SessionLocal()

    total_supported = 0
    correct_supported = 0
    false_negatives = 0

    total_negative = 0
    correct_negative = 0
    unsupported_leakage = 0

    total_evidence_chunks = 0
    relevant_evidence_chunks = 0

    total_expected_concepts = 0
    recalled_concepts = 0

    high_confidence_total = 0
    high_confidence_calibrated = 0

    detailed_results = []

    print("=" * 80)
    print("CODESENSE UNSEEN QUESTION EVALUATION HARNESS")
    print(f"Dataset: {data_path}")
    print("=" * 80)

    for domain_key, domain_info in data.get("domains", {}).items():
        domain_name = domain_info.get("domain_name", domain_key)
        repo_id = domain_info.get("repo_identifier", "")
        project = find_project_by_identifier(db, repo_id)

        if not project:
            print(f"[-] WARNING: Project matching '{repo_id}' not found in database. Skipping domain.")
            continue

        print(f"\nEvaluating Domain: {domain_name} (Project ID: {project.id}, Name: {project.name})")
        print("-" * 80)

        for q_item in domain_info.get("questions", []):
            qid = q_item["id"]
            question = q_item["question"]
            expected_status = q_item["expected_status"]
            category = q_item.get("category", "")
            expected_concepts = q_item.get("expected_concepts", [])

            res = answer_functional_question(db, project.id, question)
            actual_status = res.get("status", "")
            confidence = res.get("confidence", "None")
            evidence = res.get("evidence", [])
            answer_text = res.get("answer", "")

            is_supported = (expected_status == "SUCCESS")
            is_negative = (expected_status == "INSUFFICIENT_EVIDENCE")

            matched_expected = (actual_status == expected_status)

            if is_supported:
                total_supported += 1
                if actual_status == "SUCCESS":
                    correct_supported += 1
                elif actual_status == "INSUFFICIENT_EVIDENCE":
                    false_negatives += 1

                # Confidence calibration
                if confidence == "High":
                    high_confidence_total += 1
                    if len(evidence) >= 2:
                        high_confidence_calibrated += 1

                # Evidence precision & recall
                def _get_ev_text(ev: dict) -> str:
                    return f"{ev.get('file', '')} {ev.get('symbol', '')} {ev.get('why_relevant', '')} {ev.get('text', '')} {ev.get('source_ref', '')}".lower()

                ev_text_combined = " ".join(_get_ev_text(e) for e in evidence)
                for exp_c in expected_concepts:
                    total_expected_concepts += 1
                    if exp_c.lower() in ev_text_combined or exp_c.lower() in answer_text.lower():
                        recalled_concepts += 1

                for e in evidence:
                    total_evidence_chunks += 1
                    e_text = _get_ev_text(e)
                    if any(c.lower() in e_text for c in expected_concepts) or len(expected_concepts) == 0:
                        relevant_evidence_chunks += 1

            elif is_negative:
                total_negative += 1
                if actual_status == "INSUFFICIENT_EVIDENCE":
                    correct_negative += 1
                else:
                    unsupported_leakage += 1

            status_symbol = "PASS" if matched_expected else "FAIL"
            print(f"[{status_symbol}] ({qid}) {question[:60]:<60} | Exp: {expected_status:<22} Act: {actual_status:<22} Conf: {confidence}")

            detailed_results.append({
                "id": qid,
                "domain": domain_name,
                "question": question,
                "category": category,
                "expected_status": expected_status,
                "actual_status": actual_status,
                "confidence": confidence,
                "evidence_count": len(evidence),
                "pass": matched_expected,
            })

    db.close()

    # Compute Summary Metrics
    ans_rate = (correct_supported / total_supported * 100.0) if total_supported > 0 else 0.0
    fn_rate = (false_negatives / total_supported * 100.0) if total_supported > 0 else 0.0
    unsupported_rate = (unsupported_leakage / total_negative * 100.0) if total_negative > 0 else 0.0
    precision = (relevant_evidence_chunks / total_evidence_chunks * 100.0) if total_evidence_chunks > 0 else 100.0
    recall = (recalled_concepts / total_expected_concepts * 100.0) if total_expected_concepts > 0 else 100.0
    calibration = (high_confidence_calibrated / high_confidence_total * 100.0) if high_confidence_total > 0 else 100.0

    print("\n" + "=" * 80)
    print("EVALUATION SUMMARY & CAPABILITY METRICS")
    print("=" * 80)
    print(f"Supported Questions Evaluated:    {total_supported}")
    print(f"Successfully Answered:           {correct_supported}")
    print(f"Answerability Rate:              {ans_rate:.1f}% (Target: >= 90%)")
    print(f"False Negative Rate:             {fn_rate:.1f}% (Target: < 10%)")
    print("-" * 80)
    print(f"Negative/Unsupported Questions:  {total_negative}")
    print(f"Correctly Blocked:               {correct_negative}")
    print(f"Unsupported Answer Rate:         {unsupported_rate:.1f}% (Target: 0.0% - Strict Zero Hallucination)")
    print("-" * 80)
    print(f"Evidence Precision:              {precision:.1f}%")
    print(f"Evidence Recall:                 {recall:.1f}%")
    print(f"Confidence Calibration:          {calibration:.1f}%")
    print("=" * 80)

    quality_pass = (ans_rate >= 90.0 and fn_rate <= 10.0 and unsupported_rate == 0.0)
    print(f"Overall Quality Gate: {'PASSED [APPROVED]' if quality_pass else 'FAILED'}")
    print("=" * 80)

    return {
        "answerability_rate": ans_rate,
        "false_negative_rate": fn_rate,
        "unsupported_answer_rate": unsupported_rate,
        "evidence_precision": precision,
        "evidence_recall": recall,
        "confidence_calibration": calibration,
        "quality_gate_passed": quality_pass,
        "details": detailed_results,
    }


if __name__ == "__main__":
    path_arg = sys.argv[1] if len(sys.argv) > 1 else ""
    res = run_evaluation(path_arg)
    if not res["quality_gate_passed"]:
        sys.exit(1)
