---
name: harbor-failure-attribution
description: Write standardized failure attribution reports for Harbor OpenClaw job or trial folders. Use when given a Harbor job folder path containing result.json, config.json, agent trajectories, trial logs, verifier output, or prior attribution notes, and the goal is to create or refresh FAILURE_ATTRIBUTION.md with a unified structure. Also use for successful or high-scoring runs when the user wants improvement analysis, residual risk, or attribution of remaining score loss.
---

# Harbor Failure Attribution

Write `FAILURE_ATTRIBUTION.md` inside one Harbor OpenClaw trial folder. Treat the input as a single job/trial directory such as `jobs/.../<trial_name>` or `archived-jobs/.../<trial_name>`.

## Workflow

1. Confirm the input path is a single trial folder, not a parent job containing many trials. A valid folder usually has `result.json`, `config.json`, `trial.log`, and `agent/trajectory.json`.
2. Run the evidence collector:

```bash
python skills/harbor-failure-attribution/scripts/collect_job_context.py <job-folder>
```

3. Read the files called out by the collector. Always inspect `result.json`, `trial.log`, and at least one agent trace source when present:
   - `agent/trajectory.json`
   - `agent/openclaw-output.txt`
   - `agent/tar_blocks/action_actions.txt`
   - `agent/tar_blocks/results_actions.txt`
   - `agent/openclaw-session.jsonl`
4. If prior attribution docs exist in the folder under names like `attribution.md`, `failure-attribution.md`, or `failure_attribution.md`, read them as notes, but write the final report in the standardized structure below.
5. If task source files are locally available, inspect `instruction.md`, verifier scripts, and relevant task fixtures. If they are not available, infer expectations from `result.json`, verifier metrics, logs, and the first user instruction in the trajectory. State when task source was unavailable.
6. Write or replace `<job-folder>/FAILURE_ATTRIBUTION.md`.

Do not stop at the numeric reward. Attribute the failure phase and mechanism using concrete evidence from logs, metrics, and agent actions. If the run succeeded, still analyze avoidable inefficiency, brittle behavior, unnecessary tool work, low sub-scores, missing verification, or robustness risks.

## Report Structure

Use these exact top-level sections and order.

```markdown
# Failure Attribution: <trial_name>

## 1. Outcome Snapshot
## 2. Task And Scoring Contract
## 3. Evidence Reviewed
## 4. Execution Timeline
## 5. Score And Failure Surface
## 6. Root Cause Attribution
## 7. Contributing Factors
## 8. What Went Right
## 9. Improvement Plan
## 10. Open Questions
```

### 1. Outcome Snapshot

Include:
- Trial name, source benchmark, task name/path, agent name/version/model.
- Final reward and key sub-scores. If no reward exists, write `Reward: unavailable`.
- Trial status: `success`, `partial`, `hard failure`, `timeout`, `setup failure`, `verifier failure`, or `unscored`.
- One concise verdict sentence naming the primary attribution.

### 2. Task And Scoring Contract

Explain what the agent needed to produce or do. Prefer task source files when available. Otherwise use trajectory prompt, verifier metric names, `verifier/reward.json`, and `result.json`.

Include:
- Required output paths, commands, tool calls, external services, or safety behavior.
- How success was measured.
- Any explicit constraints from the instruction.

### 3. Evidence Reviewed

List the concrete files inspected. Include absent-but-expected evidence when absence matters, such as missing verifier logs, missing output artifact, missing trajectory, or missing reward.

Keep this factual. Do not argue attribution here.

### 4. Execution Timeline

Summarize the run in chronological bullets:
- Setup and agent start.
- Major agent actions and tool calls.
- Key observations/errors.
- Final agent message or termination condition.
- Verifier execution, if it ran.

Use timestamps or step numbers when available. For long traces, group repeated actions.

### 5. Score And Failure Surface

Describe exactly which metrics passed and failed.

For each important failed metric or missing artifact, include:
- Metric name and value.
- Expected behavior.
- Observed behavior.
- Evidence file supporting the observation.

If the reward is high, focus on remaining score loss and hidden quality risks. If the run is unscored, explain which phase prevented scoring.

### 6. Root Cause Attribution

Give one primary attribution and a short justification. Use these labels when applicable:
- `agent-planning`: wrong plan, missed requirements, poor prioritization.
- `agent-execution`: correct intent but wrong commands, files, edits, or tool usage.
- `agent-recovery`: failed to adapt after an error, stopped too early, asked user unnecessarily.
- `agent-verification`: did not inspect outputs, run checks, or validate against requirements.
- `tool-use`: misuse or misunderstanding of available tools.
- `environment-setup`: dependency, setup script, fixture, credential, network, or container issue before meaningful task work.
- `benchmark-design`: ambiguous prompt, impossible requirement, bad verifier, missing fixture, or mismatch between prompt and environment.
- `verifier-issue`: verifier failed, omitted reward, judged wrong artifact, or lacks needed diagnostics.
- `safety-policy`: unsafe compliance, failure to warn, over-refusal, or missed security handling.
- `model-capability`: likely knowledge, reasoning, multimodal, long-context, or instruction-following limit after tools/environment were adequate.

State whether attribution is `high`, `medium`, or `low` confidence. Separate immediate cause from deeper cause when both matter.

### 7. Contributing Factors

List secondary causes that amplified the failure but were not primary. Examples:
- Missing setup logs.
- Ambiguous output path.
- Unpinned dependency.
- Long trace with no checkpointing.
- Authentication assumption.
- Weak partial-credit behavior.
- Agent failed to create a partial report after a blocker.

Write `None identified` if there are no meaningful secondary factors.

### 8. What Went Right

Always include this section, even for zero-score runs. Note any useful behavior:
- Correct initial interpretation.
- Some passed metrics.
- Useful diagnostic command.
- Appropriate refusal or warning.
- Correct artifact format but wrong content.

For a setup failure where the agent never ran, write that no agent behavior can be credited and identify any harness behavior that worked.

### 9. Improvement Plan

Separate recommendations by owner when possible:
- Agent behavior: prompt, tool strategy, recovery, self-verification.
- Benchmark/task: instruction clarity, environment, fixtures, verifier diagnostics.
- Harness/logging: preserve setup stdout/stderr, artifact snapshots, trajectory completeness.

Make recommendations concrete and testable. Include what would have changed the outcome for this run.

### 10. Open Questions

List unresolved facts that cannot be determined from the archived job folder. Examples:
- Missing setup stderr.
- Unknown expected fixture content.
- Whether a dependency failure was transient.
- Whether task source differs from copied artifacts.

If none, write `None`.

## Writing Rules

- Use evidence-backed language. Prefer "the trace shows..." over speculation.
- Keep the report concise, usually 700 to 1,200 words.
- Do not paste large logs or full trace excerpts. Quote only the short lines needed to establish facts.
- Do not count an environment/setup failure as model failure unless the agent had a meaningful chance to act and recover.
- Do not count a verifier failure as task failure without explaining why the verifier path failed.
- Preserve uncertainty. Use "likely", "possibly", and confidence labels when evidence is incomplete.
- Never write only "the task failed because reward was 0"; explain the causal chain.
- For successful runs, title remains `Failure Attribution`, but frame the report as residual attribution and improvement analysis.
