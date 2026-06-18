from pathlib import Path
from typing import Annotated, Sized

from typer import Exit, Option, Typer

traces_app = Typer(
    no_args_is_help=True, context_settings={"help_option_names": ["-h", "--help"]}
)


def _resolve_trajectory_file(path: Path) -> Path:
    if path.is_file():
        return path
    if not path.is_dir():
        raise ValueError(f"Path does not exist: {path}")

    candidates = [
        path / "agent" / "trajectory.json",
        path / "trajectory.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise ValueError(
        "Expected a trajectory JSON file, a trial directory containing "
        "agent/trajectory.json, or a directory containing trajectory.json"
    )


@traces_app.command("blocks")
def blocks(
    path: Annotated[
        Path,
        Option(
            "--path",
            "-p",
            help="Path to an ATIF trajectory.json file or trial directory",
        ),
    ],
    out: Annotated[
        Path | None,
        Option(
            "--out",
            "-o",
            help="Directory to write paper-style block analysis files",
            show_default=False,
        ),
    ] = None,
    ngram_size: Annotated[
        int,
        Option("--ngram-size", help="Action-category n-gram length"),
    ] = 4,
    include_copied_context: Annotated[
        bool,
        Option(
            "--include-copied-context/--exclude-copied-context",
            help="Include ATIF steps marked as copied context",
        ),
    ] = False,
):
    """Parse ATIF trajectories into thought/action/result blocks."""
    import json

    from harbor.utils.trajectory_blocks import (
        parse_trajectory_file,
        write_trajectory_block_analysis,
    )

    trajectory_path = _resolve_trajectory_file(path)
    if out is None:
        parsed = parse_trajectory_file(
            trajectory_path,
            include_copied_context=include_copied_context,
        )
        print(
            json.dumps(
                [block.model_dump(mode="json") for block in parsed],
                indent=2,
            )
        )
        return

    written = write_trajectory_block_analysis(
        trajectory_path,
        out,
        ngram_size=ngram_size,
        include_copied_context=include_copied_context,
    )
    print(f"Parsed {trajectory_path} into {out}")
    for name, written_path in written.items():
        print(f"{name}: {written_path}")


@traces_app.command("convert")
def convert(
    agent: Annotated[
        str,
        Option(
            "--agent",
            help="Agent whose native harness output should be converted to ATIF",
        ),
    ],
    path: Annotated[
        Path,
        Option(
            "--path",
            "-p",
            help="Native harness output directory, or recursive root with --recursive",
        ),
    ],
    recursive: Annotated[
        bool,
        Option(
            "--recursive/--no-recursive",
            help="Search recursively for matching agent log directories",
        ),
    ] = False,
    out: Annotated[
        Path | None,
        Option(
            "--out",
            "-o",
            help="Output trajectory path for single-input conversion",
            show_default=False,
        ),
    ] = None,
    force: Annotated[
        bool,
        Option("--force", help="Overwrite existing trajectory.json files"),
    ] = False,
    validate: Annotated[
        bool,
        Option(
            "--validate/--no-validate",
            help="Validate converted ATIF before writing",
        ),
    ] = True,
):
    """Convert native agent harness output to ATIF trajectory.json files."""

    from harbor.agents.trajectory_conversion import (
        ConversionSummary,
        TrajectoryConversionError,
        convert_one,
        convert_recursive,
        list_converter_names,
    )

    if agent not in list_converter_names():
        supported = ", ".join(list_converter_names())
        print(f"Unsupported agent: {agent}. Supported agents: {supported}")
        raise Exit(1)

    if recursive and out is not None:
        print("--out is only supported without --recursive")
        raise Exit(1)

    try:
        if recursive:
            summary = convert_recursive(
                agent_name=agent,
                root=path,
                force=force,
                validate=validate,
            )
        else:
            summary = ConversionSummary(
                [
                    convert_one(
                        agent_name=agent,
                        input_dir=path,
                        output_path=out,
                        force=force,
                        validate=validate,
                    )
                ]
            )
    except TrajectoryConversionError as exc:
        print(str(exc))
        raise Exit(1) from exc

    for outcome in summary.outcomes:
        if outcome.status == "converted":
            print(f"converted: {outcome.input_dir} -> {outcome.output_path}")
        elif outcome.status == "skipped":
            print(
                f"skipped: {outcome.input_dir} -> {outcome.output_path}"
                f" ({outcome.message})"
            )
        else:
            print(f"failed: {outcome.input_dir} ({outcome.message})")

    print(
        f"Summary: converted={summary.converted} "
        f"skipped={summary.skipped} failed={summary.failed}"
    )
    if summary.failed:
        raise Exit(1)


@traces_app.command("export")
def export(
    path: Annotated[
        Path,
        Option(
            "--path",
            "-p",
            help="Path to a trial dir or a root containing trials recursively",
        ),
    ],
    recursive: Annotated[
        bool,
        Option(
            "--recursive/--no-recursive",
            help="Search recursively for trials under path",
        ),
    ] = True,
    episodes: Annotated[
        str,
        Option(
            "--episodes",
            help="Export all episodes or only the last episode per trial (all|last)",
        ),
    ] = "all",
    to_sharegpt: Annotated[
        bool,
        Option(
            "--sharegpt/--no-sharegpt",
            help="Also emit ShareGPT-formatted conversations column",
        ),
    ] = False,
    push: Annotated[
        bool,
        Option(
            "--push/--no-push", help="Push dataset to Hugging Face Hub after export"
        ),
    ] = False,
    repo_id: Annotated[
        str | None,
        Option(
            "--repo",
            help="Target HF repo id (org/name) when --push is set",
            show_default=False,
        ),
    ] = None,
    verbose: Annotated[
        bool,
        Option("--verbose/--no-verbose", help="Print discovery details for debugging"),
    ] = False,
    filter: Annotated[
        str | None,
        Option(
            "--filter",
            help="Filter trials by result: success|failure|all (default all)",
            show_default=False,
        ),
    ] = None,
    subagents: Annotated[
        bool,
        Option(
            "--subagents/--no-subagents",
            help="Export subagent traces",
        ),
    ] = True,
    instruction_metadata: Annotated[
        bool,
        Option(
            "--instruction-metadata/--no-instruction-metadata",
            help="Include instruction text for each row when available",
            show_default=False,
        ),
    ] = False,
    verifier_metadata: Annotated[
        bool,
        Option(
            "--verifier-metadata/--no-verifier-metadata",
            help="Include verifier stdout/stderr blobs when available",
            show_default=False,
        ),
    ] = False,
):
    from harbor.utils.traces_utils import export_traces as _export_traces

    if push and not repo_id:
        raise ValueError("--push requires --repo <org/name>")

    if episodes not in ("all", "last"):
        raise ValueError("--episodes must be one of: all, last")

    if filter and filter not in ("all", "success", "failure"):
        raise ValueError("--filter must be one of: success, failure, all")

    ds = _export_traces(
        root=path,
        recursive=recursive,
        episodes=episodes,
        to_sharegpt=to_sharegpt,
        repo_id=repo_id,
        push=push,
        verbose=verbose,
        success_filter=(None if (not filter or filter == "all") else filter),
        export_subagents=subagents,
        include_instruction=instruction_metadata,
        include_verifier_output=verifier_metadata,
    )

    # Handle different return types based on export_subagents
    if isinstance(ds, dict):
        # Multiple datasets returned (main + subagents)
        main_ds = ds.get("main")  # type: ignore[call-overload]
        main_count = len(main_ds) if main_ds else 0  # ty: ignore[invalid-argument-type]
        subagent_info = ", ".join(
            [
                f"{k}: {len(v)} rows"
                for k, v in ds.items()
                if k != "main" and isinstance(v, Sized)
            ]
        )
        print(f"Exported {main_count} main rows from {path}")
        if subagent_info:
            print(f"Subagent traces: {subagent_info}")
    else:
        # Single dataset returned (main only)
        print(f"Exported {len(ds)} rows from {path}")
