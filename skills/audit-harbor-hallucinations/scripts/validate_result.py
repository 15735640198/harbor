#!/usr/bin/env python3
"""Validate hallucination audit result.json files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


CATEGORIES = {
    "tool_result_misread",
    "false_completion_claim",
    "unsupported_factual_claim",
    "fabricated_tool_effect",
    "instruction_contradiction",
    "tool_call_contradiction",
    "other_contradiction",
}
LEVELS = {"low", "medium", "high"}


def _is_int_or_null(value: Any) -> bool:
    return value is None or isinstance(value, int)


def validate_item(item: Any, index: int) -> list[str]:
    prefix = f"item {index}"
    errors: list[str] = []

    if not isinstance(item, dict):
        return [f"{prefix}: expected object, got {type(item).__name__}"]

    for field in ("category", "severity", "confidence", "summary", "rationale"):
        if field not in item:
            errors.append(f"{prefix}: missing required field {field!r}")
            continue
        if not isinstance(item[field], str) or not item[field].strip():
            errors.append(f"{prefix}: field {field!r} must be a non-empty string")

    category = item.get("category")
    if isinstance(category, str) and category not in CATEGORIES:
        errors.append(f"{prefix}: unknown category {category!r}")

    severity = item.get("severity")
    if isinstance(severity, str) and severity not in LEVELS:
        errors.append(f"{prefix}: severity must be one of {sorted(LEVELS)}")

    confidence = item.get("confidence")
    if isinstance(confidence, str) and confidence not in LEVELS:
        errors.append(f"{prefix}: confidence must be one of {sorted(LEVELS)}")

    claim = item.get("contradicting_agent_claim")
    if claim is not None and not isinstance(claim, str):
        errors.append(
            f"{prefix}: contradicting_agent_claim must be a string when present"
        )

    prior_evidence = item.get("prior_evidence")
    if prior_evidence is not None:
        if not isinstance(prior_evidence, list):
            errors.append(f"{prefix}: prior_evidence must be a list when present")
        else:
            for evidence_index, evidence in enumerate(prior_evidence):
                if not isinstance(evidence, str) or not evidence.strip():
                    errors.append(
                        f"{prefix}: prior_evidence[{evidence_index}] must be a non-empty string"
                    )

    location = item.get("location")
    if location is not None:
        if not isinstance(location, dict):
            errors.append(f"{prefix}: location must be an object when present")
        else:
            claim_event_index = location.get("claim_event_index")
            if "claim_event_index" in location and not _is_int_or_null(
                claim_event_index
            ):
                errors.append(
                    f"{prefix}: location.claim_event_index must be an integer or null"
                )

            evidence_event_indices = location.get("evidence_event_indices")
            if "evidence_event_indices" in location:
                if not isinstance(evidence_event_indices, list):
                    errors.append(
                        f"{prefix}: location.evidence_event_indices must be a list"
                    )
                else:
                    for evidence_index, event_index in enumerate(
                        evidence_event_indices
                    ):
                        if not isinstance(event_index, int):
                            errors.append(
                                f"{prefix}: location.evidence_event_indices[{evidence_index}] "
                                "must be an integer"
                            )

    return errors


def validate_result(data: Any) -> list[str]:
    if not isinstance(data, list):
        return [f"root: expected array, got {type(data).__name__}"]

    errors: list[str] = []
    for index, item in enumerate(data):
        errors.extend(validate_item(item, index))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "result_json", type=Path, help="Path to hallucination audit result.json"
    )
    args = parser.parse_args()

    try:
        data = json.loads(args.result_json.read_text())
    except FileNotFoundError:
        print(f"ERROR: file not found: {args.result_json}")
        return 1
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON: {exc}")
        return 1

    errors = validate_result(data)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print(f"OK: {len(data)} hallucination(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
