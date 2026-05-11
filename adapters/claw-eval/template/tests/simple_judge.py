"""
Simple Claw-Eval Judge - Simplified version for validation purposes.
Checks if the answer contains key information points without requiring complex LLM evaluation.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any


def load_answer() -> str:
    """Load the agent's answer from /workspace/answer.txt."""
    answer_path = Path("/workspace/answer.txt")
    if not answer_path.exists():
        return ""
    return answer_path.read_text(encoding="utf-8").strip()


def save_agent_output(answer: str, ground_truth: Dict[str, Any]) -> None:
    """Save the agent's output to job logs for review."""
    output_path = Path("/logs/agent_output.json")
    output_data = {
        "task_id": ground_truth["task_id"],
        "task_name": ground_truth["task_name"],
        "agent_answer": answer,
        "reference_solution": ground_truth["reference_solution"],
        "task_prompt": ground_truth["question"]
    }
    output_path.write_text(json.dumps(output_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Agent output saved to: {output_path}")


def check_key_points(answer: str, reference: str) -> tuple[float, list[str], list[str]]:
    """
    Simple keyword matching check to verify if answer contains key points from reference.
    Returns (score: float, matched_points: list, missing_points: list)
    """
    # Extract key points from reference solution (split by lines/numbers)
    reference_points = []
    for line in reference.split('\n'):
        line = line.strip()
        if line and (line[0].isdigit() or line.startswith('-')):
            # Remove leading numbers/dashes
            point = line.lstrip('0123456789.- ').strip()
            if point and len(point) > 5:
                reference_points.append(point)
    
    if not reference_points:
        # If no structured points, do simple substring check
        if len(answer) > 100 and answer != "":
            return 0.7, ["Answer provided"], []
        else:
            return 0.0, [], ["No valid answer provided"]
    
    # Check each key point
    matched = []
    missing = []
    answer_lower = answer.lower()
    
    for point in reference_points:
        point_lower = point.lower()
        # Split into keywords, check if 70% of keywords are present
        keywords = [k for k in point_lower.split() if len(k) > 2]
        if not keywords:
            continue
            
        matched_keywords = sum(1 for k in keywords if k in answer_lower)
        if matched_keywords / len(keywords) >= 0.7:
            matched.append(point)
        else:
            missing.append(point)
    
    # Calculate score
    if not reference_points:
        score = 1.0 if len(answer) > 100 else 0.0
    else:
        score = len(matched) / len(reference_points)
    
    return score, matched, missing


def main():
    """Simple judge entry point."""
    Path("/logs/verifier").mkdir(parents=True, exist_ok=True)

    # Load ground truth
    ground_truth_path = Path("/tests/ground_truth.json")
    if not ground_truth_path.exists():
        print("ERROR: /tests/ground_truth.json not found")
        Path("/logs/verifier/reward.txt").write_text("0")
        return

    ground_truth = json.loads(ground_truth_path.read_text(encoding="utf-8"))
    task_id = ground_truth["task_id"]
    task_name = ground_truth["task_name"]
    
    print(f"=== Evaluating Task: {task_id} - {task_name} ===")
    
    # Load and save agent's answer
    answer = load_answer()
    save_agent_output(answer, ground_truth)
    
    if not answer:
        print("ERROR: Agent did not produce any output")
        Path("/logs/verifier/reward.txt").write_text("0")
        score = 0.0
        matched = []
        missing = ["No answer provided"]
    else:
        print(f"Agent output length: {len(answer)} characters")
        print("-" * 80)
        print(f"Answer preview:\n{answer[:500]}{'...' if len(answer) > 500 else ''}")
        print("-" * 80)
        
        # Simple scoring based on key points matching
        reference = ground_truth.get("reference_solution", "")
        score, matched, missing = check_key_points(answer, reference)
    
    # Determine pass/fail (>= 0.6 is pass)
    passed = score >= 0.6
    reward = 1 if passed else 0
    
    # Write reward
    Path("/logs/verifier/reward.txt").write_text(str(reward))
    
    # Write detailed results
    details = {
        "task_id": task_id,
        "task_name": task_name,
        "score": score,
        "passed": passed,
        "reward": reward,
        "matched_key_points": matched,
        "missing_key_points": missing,
        "agent_answer_length": len(answer),
        "evaluation_method": "simple keyword matching"
    }
    
    Path("/logs/verifier/grading_details.json").write_text(
        json.dumps(details, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    
    # Print results
    print(f"\n=== Evaluation Results ===")
    print(f"Score: {score:.2f}/1.0")
    print(f"Result: {'PASS' if passed else 'FAIL'}")
    
    if matched:
        print(f"\n✓ Matched key points ({len(matched)}):")
        for point in matched:
            print(f"  - {point[:80]}{'...' if len(point) > 80 else ''}")
    
    if missing:
        print(f"\n✗ Missing key points ({len(missing)}):")
        for point in missing:
            print(f"  - {point[:80]}{'...' if len(point) > 80 else ''}")
    
    print(f"\nDetailed results saved to /logs/verifier/grading_details.json")
    print(f"Full agent output saved to /logs/agent_output.json")


if __name__ == "__main__":
    main()
