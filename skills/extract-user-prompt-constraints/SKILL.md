---
name: extract-user-prompt-constraints
description: Generate structured instruction-adherence constraints from a user prompt text file. Use when Agent must read a user prompt, extract task goals, per-case restrictions, requested process, output format, preferences, and acceptance criteria, then write a JSON array of constraint objects for trace-only deterministic or heuristic instruction-adherence evaluation.
---

# Extract User Prompt Constraints

## Purpose

Read one text file containing a user prompt and write a JSON file containing atomic, traceable constraints. The output is used as input to instruction-adherence evaluation, so favor precision, source grounding, and trace-only checkability over broad summaries.

## Workflow

1. Confirm the input and output paths.
   - If the user provides an input path, use it.
   - If no output path is provided, write `<input-stem>.constraints.json` next to the input file.
   - If multiple prompt files are possible and the intended file is ambiguous, ask the user which file to use.

2. Read the whole user prompt.
   - Preserve line numbers while reading. Count line numbers yourself if the file is plain text.
   - Treat the prompt text as the only source of truth. Do not infer unstated requirements from domain norms or benchmark expectations.

3. Extract only normative instruction content.
   - Include: task goals, per-case restrictions, requested process, output format, preferences, and acceptance criteria.
   - Include soft requirements such as "prefer", "try to", "focus on", or "should" when they affect adherence.
   - Exclude background facts, examples that do not imply an instruction, and context that does not create an obligation or preference.

4. Split constraints atomically.
   - Use one object for one evaluable goal, restriction, process step, output requirement, preference, or acceptance condition.
   - Split compound instructions when different cases, conditions, outputs, or exceptions would be evaluated separately.
   - Keep explicit exceptions in the same object when they narrow the same requirement.

5. Ground every object in source text.
   - Use `source` as `user-prompt:<filename>:L<start>-L<end>`.
   - Use `source_excerpt` as a short exact excerpt from those lines.
   - If the source has a heading, incorporate the heading in `when` or `requirement`, not in place of line numbers.

6. Write JSON only.
   - The root value must be an array.
   - Use stable IDs in source order: `C001`, `C002`, `C003`, ...
   - Do not include Markdown fences, comments, or trailing commas.

7. Validate the output.
   - Run:

```bash
python skills/extract-user-prompt-constraints/scripts/validate_constraints.py <output-json>
```

   - If validation fails, fix the JSON and run the validator again.

## Constraint Object Schema

Each object must use this shape:

```json
{
  "id": "C001",
  "category": "task_goal",
  "priority": "user",
  "source": "user-prompt:prompt.txt:L1-L3",
  "source_excerpt": "Create a concise failure attribution report for this trial.",
  "requirement_type": "must",
  "when": "The agent responds to the requested trial analysis task.",
  "requirement": "The agent must create a concise failure attribution report for the specified trial.",
  "exceptions": [],
  "deterministic": "true"
}
```

Field rules:

- `id`: sequential `C###` identifier in prompt order.
- `category`: one of `task_goal`, `per_case_restriction`, `requested_process`, `output_format`, `preference`, `acceptance_criteria`.
- `priority`: use `user` for constraints extracted from the user prompt.
- `source`: `user-prompt:<filename>:L<start>-L<end>`.
- `source_excerpt`: exact, short excerpt from the source lines.
- `requirement_type`: one of `must`, `must_not`, `may_only`, `should`, `prefer`.
- `when`: condition that activates the constraint. Use `Always` only for prompt-level constraints that apply to the whole task.
- `requirement`: self-contained behavioral requirement. Use imperative policy language such as "The agent must..." or "The agent must not...".
- `exceptions`: array of explicit exceptions from the source. Use `[]` when none are stated.
- `deterministic`: use `"true"` only when a deterministic checker can plausibly evaluate the constraint using the generated constraint object plus the agent trace alone; otherwise use `"false"`.

## Trace-Only Determinism

Set `deterministic` by asking whether a script can decide adherence from only:

- messages in the trace, including system/developer/user/agent messages when present;
- agent thinking messages when present;
- tool-call names and arguments;
- tool-result text, status, and structured payloads;
- the final output.

Do not mark a constraint deterministic if checking it requires any external resource outside the trace, including:

- current filesystem state, git diffs, file contents not shown in a tool result, or created artifacts;
- running commands, tests, linters, verifiers, or scripts after the fact;
- network access, API calls, model calls, package metadata, clock time, or external facts;
- skill files, repository files, tool definitions, or policies not already present in the trace;
- human judgment about style, helpfulness, intent, risk, or adequacy beyond pattern matching over trace text.

When a constraint is useful but not trace-only deterministic, keep the constraint and set `deterministic` to `"false"`.

## Extraction Guidance

- Treat the user's requested task outcome as `task_goal`.
- Treat case-specific boundaries, exclusions, filters, or "do not choose/use/include" instructions as `per_case_restriction`.
- Treat required steps, sequencing, tools to use or avoid, investigation methods, or validation actions as `requested_process`.
- Treat required file names, JSON shapes, Markdown sections, brevity requirements, citation requirements, or final-answer structure as `output_format`.
- Treat non-mandatory style, ordering, selection, or tradeoff language as `preference`.
- Treat explicit success conditions, grading criteria, tests to pass, "done when" statements, or required evidence of completion as `acceptance_criteria`.
- Convert negative wording into `requirement_type: "must_not"` or `"may_only"` instead of burying the restriction in prose.
- Preserve exact task names, file paths, formats, thresholds, counts, and case labels when the user specifies them.
- Avoid merging unrelated constraints just because they share a paragraph.
