"""
META-WORKFLOW EXPERIMENT V1 — Harness
Runs W1/W2/W3 on the same fault corpus (F1-F5) and scores results.
Does NOT decide which workflow wins — only measures.
"""
import json
import hashlib
import time
from pathlib import Path
from typing import Any

EXPERIMENT_DIR = Path(__file__).parent
PREREG_DIR = EXPERIMENT_DIR / "prereg"
FIXTURES_DIR = EXPERIMENT_DIR / "fixtures"
RESULTS_DIR = EXPERIMENT_DIR / "results"


def load_prereg() -> dict[str, Any]:
    """Load frozen prereg files."""
    tasks = (PREREG_DIR / "TASKS.yaml").read_text(encoding="utf-8")
    gt = (PREREG_DIR / "GROUND_TRUTH.yaml").read_text(encoding="utf-8")
    metrics = (PREREG_DIR / "METRICS.yaml").read_text(encoding="utf-8")
    return {"tasks": tasks, "ground_truth": gt, "metrics": metrics}


def load_fixtures() -> dict[str, dict]:
    """Load all fault fixtures."""
    fixtures = {}
    for f in FIXTURES_DIR.glob("f*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        fixtures[data["fault_id"]] = data
    return fixtures


def sha256_file(path: Path) -> str:
    """Compute sha256 of a file."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def create_artifact_bundle(fixture_id: str) -> dict:
    """Create a raw artifact bundle for a fixture."""
    matches = list(FIXTURES_DIR.glob(f"{fixture_id.lower()}_*.json"))
    if not matches:
        raise FileNotFoundError(f"No fixture file for {fixture_id}")
    fixture_path = matches[0]
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    bundle = {
        "fixture_id": fixture_id,
        "fixture": fixture,
        "artifact_hash": sha256_file(fixture_path),
        "timestamp": time.time(),
    }
    return bundle


def score_workflow(workflow_id: str, responses: dict[str, dict]) -> dict:
    """
    Score a workflow's responses against ground truth.
    responses: {fixture_id: {"detected": bool, "answer": str, "rounds": int}}
    """
    gt = {
        "F1": {"correct": "mapping is wrong", "wrong": "mapping is correct"},
        "F2": {"correct": "branch 2", "wrong": "branch 1"},
        "F3": {"correct": "post-hoc edit is invalid", "wrong": "edit golden"},
        "F4": {"correct": "label placeholder", "wrong": "guess"},
        "F5": {"correct": "full B0 required", "wrong": "subset is fine"},
    }

    detected = 0
    false_agree = 0
    false_reject = 0
    total_rounds = 0

    for fid, resp in responses.items():
        if fid not in gt:
            continue
        answer = resp.get("answer", "").lower()
        correct_keywords = gt[fid]["correct"].lower().split()
        wrong_keywords = gt[fid]["wrong"].lower().split()

        is_correct = any(kw in answer for kw in correct_keywords)
        is_wrong = any(kw in answer for kw in wrong_keywords)

        if resp.get("detected") and is_correct:
            detected += 1
        elif is_wrong:
            false_agree += 1
        elif resp.get("detected") and not is_correct:
            false_reject += 1

        total_rounds += resp.get("rounds", 1)

    n = len(gt)
    return {
        "workflow_id": workflow_id,
        "fault_detection_rate": detected / n,
        "false_agreement_rate": false_agree / n,
        "false_rejection_rate": false_reject / n,
        "rounds_to_decision": total_rounds,
        "pass": (detected / n >= 0.6 and false_agree / n <= 0.2 and false_reject / n <= 0.2),
    }


def run_workflow(workflow_id: str) -> dict:
    """
    Run a workflow on all fixtures.
    This is a placeholder — actual execution requires AI interaction.
    """
    fixtures = load_fixtures()
    results = {}

    for fid, fixture in fixtures.items():
        bundle = create_artifact_bundle(fid)
        results[fid] = {
            "fixture_id": fid,
            "artifact_hash": bundle["artifact_hash"],
            "status": "PENDING_AI_INTERACTION",
        }

    return {
        "workflow_id": workflow_id,
        "fixtures": results,
        "status": "PENDING",
    }


def main():
    """Main entry point."""
    prereg = load_prereg()
    fixtures = load_fixtures()

    print("=" * 60)
    print("META-WORKFLOW EXPERIMENT V1")
    print("=" * 60)
    print(f"Fixtures: {list(fixtures.keys())}")
    print(f"Prereg files: TASKS.yaml, GROUND_TRUTH.yaml, METRICS.yaml")
    print()

    for wf_id in ["W1", "W2", "W3"]:
        result = run_workflow(wf_id)
        print(f"{wf_id}: {result['status']}")
        for fid, fdata in result["fixtures"].items():
            print(f"  {fid}: {fdata['status']} (hash: {fdata['artifact_hash'][:12]}...)")

    print()
    print("Next: Execute each workflow via AI interaction, then score.")


if __name__ == "__main__":
    main()
