# Pinchbench Task Template

Pinchbench tasks are rendered by the adapter-local `pinchbench-to-harbor` skill
rather than a static file template. The generated Harbor task shape depends on
the Pinchbench markdown frontmatter:

- `automated` tasks get deterministic verifier scripts.
- `llm_judge` and `hybrid` tasks get Harbor-style `llm_judge.py` verifiers.
- `multi_session` tasks get Harbor `steps/*` directories.

This directory exists to keep the adapter layout aligned with the Harbor adapter
implementation guide while the executable template logic stays in the skill.
