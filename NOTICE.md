# Notice

This repository is a fork of **[github/spec-kit](https://github.com/github/spec-kit)**
(MIT, © GitHub, Inc.), created to add a deterministic conformance gate for Spec
Kit artifacts.

## What was added

| Path | Lines | Purpose |
|---|---|---|
| `src/specify_cli/gate/` | new package | parser, rules, coverage, baseline, renderers, CLI adapter |
| `src/specify_cli/command_gate.py` | new | `specify gate` command definition |
| `tests/specify_cli/gate/` | new | 68 tests (parser layouts, rules, coverage, baseline, CLI contract) |
| `.github/workflows/gate.yml` | new | lint + test + determinism check |

## What was changed in upstream files

`src/specify_cli/__init__.py` — two lines, to register the new command:

```python
from . import command_gate as _command_gate  # noqa: E402
_command_gate.register(app)
```

`README.md` — one section ("Deterministic gate"), appended under *Documentation*.

No other upstream file was touched. `git diff upstream/main --stat` shows only
these three paths.

## Upstream license

MIT — see [LICENSE](./LICENSE). The license text is unchanged; this notice exists
so that the origin of the code and the scope of the modifications stay visible.

## Why a fork instead of a separate package

The gate has to read Spec Kit's own artifact conventions (phase headings, `[USn]`
labels, `T###` ids, the `NEEDS CLARIFICATION` marker) and register itself on the
existing `specify` CLI. Shipping it as a fork keeps one install command and one
version line for users.
