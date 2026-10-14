# PM-era installs: ask the package manager

The in-tree resolver answers "which venv directory does this checkout have". On a
**PM-era install (2026-09 onward)** there is no in-tree venv at all: PM keeps the
dependency environment under `$HERMES_HOME/installs/<key>/environments/` and the
shared runtime store in `$HERMES_HOME/tools`, and it removes a legacy in-tree
venv once a generation is committed.

So `project_venv_dir()` can return `None` **even though a dependency environment
exists** — it never looks under `$HERMES_HOME/installs/<key>/environments/`. A
`None` there means "wrong question", not "nothing installed".

Ask PM instead:

| Call | Returns |
|---|---|
| `committed_venv(root)` | the **venv directory** PM committed, or `None` |
| `project_python(root)` | the **interpreter executable** — never `None` |

**These are not interchangeable, in two ways.**

`venv_bin_dir()` appends `bin`/`Scripts` to a venv *directory*, so pass it
`committed_venv()`'s result — never `project_python()`'s, which would yield
`.../bin/bin/python`.

And they answer different questions, which decides which one you may trust.
`project_python()` is `venv_python(selected_venv(root))`, and `selected_venv()`
falls back through `base_venv()` to the in-tree `venv` directory — so it
**cannot return `None`** even when PM has committed nothing. On an install with
no committed generation it returns `<root>/venv/bin/python`, a path that does
not exist, and a caller that launches it gets a failure that looks like a broken
interpreter rather than an uncommitted environment.

> [!IMPORTANT]
> Verify a committed environment exists before using `project_python()`. Either call `committed_venv(root)` first and handle `None`, or check the returned path with `Path.is_file()` before executing it. `venv_python()` is documented as returning a path that *may not exist*, so the existence check is the caller's job.

Both calls read the same record, so both raise `RuntimeError` when it exists but cannot be read or parsed. Handle three outcomes rather than assuming success:

- **`committed_venv()` → `None`** — no generation is committed yet. Not an error
  yet; the first `hermes update` creates it. Do **not** fall back to
  `project_python()` here: that is the stale-interpreter path above.
- **`RuntimeError`** — the record exists but cannot be read or parsed (the
  record-reading helper in `pm/environments.py`). Treat this as *corrupt dependency
  state*: re-run `hermes update`. Do **not** report it as "no environment",
  which sends the reader down the wrong path entirely.
- **`committed_venv()` → a path that fails `is_dir()`** — the record names an
  environment that is gone, or it was removed by hand. Re-run `hermes update`.
  Note the asymmetry: this is a **directory**, so test it with `is_dir()`.
  `is_file()` belongs only to the executable from `project_python()`, and a
  valid committed environment is not a file — checking the directory with
  `is_file()` rejects every healthy install.
