import importlib.util
import sys
from collections import Counter
from pathlib import Path


def load_summarize_module():
    script_path = (
        Path(__file__).parents[2] / "scripts" / "summarize_trajectory_blocks.py"
    )
    spec = importlib.util.spec_from_file_location(
        "summarize_trajectory_blocks",
        script_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load summarize_trajectory_blocks.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_classify_outcome_success_threshold():
    summarize = load_summarize_module()
    metadata = {"verifier_result": {"rewards": {"reward": 0.8}}}

    assert summarize.classify_outcome(metadata) == "failure"
    assert summarize.classify_outcome(metadata, success_threshold=0.8) == "success"


def test_classify_outcome_can_count_errors_as_failures():
    summarize = load_summarize_module()
    metadata = {
        "exception_info": {"exception_type": "RuntimeError"},
        "verifier_result": {"rewards": {"reward": 1.0}},
    }

    assert summarize.classify_outcome(metadata) == "error"
    assert summarize.classify_outcome(metadata, errors_as_failures=True) == "failure"


def test_markdown_summary_includes_success_and_failure_ngrams(tmp_path):
    summarize = load_summarize_module()
    summary_path = tmp_path / "summary.md"
    summaries = [
        make_trial_summary(summarize, "success", ["Retrieve"] * 4),
        make_trial_summary(summarize, "failure", ["Generate Fix"] * 4),
    ]
    ngram_counts = Counter(
        {
            ("Retrieve", "Retrieve", "Retrieve", "Retrieve"): 1,
            ("Generate Fix", "Generate Fix", "Generate Fix", "Generate Fix"): 1,
        }
    )
    summarize.write_markdown_summary(
        summary_path,
        summaries,
        {
            ("ALL", "all"): ngram_counts,
            ("ALL", "success"): Counter(
                {("Retrieve", "Retrieve", "Retrieve", "Retrieve"): 1}
            ),
            ("ALL", "failure"): Counter(
                {("Generate Fix", "Generate Fix", "Generate Fix", "Generate Fix"): 1}
            ),
        },
        top_k=10,
        ngram_size=4,
    )

    content = summary_path.read_text()

    assert "## Top 4-grams" in content
    assert "## Success Top 4-grams" in content
    assert "| Retrieve -> Retrieve -> Retrieve -> Retrieve | 1 |" in content
    assert "## Failure Top 4-grams" in content
    assert (
        "| Generate Fix -> Generate Fix -> Generate Fix -> Generate Fix | 1 |"
        in content
    )


def make_trial_summary(summarize, outcome, categories):
    return summarize.TrialSummary(
        job="job",
        trial=f"{outcome}-trial",
        task_name="task",
        source="source",
        agent="agent",
        model="model",
        reward=1.0 if outcome == "success" else 0.0,
        outcome=outcome,
        exception_type="",
        length=len(categories),
        prompt_tokens=0,
        completion_tokens=0,
        cached_tokens=0,
        total_tokens=0,
        cost_usd=0.0,
        categories=categories,
        repeated_actions=0,
        repeated_categories=0,
        consecutive_generate_fix=0,
        no_test_after_last_fix=False,
    )
