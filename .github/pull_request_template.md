## What does this PR do?

<!-- 2-3 sentences. What changed and why. -->

## How to test it

<!-- Steps to verify the change works locally. -->

```bash
# e.g.
uv run pytest tests/ -v
uv run python -m analyzer --symbols RELIANCE --dry-run
```

## Checklist

- [ ] `uv run ruff check src/ tests/` passes
- [ ] `uv run pytest tests/ -v` passes (coverage ≥ 70%)
- [ ] No secrets or `.env` values hardcoded
- [ ] `--dry-run` tested if pipeline logic changed

## Risk

<!-- Low / Medium / High. What could break? How to roll back? -->
