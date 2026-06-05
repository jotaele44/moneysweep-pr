# Development setup

## Dependencies

`requirements.txt` holds the human-maintained floor pins (`>=`). For a
reproducible install, a fully-pinned, **universal** lockfile is generated with
[`uv`](https://github.com/astral-sh/uv) from `requirements.in`:

```bash
# regenerate after editing requirements.in
uv pip compile requirements.in --universal --python-version 3.10 -o requirements.lock
```

The lock is universal — it carries environment markers so a single file pins the
correct versions across the supported Python matrix (3.10–3.12), e.g.
`pandas==2.3.3 ; python_full_version < '3.11'` vs `pandas==3.0.3 ; >= '3.11'`.

To install against the lock:

```bash
pip install -r requirements.txt -c requirements.lock
```

CI currently installs from `requirements.txt` (floors) and treats the lock as an
opt-in reproducibility aid; it can be promoted to the default install later.

## Type checking

[`mypy`](https://mypy-lang.org/) is configured in `pyproject.toml` with a lenient,
gradually-typed baseline scoped to the `contract_sweeper` package:

```bash
pip install mypy
python -m mypy
```

It runs **report-only** in CI (`.github/workflows/mypy.yml`,
`continue-on-error`), so findings are visible but do not block merges. Tighten the
config (remove `ignore_missing_imports`, widen `files`, drop `continue-on-error`)
incrementally as annotations land.
