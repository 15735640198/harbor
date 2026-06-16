#!/usr/bin/env python3
"""Classify whether an agent final message claims task completion."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

Classification = Literal["success", "failure", "unknown"]


@dataclass(frozen=True)
class CompletionClassification:
    classification: Classification
    matched_pattern: str | None
    rationale: str
    confidence: Literal["low", "medium", "high"]

    def to_json_dict(self) -> dict[str, str | None]:
        return asdict(self)


@dataclass(frozen=True)
class PatternRule:
    label: str
    pattern: re.Pattern[str]


_FAILURE_RULES = [
    PatternRule(
        "english_unable_to_complete",
        re.compile(
            r"\b(?:i|we)?\s*(?:could\s+not|couldn't|cannot|can't|unable\s+to)\s+"
            r"(?:complete|finish|solve|save|write|create|generate)\b"
        ),
    ),
    PatternRule(
        "english_cant_proceed",
        re.compile(
            r"\b(?:i|we)\s+(?:can't|cannot|don't\s+have|do\s+not\s+have)\b.{0,120}"
            r"\b(?:access|authenticate|authentication|credentials|token|tool|proceed|help|view)\b"
        ),
    ),
    PatternRule(
        "english_not_complete",
        re.compile(
            r"\b(?:task|job|work|request|it|this)\s+(?:is\s+)?"
            r"(?:not\s+(?:complete|completed|done|finished)|incomplete)\b"
        ),
    ),
    PatternRule(
        "english_blocked_completion",
        re.compile(
            r"\b(?:blocked|stuck)\b.{0,80}\b(?:complete|finish|solve|save|write|create|generate)\b"
        ),
    ),
    PatternRule(
        "english_error_prevented_completion",
        re.compile(
            r"\b(?:error|exception|failure)\b.{0,80}\b"
            r"(?:prevented|prevents|blocking|blocked|unable|could\s+not|can't|cannot)\b"
        ),
    ),
    PatternRule(
        "english_completion_failed",
        re.compile(
            r"\b(?:failed|failure)\s+(?:to\s+)?"
            r"(?:complete|finish|solve|save|write|create|generate)\b"
        ),
    ),
    PatternRule(
        "chinese_failed",
        re.compile(r"(?:任务)?(?:失败|未完成|没完成|无法完成|不能完成)"),
    ),
    PatternRule(
        "chinese_error_blocked",
        re.compile(r"(?:报错|错误|异常).{0,40}(?:无法|不能|未能|没能)"),
    ),
]

_SUCCESS_RULES = [
    PatternRule(
        "english_completed_task",
        re.compile(
            r"\b(?:i|we)\s+(?:have\s+)?(?:completed|finished)\s+"
            r"(?:the\s+)?(?:task|job|work|request)\b"
        ),
    ),
    PatternRule(
        "english_task_complete",
        re.compile(
            r"\b(?:task|job|work|request)\s+(?:is\s+)?"
            r"(?:complete|completed|done|finished)\b"
        ),
    ),
    PatternRule(
        "english_subject_is_complete",
        re.compile(
            r"\b(?:pipeline|implementation|script|report|analysis|export|triage|"
            r"itinerary|search|task|job|work|request)\s+"
            r"(?:is\s+)?complete(?:\s+and\s+verified)?\b"
        ),
    ),
    PatternRule(
        "english_done",
        re.compile(r"\b(?:done|all\s+set|finished)\b"),
    ),
    PatternRule(
        "english_fixed",
        re.compile(r"\b(?:fixed|bug\s+fixed|issue\s+fixed|the\s+bug\s+is\s+fixed)\b"),
    ),
    PatternRule(
        "english_tests_pass",
        re.compile(
            r"\b(?:all\s+)?(?:tests?|checks?|verification|verify\s+script)\s+"
            r"(?:now\s+)?(?:pass|passes|passed|succeed|succeeds|succeeded)\b"
        ),
    ),
    PatternRule(
        "english_all_verifiers_pass",
        re.compile(
            r"\ball\s+.{0,40}\b(?:pass|passes|passed|succeed|succeeds|succeeded)\b"
        ),
    ),
    PatternRule(
        "english_verification_passed",
        re.compile(
            r"\b(?:verification\s+script|verify\s+script|verifier|verifiers|"
            r"tests?|checks?)\s+.{0,80}\b(?:passed|pass|passes|succeeded|succeeds)\b"
        ),
    ),
    PatternRule(
        "english_successfully_wrote",
        re.compile(
            r"\bsuccessfully\s+(?:created|wrote|written|saved|generated|completed|"
            r"finished|updated|produced)\b"
        ),
    ),
    PatternRule(
        "english_saved_output",
        re.compile(
            r"\b(?:saved|wrote|written|created|generated|updated|jotted\s+down)\s+(?:the\s+)?"
            r"(?:results?|report|file|answer|output|findings?)\b"
        ),
    ),
    PatternRule(
        "english_saved_to_path",
        re.compile(
            r"\b(?:saved|wrote|written|created|generated|updated|jotted\s+down)\s+"
            r"(?:to|in|at|as)\s+[`'\"]?[/\w.-]"
        ),
    ),
    PatternRule(
        "english_got_it_saved",
        re.compile(
            r"\bgot\s+it\b.{0,120}\b(?:saved|wrote|written|created|jotted\s+down)\b"
        ),
    ),
    PatternRule(
        "english_output_has_been_saved",
        re.compile(
            r"\b(?:results?|report|file|answer|output|findings?)\s+"
            r"(?:has|have)\s+been\s+"
            r"(?:saved|written|created|generated|updated)\b"
        ),
    ),
    PatternRule(
        "english_file_path_written",
        re.compile(
            r"[`'\"]?[/\w.-]+\.(?:md|txt|json|csv|ics|py|js|html|yaml|yml|toml|sh)"
            r"[`'\"]?\s+(?:has\s+been\s+)?"
            r"(?:saved|written|created|generated|updated)\b"
        ),
    ),
    PatternRule(
        "english_here_are_deliverable",
        re.compile(
            r"\bhere\s+are\s+(?:the\s+)?(?:answers?|results?|findings?|"
            r"requested|key|summary|details|files?|changes?)\b"
        ),
    ),
    PatternRule(
        "english_heres_deliverable",
        re.compile(
            r"\bhere(?:'s| is)\s+(?:your\s+)?(?:catch-up|summary|report|"
            r"answer|analysis|triage|itinerary|result|findings?)\b"
        ),
    ),
    PatternRule(
        "chinese_completed",
        re.compile(r"(?:所有)?(?:任务|工作)?已完成|任务完成|完成了(?:任务|工作)?"),
    ),
    PatternRule(
        "chinese_saved",
        re.compile(
            r"成功(?:保存|写入|创建|生成)|(?:结果|报告|文件|答案)已(?:保存|写入|创建|生成)"
        ),
    ),
]


def normalize_message(message: str) -> str:
    """Normalize punctuation and whitespace while preserving Chinese text."""
    normalized = message.lower()
    normalized = normalized.replace("’", "'").replace("`", "'")
    normalized = re.sub(r"[\u2013\u2014]", "-", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def classify_message(message: str) -> CompletionClassification:
    """Classify whether a final message claims success, failure, or neither."""
    normalized = normalize_message(message)
    if not normalized:
        return CompletionClassification(
            classification="unknown",
            matched_pattern=None,
            rationale="The final message is empty.",
            confidence="high",
        )

    failure_match = _first_match(_FAILURE_RULES, normalized)
    if failure_match is not None:
        return CompletionClassification(
            classification="failure",
            matched_pattern=failure_match,
            rationale="The final message explicitly says completion was blocked or failed.",
            confidence="high",
        )

    success_match = _first_match(_SUCCESS_RULES, normalized)
    if success_match is not None:
        return CompletionClassification(
            classification="success",
            matched_pattern=success_match,
            rationale="The final message explicitly claims the task was completed or output was saved.",
            confidence="high",
        )

    return CompletionClassification(
        classification="unknown",
        matched_pattern=None,
        rationale="No explicit completion or failure phrase matched.",
        confidence="high",
    )


def _first_match(rules: list[PatternRule], text: str) -> str | None:
    for rule in rules:
        if rule.pattern.search(text):
            return rule.label
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify an agent final message with non-LLM heuristics."
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--text", help="Message text to classify.")
    source.add_argument("--file", type=Path, help="File containing message text.")
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output.",
    )
    return parser.parse_args()


def read_message(args: argparse.Namespace) -> str:
    if args.text is not None:
        return args.text
    if args.file is not None:
        return args.file.read_text(errors="replace")
    return sys.stdin.read()


def main() -> int:
    args = parse_args()
    result = classify_message(read_message(args))
    indent = 2 if args.pretty else None
    print(json.dumps(result.to_json_dict(), ensure_ascii=False, indent=indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
