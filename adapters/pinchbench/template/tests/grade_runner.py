"""
Automated grading runner for PinchBench tasks.
Generated automatically for each task.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

# === Harbor adaptation layer ===
WORKSPACE = Path("/workspace")
LOG_DIR = Path("/logs/verifier")
LOG_DIR.mkdir(parents=True, exist_ok=True)

def adapt_transcript() -> list[dict]:
    """
    Adapt Harbor's ATIF format to PinchBench transcript format.
    Currently returns empty list as most PinchBench grade functions only check workspace files.
    """
    # TODO: Implement full transcript conversion if needed for specific tasks
    return []

def main():
    try:
        # Run the grade function
        scores = grade(transcript=adapt_transcript(), workspace_path=WORKSPACE)
        
        # Calculate mean score
        if not scores:
            mean_score = 0.0
        else:
            mean_score = sum(scores.values()) / len(scores)
        
        # Write outputs
        (LOG_DIR / "automated_score.txt").write_text(str(mean_score))
        
        details = {
            "task_id": "$$TASK_ID$$",
            "scores": scores,
            "mean_score": mean_score,
        }
        (LOG_DIR / "automated_details.json").write_text(json.dumps(details, indent=2))
        
        print(f"Automated grading completed. Score: {mean_score:.2f}")
        return 0
    except Exception as e:
        print(f"Automated grading failed: {e}")
        (LOG_DIR / "automated_score.txt").write_text("0.0")
        return 1

if __name__ == "__main__":
    sys.exit(main())
