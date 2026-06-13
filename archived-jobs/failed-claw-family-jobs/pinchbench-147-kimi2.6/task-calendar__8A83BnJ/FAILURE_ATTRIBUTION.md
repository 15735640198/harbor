# Failure Attribution: task-calendar__8A83BnJ

## Summary

The trial failed because the agent wrote the calendar file to a subdirectory, `/app/events/project-sync-2026-06-02.ics`, while the grader only looked for `.ics` files directly under the workspace root, `/app/*.ics`.

This caused `automated.file_created` to be 0.0. The grader then returned early, so every content-specific check also scored 0.0.

## Evidence

- Final reward: `0.0`
- Failed checks:
  - `automated.file_created`: `0.0`
  - `automated.date_correct`: `0.0`
  - `automated.time_correct`: `0.0`
  - `automated.attendee_present`: `0.0`
  - `automated.title_correct`: `0.0`
  - `automated.description_present`: `0.0`
- Agent action trace:
  - It computed next Tuesday as `2026-06-02`.
  - It wrote `530` bytes to `/app/events/project-sync-2026-06-02.ics`.
- Grader behavior:
  - The grader uses `workspace.glob("*.ics")`.
  - That only matches root-level `.ics` files in `/app`.
  - It does not match files in `/app/events/`.

## Root Cause

Primary attribution: artifact placement mismatch.

The task instruction said to write an ICS file "in the workspace". The agent interpreted this as allowing a subdirectory inside the workspace. The verifier interpreted it narrowly as requiring the `.ics` file at the workspace root.

## Secondary Notes

The generated ICS content appears likely to satisfy the intended semantic requirements for the original run date:

- Meeting title: `Project Sync`
- Date: `2026-06-02`, which was next Tuesday at the time of the trial on `2026-05-27`
- Time: `15:00`
- Attendee: `john@example.com`
- Description mentions the Q1 roadmap

However, the grader never inspected that content because it did not find a root-level `.ics` file.

## Attribution Category

`artifact_path_contract_failure`

## Suggested Fixes

For agent behavior:

- Prefer writing required deliverables directly in the workspace root unless the task explicitly asks for a subdirectory.
- When creating a deliverable in a subdirectory, also consider placing or copying the final artifact at the root if the benchmark wording is ambiguous.

For benchmark robustness:

- If subdirectories should count as workspace artifacts, change the grader from `workspace.glob("*.ics")` to `workspace.rglob("*.ics")`.
- If root-only output is required, make the instruction explicit: "write the ICS file directly in `/app`, not in a subdirectory."
