# Failure Attribution

## Summary

This failure was not caused by the task docs missing from the Harbor testing container.

The converted task correctly copied the original asset pack into the container image. The agent failed because it searched OpenClaw's installed documentation directory instead of the task-local `docs/` directory in `/workspace`, then looped until timeout without writing the required output files.

## Expected Task

The instruction required:

- Read only local docs in `docs/`.
- Write `answer.txt` in the form `Support window: ...`.
- Write `evidence.md` citing the source file and quoted line.

The correct local evidence is:

- `docs/maintenance_notes.md`
- line: `- Support window: 18 months`

The verifier expected:

- `answer.txt` exactly equal to `Support window: 18 months`
- `evidence.md` containing `maintenance_notes.md` and `18 months`

## Container Validation

The original task asset pack is:

`related-projects/external-tasks/clawbench/tasks-public/assets/t5_hallucination_resistant_evidence`

The converted task workspace is:

`datasets/clawbench/t5-hallucination-resistant-evidence/environment/workspace`

Validation findings:

- The original asset pack and converted workspace are byte-for-byte identical.
- The converted Dockerfile includes `COPY workspace/ /workspace/`.
- Building the converted Docker image showed `/workspace/docs/maintenance_notes.md` exists.
- `/workspace/verify_answer.py` exists.
- Creating the expected `answer.txt` and `evidence.md` inside the image makes `python3 verify_answer.py` pass.
- Running the archived `install-openclaw.sh` inside the built image did not delete `/workspace/docs/maintenance_notes.md`.

## Workspace Validation

The archived OpenClaw session metadata showed OpenClaw did know the workspace path:

- session `cwd`: `/workspace`
- `workspaceDir`: `/workspace`
- OpenClaw config `agents.defaults.workspace`: `/workspace`
- shell tool results used `cwd: /workspace`

So the failure was not that OpenClaw lacked a workspace path.

## What The Agent Did

The raw session shows:

- 261 `exec` calls
- 143 `read` calls
- 0 write/edit calls
- 141 reads of missing `/workspace/answer.txt`
- 261 shell searches under `/root/.nvm/versions/node/v22.22.3/lib/node_modules/openclaw/docs`
- 0 shell searches under `/workspace/docs` or task-local `docs/`

The agent repeatedly searched OpenClaw's installed docs, for example:

`/root/.nvm/versions/node/v22.22.3/lib/node_modules/openclaw/docs`

It never inspected:

`/workspace/docs/maintenance_notes.md`

It never wrote:

- `/workspace/answer.txt`
- `/workspace/evidence.md`

## Verifier Result

The verifier reported:

- `completion_score`: `0.0`
- `judge_score`: `0.0`
- `passed_assertions`: `0 / 2`
- `failure_mode`: `verification_skipped`

Failed assertions:

- `FILE evidence.md: File does not exist`
- `EXEC answer verification: Exit code 1 != expected 0`

The execution check failed because `verify_answer.py` could not read missing `answer.txt`.

## Root Cause

OpenClaw's system prompt included a documentation section pointing to its own installed docs:

`Docs: /root/.nvm/versions/node/v22.22.3/lib/node_modules/openclaw/docs`

The model appears to have latched onto that path when the task said `local docs in docs/`. This caused a context/path confusion:

- task-local docs: `/workspace/docs`
- OpenClaw product docs: `/root/.nvm/versions/node/v22.22.3/lib/node_modules/openclaw/docs`

The agent chose the latter and never recovered.

## Attribution

Primary failure type: agent prompt/context confusion.

More specific attribution:

The task assets and Harbor container setup were correct. OpenClaw exposed the correct workspace as `/workspace`, but its prompt also advertised OpenClaw's own documentation directory. The model interpreted `docs/` as OpenClaw's installed docs rather than the task-local `/workspace/docs`, entered a repeated wrong-path search loop, performed no file mutations, timed out, and left both required deliverables missing.
