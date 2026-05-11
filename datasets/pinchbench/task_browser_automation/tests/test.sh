#!/bin/bash
set -euo pipefail

GRADING_TYPE=$(grep 'grading_type' /task.toml | cut -d'"' -f2)
echo "Running grading for task: $(cat /tests/ground_truth.json | jq -r '.task_id')"
echo "Grading type: $GRADING_TYPE"

# Create logs directory
mkdir -p /logs/verifier

# Run automated grading if needed
if [[ "$GRADING_TYPE" == "automated" || "$GRADING_TYPE" == "hybrid" ]]; then
    echo "Running automated grading..."
    python3 /tests/grade_runner.py
    AUTOMATED_SCORE=$(cat /logs/verifier/automated_score.txt 2>/dev/null || echo "0")
fi

# Run LLM judge grading if needed
if [[ "$GRADING_TYPE" == "llm_judge" || "$GRADING_TYPE" == "hybrid" ]]; then
    echo "Running LLM judge grading..."
    python3 /tests/judge.py
    JUDGE_SCORE=$(cat /logs/verifier/judge_score.txt 2>/dev/null || echo "0")
fi

# Calculate final reward
if [[ "$GRADING_TYPE" == "automated" ]]; then
    FINAL_SCORE=$AUTOMATED_SCORE
elif [[ "$GRADING_TYPE" == "llm_judge" ]]; then
    FINAL_SCORE=$JUDGE_SCORE
elif [[ "$GRADING_TYPE" == "hybrid" ]]; then
    # Average both scores for hybrid grading (using Python for cross-platform compatibility)
    FINAL_SCORE=$(python3 -c "print(f\"{($AUTOMATED_SCORE + $JUDGE_SCORE) / 2:.2f}\")")
else
    FINAL_SCORE=0.0
fi

echo "Final score: $FINAL_SCORE"
echo $FINAL_SCORE > /logs/verifier/reward.txt

# Write grading details
cat > /logs/verifier/grading_details.json << EOF
{
    "task_id": "$(cat /tests/ground_truth.json | jq -r '.task_id')",
    "grading_type": "$GRADING_TYPE",
    "automated_score": $AUTOMATED_SCORE,
    "judge_score": $JUDGE_SCORE,
    "final_score": $FINAL_SCORE,
    "timestamp": "$(date -Iseconds)"
}
EOF

echo "Grading completed successfully"
