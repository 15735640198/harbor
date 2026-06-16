#!/usr/bin/env python3
"""Validate system-prompt instruction constraint JSON files."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


CATEGORIES = {
    "global_requirement",
    "prohibition",
    "priority_rule",
    "tool_use_restriction",
    "output_requirement",
    "conditional_behavior",
    "security_privacy_policy",
}
REQUIREMENT_TYPES = {"must", "must_not", "may_only", "should", "prefer"}
ID_RE = re.compile(r"^C\d{3,}$")
SOURCE_RE = re.compile(r"^system-prompt:.+:L\d+-L\d+$")


def validate_string_field(item: dict[str, Any], field: str, prefix: str) -> list[str]:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        return [f"{prefix}: field {field!r} must be a non-empty string"]
    return []


def validate_string_list(value: Any, field: str, prefix: str) -> list[str]:
    if not isinstance(value, list):
        return [f"{prefix}: field {field!r} must be a list"]

    errors: list[str] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, str) or not entry.strip():
            errors.append(
                f"{prefix}: field {field!r}[{index}] must be a non-empty string"
            )
    return errors


def validate_item(item: Any, index: int, expected_id: str) -> list[str]:
    prefix = f"item {index}"
    if not isinstance(item, dict):
        return [f"{prefix}: expected object, got {type(item).__name__}"]

    errors: list[str] = []
    required_fields = {
        "id",
        "category",
        "priority",
        "source",
        "source_excerpt",
        "requirement_type",
        "when",
        "requirement",
        "exceptions",
        "deterministic",
    }
    for field in sorted(required_fields - set(item)):
        errors.append(f"{prefix}: missing required field {field!r}")

    for field in (
        "id",
        "category",
        "priority",
        "source",
        "source_excerpt",
        "requirement_type",
        "when",
        "requirement",
        "deterministic",
    ):
        if field in item:
            errors.extend(validate_string_field(item, field, prefix))

    constraint_id = item.get("id")
    if isinstance(constraint_id, str):
        if not ID_RE.fullmatch(constraint_id):
            errors.append(f"{prefix}: id must match C###, got {constraint_id!r}")
        if constraint_id != expected_id:
            errors.append(
                f"{prefix}: id should be {expected_id}, got {constraint_id!r}"
            )

    category = item.get("category")
    if isinstance(category, str) and category not in CATEGORIES:
        errors.append(f"{prefix}: unknown category {category!r}")

    priority = item.get("priority")
    if isinstance(priority, str) and priority != "system":
        errors.append(f"{prefix}: priority must be 'system'")

    source = item.get("source")
    if isinstance(source, str) and not SOURCE_RE.fullmatch(source):
        errors.append(
            f"{prefix}: source must match 'system-prompt:<filename>:L<start>-L<end>'"
        )

    requirement_type = item.get("requirement_type")
    if isinstance(requirement_type, str) and requirement_type not in REQUIREMENT_TYPES:
        errors.append(f"{prefix}: unknown requirement_type {requirement_type!r}")

    if "exceptions" in item:
        exceptions = item.get("exceptions")
        if exceptions == []:
            pass
        else:
            errors.extend(validate_string_list(exceptions, "exceptions", prefix))

    deterministic = item.get("deterministic")
    if isinstance(deterministic, str) and deterministic not in {"true", "false"}:
        errors.append(f"{prefix}: deterministic must be 'true' or 'false'")

    if "deterministic_evaluation" in item:
        errors.append(f"{prefix}: unexpected field 'deterministic_evaluation'")

    return errors


def validate_constraints(data: Any) -> list[str]:
    if not isinstance(data, list):
        return [f"root: expected array, got {type(data).__name__}"]

    errors: list[str] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(data):
        expected_id = f"C{index + 1:03d}"
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            constraint_id = item["id"]
            if constraint_id in seen_ids:
                errors.append(f"item {index}: duplicate id {constraint_id!r}")
            seen_ids.add(constraint_id)
        errors.extend(validate_item(item, index, expected_id))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("constraints_json", type=Path)
    args = parser.parse_args()

    try:
        data = json.loads(args.constraints_json.read_text())
    except FileNotFoundError:
        print(f"ERROR: file not found: {args.constraints_json}")
        return 1
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON: {exc}")
        return 1

    errors = validate_constraints(data)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print(f"OK: {len(data)} constraint(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
