---
name: extract-skill-constraints
description: Generate structured instruction-adherence constraints from a Codex skill folder. Use when Codex must read a skill directory, inspect SKILL.md and any mandatory referenced instruction files, extract only actions that must be done or must not be done according to the skill, then write a JSON array of constraint objects for trace-only deterministic or heuristic instruction-adherence evaluation.
---

# Extract Skill Constraints

## Purpose

Read one Codex skill folder and write a JSON file containing only hard mandatory constraints from that skill. Skills can include extensive examples, optional resources, preferences, and explanatory context; exclude all of that unless it creates an explicit `must` or `must_not` obligation.

## Workflow

1. Confirm the input and output paths.
   - If the user provides a skill folder path, use it.
   - The input folder must contain `SKILL.md`.
   - If no output path is provided, write `<skill-folder-name>.constraints.json` next to the skill folder.
   - If multiple skill folders are possible and the intended folder is ambiguous, ask the user which folder to use.

2. Read the skill instructions.
   - Read `SKILL.md` completely, including frontmatter, with line numbers.
   - Inspect referenced resources only when `SKILL.md` says they are mandatory, required, always used, a prerequisite, or must be followed.
   - Do not mine optional examples, assets, scripts, generated metadata, or broad reference files for implicit obligations unless a mandatory instruction points to them.

3. Extract only hard obligations and prohibitions.
   - Include instructions stated with hard language such as `must`, `required`, `mandatory`, `always`, `never`, `do not`, `only`, `cannot`, or `must not`.
   - Include mandatory sequencing rules, mandatory validation steps, mandatory tool-use rules, mandatory output-format rules, and explicit prohibitions.
   - Exclude `should`, `prefer`, `recommended`, `may`, `can`, examples, descriptive background, capability lists, optional resources, and non-binding guidance.
   - Exclude trigger metadata such as "Use when..." unless it states a hard prerequisite or prohibition after the skill is selected.

4. Split constraints atomically.
   - Use one object for one mandatory action, sequencing rule, output requirement, validation requirement, tool-use requirement, resource-handling requirement, or prohibition.
   - Split compound instructions when different conditions, actions, tools, outputs, or exceptions would be evaluated separately.
   - Keep explicit exceptions in the same object when they narrow the same requirement.

5. Ground every object in source text.
   - Use `source` as `skill:<relative-path>:L<start>-L<end>`.
   - Use `source_excerpt` as a short exact excerpt from those lines.
   - Use paths relative to the input skill folder, such as `SKILL.md` or `references/policy.md`.

6. Write JSON only.
   - The root value must be an array.
   - Use stable IDs in source order: `C001`, `C002`, `C003`, ...
   - Do not include Markdown fences, comments, or trailing commas.

7. Validate the output.
   - Run:

```bash
python skills/extract-skill-constraints/scripts/validate_constraints.py <output-json>
```

   - If validation fails, fix the JSON and run the validator again.

## Constraint Object Schema

Each object must use this shape:

```json
{
  "id": "C001",
  "category": "mandatory_validation",
  "priority": "skill",
  "source": "skill:SKILL.md:L42-L46",
  "source_excerpt": "After writing the file, validate the output.",
  "requirement_type": "must",
  "when": "The agent writes the constraint JSON output.",
  "requirement": "The agent must validate the output JSON with the skill's validator after writing it.",
  "exceptions": [],
  "deterministic": "true"
}
```

Field rules:

- `id`: sequential `C###` identifier in source order.
- `category`: one of `mandatory_action`, `mandatory_tool_use`, `mandatory_output`, `mandatory_validation`, `mandatory_resource_handling`, `mandatory_sequence`, `prohibition`.
- `priority`: use `skill` for constraints extracted from a skill folder.
- `source`: `skill:<relative-path>:L<start>-L<end>`.
- `source_excerpt`: exact, short excerpt from the source lines.
- `requirement_type`: use only `must` or `must_not`.
- `when`: condition that activates the constraint. Use `Always` only for skill-level constraints that apply whenever the skill is used.
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

- Treat required work products, required reads, required inspections, or required operations as `mandatory_action`.
- Treat mandatory tool calls, tool prerequisites, tool-specific sequencing, or tool prohibitions as `mandatory_tool_use`.
- Treat required file names, JSON shapes, Markdown sections, citations, final-answer content, or exact formatting as `mandatory_output`.
- Treat required checks, validators, tests, renders, smoke tests, or verification commands as `mandatory_validation`.
- Treat required use or avoidance of bundled scripts, references, assets, templates, or generated files as `mandatory_resource_handling`.
- Treat required ordering such as "before every", "after writing", "first", "then", or "only after" as `mandatory_sequence`.
- Treat `never`, `do not`, `must not`, forbidden actions, and hard exclusions as `prohibition`.
- Convert `only` and `may only` instructions into a `must_not` requirement that names the forbidden alternatives when that is clearer for evaluation.
- Preserve exact tool names, file paths, validator commands, source filenames, prerequisite names, and output filenames when the skill specifies them.
- Do not include broad best practices, explanatory examples, or optional recommendations just because they are useful.
