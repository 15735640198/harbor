# Failure Attribution: t2-add-tests-normalizer__BPeAoa2

## 1. Outcome Snapshot

- Source job: `clawbench-19-kimi2.6-2`
- Source benchmark: `clawbench`
- Task: `clawbench/t2-add-tests-normalizer`
- Task path: `datasets/clawbench/t2-add-tests-normalizer`
- Agent: `openclaw` `2026.5.27`
- Model: `anthropic/kimi-k2.6`
- Reward: `0.5556`
- Key sub-scores: completion `0.0`, trajectory `1.0`, behavior `1.0`, judge `0.0`, passed assertions `0/2`
- Trial status: `partial`
- Primary attribution: `agent-execution` with high confidence.

The agent wrote a plausible pytest suite and locally verified it, but placed it at `/workspace/test_normalizer.py` instead of the required `/workspace/tests/test_normalizer.py`. The hidden verifier therefore could not find the test file and assigned zero completion credit.

## 2. Task And Scoring Contract

The task asked the agent to add a focused pytest suite for a text normalization module. The required coverage areas were:

- Whitespace cleanup in titles.
- Emoji stripping in titles.
- Blank tag handling.
- Running the tests after adding them.

The verifier contract in `clawbench_task.json` required:

- File existence: `tests/test_normalizer.py`.
- Execution check: `python3 verify_added_tests.py`.

`verify_added_tests.py` first asserts that `tests/test_normalizer.py` exists. It then runs the full pytest suite and mutates `normalizer.py` with two deliberately buggy versions to ensure the student's tests catch missing emoji stripping and broken blank-tag filtering.

## 3. Evidence Reviewed

- `result.json`
- `config.json`
- `trial.log`
- `agent/trajectory.json`
- `steps/run/agent/openclaw-output.txt`
- `steps/run/agent/openclaw-session.jsonl`
- `steps/run/agent/trajectory.json`
- `steps/run/verifier/reward.json`
- `steps/run/verifier/clawbench_details.json`
- `steps/run/verifier/test-stdout.txt`
- `datasets/clawbench/t2-add-tests-normalizer/steps/run/instruction.md`
- `datasets/clawbench/t2-add-tests-normalizer/tests/clawbench_task.json`
- `datasets/clawbench/t2-add-tests-normalizer/environment/workspace/normalizer.py`
- `datasets/clawbench/t2-add-tests-normalizer/environment/workspace/verify_added_tests.py`

## 4. Execution Timeline

1. The agent searched for Python files and found `/workspace/verify_added_tests.py` and `/workspace/normalizer.py`.
2. It read `/workspace/normalizer.py`, which defined `normalize_title` and `normalize_tags`.
3. It wrote a new test file to `/workspace/test_normalizer.py`.
4. It ran `pytest test_normalizer.py -v`; two tests passed and the emoji-stripping test failed because emoji removal left a double space.
5. It edited `/workspace/normalizer.py` to collapse whitespace again after emoji removal.
6. It reran `pytest test_normalizer.py -v`, and all three local tests passed.
7. It ended with a success summary stating that all three tests passed and that it had fixed the double-space bug.
8. The verifier then checked for `/workspace/tests/test_normalizer.py`, did not find it, and failed before any mutant-quality checks could pass.

## 5. Score And Failure Surface

- `clawbench.completion_score = 0.0`: both completion assertions failed.
- Failed assertion 1: `FILE tests/test_normalizer.py: File does not exist`.
- Failed assertion 2: `EXEC normalizer test quality verify: Exit code 1 != expected 0`.
- Verifier stderr: `AssertionError: tests/test_normalizer.py is missing`.
- `clawbench.trajectory_score = 1.0`: the agent satisfied the expected read, edit, execute, read-before-write, and self-verification trajectory requirements.
- `clawbench.behavior_score = 1.0`: behavior expectations were satisfied.
- `clawbench.judge_score = 0.0`, `clawbench.judge_error = 1.0`: the judge request failed with HTTP 429 quota exhaustion.

The concrete failure surface is the output path. The agent's own test file was not in the location the verifier treated as the deliverable.

## 6. Root Cause Attribution

Primary attribution: `agent-execution`, high confidence.

The agent understood the functional topic and wrote relevant tests, but executed the deliverable incorrectly by writing `test_normalizer.py` at the workspace root. The task did not explicitly name the path in the user-facing instruction, but the local workspace included `verify_added_tests.py`, and the verifier expected the conventional `tests/test_normalizer.py` path. A simple inspection or execution of `python3 verify_added_tests.py` would have exposed the mismatch.

Secondary attribution: `agent-verification`.

The agent verified only its chosen test command, `pytest test_normalizer.py -v`. It did not run the verifier-adjacent script that was present in the workspace, and it did not run full `pytest`. As a result, it accepted a local pass condition that was narrower than the task's scoring contract.

## 7. Contributing Factors

- The prompt said to add a pytest suite but did not explicitly state the required path.
- The verifier helper script was discoverable in the initial file search, but the agent did not read it.
- The agent also changed production code in `normalizer.py`. That fix was reasonable for making the tests pass, but the core task was test authoring; it did not compensate for the missing required test path.
- Judge quota exhaustion added noise to the score breakdown, but the deterministic completion failure was already decisive.

## 8. What Went Right

- The agent inspected the target module before writing tests.
- The tests covered the requested themes: whitespace cleanup, emoji stripping, and blank tag handling.
- The first test run caught a real `normalize_title` bug.
- The agent applied a focused code fix and reran its local tests successfully.
- The trajectory and behavior scores were both perfect, indicating effective tool use apart from the deliverable-path mistake.

## 9. Improvement Plan

- Agent behavior: after finding a verifier helper such as `verify_added_tests.py`, read it before deciding output paths.
- Agent behavior: place pytest suites under `tests/` unless the task or repository convention clearly says otherwise.
- Agent verification: run full `pytest` and any local verification scripts, not only the newly created test file.
- Benchmark/task: include the required `tests/test_normalizer.py` path in the user-facing instruction if exact path compliance is intended.
- Harness/logging: continue preserving `clawbench_details.json`; it was the key evidence showing this was a path error rather than poor test content.

## 10. Open Questions

- The archived workspace snapshot does not include the final file tree after agent edits, but trajectory and verifier output agree that the test was written to `/workspace/test_normalizer.py` and that `/workspace/tests/test_normalizer.py` was absent.
- Because the verifier stopped at the missing file assertion, it is unknown whether the agent's test content would have passed the mutant checks if placed in the expected directory.
