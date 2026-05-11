#!/usr/bin/env python3
"""
LLM judge grader for PinchBench tasks - Anthropic 版本
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from anthropic import Anthropic

# === Task-specific rubric (extracted from PinchBench task) ===
RUBRIC = """$$RUBRIC$$"""

# === Judge configuration ===
TASK_ID = "$$TASK_ID$$"
LOG_DIR = Path("/logs/verifier")
LOG_DIR.mkdir(parents=True, exist_ok=True)

def clean_env():
    """Clean up empty environment variables that break Anthropic client."""
    for var in ("ANTHROPIC_BASE_URL",):
        if var in os.environ and not os.environ[var]:
            del os.environ[var]

def collect_agent_output() -> str:
    """Collect all relevant agent output from workspace."""
    output = []
    workspace = Path("/workspace")
    
    # Read all text files in workspace
    for file in workspace.glob("*.txt"):
        try:
            content = file.read_text()
            output.append(f"=== File: {file.name} ===\n{content}\n")
        except Exception:
            pass
    
    for file in workspace.glob("*.md"):
        try:
            content = file.read_text()
            output.append(f"=== File: {file.name} ===\n{content}\n")
        except Exception:
            pass
    
    if not output:
        return "NO OUTPUT FOUND IN WORKSPACE"
    
    return "\n".join(output)

def grade_with_anthropic(rubric: str, agent_output: str) -> tuple[float, dict]:
    """Grade agent output using Anthropic LLM."""
    clean_env()
    
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    model_name = os.getenv("LLM_JUDGE_MODEL", "claude-3-5-sonnet-20241022")
    
    prompt = f"""You are an impartial judge evaluating an AI agent's performance on a task.

## Evaluation Rubric
{rubric}

## Agent Output
{agent_output}

## Instructions
1. Carefully evaluate the agent's output against the rubric
2. Assign a score for each criterion (0.0 to 1.0)
3. Calculate a weighted total score
4. Return only a valid JSON object with this structure:
{{
    "criterion_scores": {{
        "criterion_name_1": 0.9,
        "criterion_name_2": 0.8,
        ...
    }},
    "total_score": 0.85,
    "explanation": "Brief explanation of scoring"
}}

Do not include any other text outside the JSON object.
"""
    
    response = client.messages.create(
        model=model_name,
        max_tokens=1024,
        temperature=0.1,
        messages=[{"role": "user", "content": prompt}]
    )
    
    try:
        result = json.loads(response.content[0].text.strip())
        total_score = float(result.get("total_score", 0.0))
        return total_score, result
    except json.JSONDecodeError:
        print(f"Failed to parse judge response: {response.content[0].text}")
        return 0.0, {"error": "Invalid JSON response"}

def main():
    try:
        agent_output = collect_agent_output()
        total_score, details = grade_with_anthropic(RUBRIC, agent_output)
        
        # Write outputs
        (LOG_DIR / "judge_score.txt").write_text(str(total_score))
        
        full_details = {
            "task_id": TASK_ID,
            "rubric": RUBRIC,
            "agent_output": agent_output,
            "judge_details": details,
            "total_score": total_score,
        }
        (LOG_DIR / "judge_details.json").write_text(json.dumps(full_details, indent=2))
        
        print(f"LLM judge grading completed. Score: {total_score:.2f}")
        return 0
    except Exception as e:
        print(f"LLM judge grading failed: {e}")
        (LOG_DIR / "judge_score.txt").write_text("0.0")
        return 1

if __name__ == "__main__":
    sys.exit(main())
