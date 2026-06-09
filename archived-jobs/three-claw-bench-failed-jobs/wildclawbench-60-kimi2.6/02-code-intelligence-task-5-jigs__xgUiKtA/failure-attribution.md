# Failure Attribution: 02-code-intelligence-task-5-jigs__xgUiKtA

## Verdict

Primary failure: the agent did not solve the jigsaw. It produced a syntactically valid output, but the final saved `result.json` had an entirely wrong 5x5 grid, no rotations, and mostly wrong distractors.

Secondary failure: after writing a candidate answer, the agent kept exploring and hit the step timeout instead of stopping.

## Score

From `result.json` and `steps/run/verifier/reward.json`:

| Metric | Score | Interpretation |
| --- | ---: | --- |
| `reward` / `overall_score` | 0.04 | 2/50 raw points. |
| `grid_points` | 0.0 | No predicted piece was in the correct grid position. |
| `transforms_points` | 0.0 | Final `transforms` had count 0, but the task required exactly 8 rotated pieces. |
| `distractors_points` | 1.0 | The verifier log reports 2/12 distractor points, normalized in `reward.json` as 1.0. |
| `assembly_points` | 0.0 | Assembled-image scoring did not award points. |

The step-level `exception_info` in `result.json` is `TimeoutError`; the agent execution ran from `2026-06-06T12:12:56Z` to `2026-06-06T13:52:56Z`.

## What The Agent Did

The agent tried several computational solvers based on edge matching and visual heuristics:

- It repeatedly attempted to write solver scripts, but initially called the `write` tool without a `path`, causing several validation failures.
- It generated multiple candidate solutions with high boundary MSE and wrong rotation counts.
- It attempted external image/browser/web assistance, but image model calls failed, browser gateway calls failed, and one web fetch returned 403.
- It encountered context overflow twice early in the run, requiring auto-compaction.
- It eventually wrote a final no-rotation solution, then continued searching the web and timed out.

## Final Saved Candidate

The last observed saved candidate in the session was from `solve_no_rot.py`:

```text
Grid: [
  ['piece_01.png', 'piece_09.png', 'piece_22.png', 'piece_36.png', 'piece_31.png'],
  ['piece_14.png', 'piece_03.png', 'piece_23.png', 'piece_05.png', 'piece_18.png'],
  ['piece_10.png', 'piece_08.png', 'piece_19.png', 'piece_11.png', 'piece_07.png'],
  ['piece_02.png', 'piece_15.png', 'piece_12.png', 'piece_33.png', 'piece_17.png'],
  ['piece_04.png', 'piece_16.png', 'piece_21.png', 'piece_13.png', 'piece_06.png']
]
Distractors: [
  'piece_20.png', 'piece_24.png', 'piece_25.png', 'piece_26.png',
  'piece_27.png', 'piece_28.png', 'piece_29.png', 'piece_30.png',
  'piece_32.png', 'piece_34.png', 'piece_35.png', 'piece_37.png'
]
```

This explains the verifier result:

- The final grid does not match any ground-truth cell.
- The final `transforms` object was empty, so transform scoring was forced to 0 because the grader requires exactly 8 entries.
- Only 2 of the 12 predicted distractors were correct.

Ground-truth details used for attribution come from `datasets/wildclawbench/02-code-intelligence-task-5-jigsaw-puzzle-hard-zh/tests/grade_source.py`; they were not available to the agent during the run.

## Root Causes

1. **Algorithmic mismatch.** The agent relied on simple edge MSE and threshold-based backtracking. Correct and incorrect edges were not cleanly separable enough for this approach, especially with rotated pieces and offset-crop distractors.

2. **No robust final validation.** The agent observed that candidate grids had high boundary MSE and wrong rotation counts, but still saved a weak candidate. The final candidate explicitly ignored the task invariant that exactly 8 pieces are rotated.

3. **Tool reliability issues.** Multiple image-model calls failed, the browser gateway failed, and web fetch/search attempts did not provide a usable reference image. These failures pushed the agent toward unreliable local heuristics.

4. **Time management failure.** The agent had produced output files before the timeout, but did not stop. It continued exploratory web/search work until Harbor killed the step.

5. **Verifier-side assembly check issue.** The verifier found `assembled.png` and attempted VLM assembly checks, but all three attempts failed with `'str' object has no attribute 'choices'`. This prevented assembly points. This was not the main cause of failure because the deterministic grid/transform/distractor scores were already near zero.

## Attribution

Failure type: multimodal reasoning plus search/control failure.

Primary attribution: agent reasoning/implementation. The agent did not produce the required grid or rotations.

Contributing attribution: tool availability and timeout behavior. Failed image/browser tools reduced feedback quality, and the agent failed to terminate after writing a candidate answer.

Evaluator attribution: minor. The assembly VLM check appears broken for this run, but it could only account for 5/50 points and would not change the overall conclusion.
