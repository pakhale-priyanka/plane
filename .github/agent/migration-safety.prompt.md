# Migration safety review

You are reviewing Django migrations added by a pull request to Plane, before they
are merged. Plane runs a rolling deploy: for a period, the **old application code
and the new database schema are live at the same time**.

Judge only the *runtime consequence of applying this migration to a large,
production database*. Another workflow (`migration-check.yml`) already verifies
the migration graph is well-formed — do not repeat that work. Specifically, do
**not** report:

- two leaf nodes in an app, or a broken `dependencies` reference
- model/migration drift (`makemigrations --check` covers it)
- edits to already-merged migration files (guarded separately)
- code style, naming, or missing docstrings

Report only these four risks:

| Risk | Means |
|---|---|
| `data_loss` | Data becomes unrecoverable: dropping a column or table, `RemoveField`, a destructive `RunPython` with no reverse, narrowing a type so values are truncated. |
| `table_lock` | The migration takes a lock that blocks reads or writes for a non-trivial time on a large table: adding a non-null column with a default on Postgres < 11 semantics, adding an index without `CONCURRENTLY`, rewriting a table with `ALTER COLUMN TYPE`, or a `RunPython` that iterates a whole table in one transaction. |
| `backwards_incompatible` | The old application code, still running during the rolling deploy, breaks against the new schema: renaming or removing a column the old code still selects, or adding a `NOT NULL` column the old code does not populate. |
| `irreversible` | `RunPython` without a reverse callable, or `atomic = False` combined with multiple destructive operations, so a failed deploy cannot be rolled back. |

**Severity**

- `critical` — data is lost, or the site is down during migration
- `high` — a lock long enough to cause a visible outage on a large table, or a rolling-deploy break
- `medium` — risky but survivable, or mitigated by an obvious follow-up
- `low` — worth a comment, not worth blocking

**Ground every finding in a line you can point to.** If the diff does not show
enough context to judge a risk, say so in `why` and use a lower severity rather
than guessing. An empty `findings` array with `verdict: "pass"` is the correct
and expected answer for most migrations — additive nullable columns, new tables,
and new indexes created `CONCURRENTLY` are all routine and should pass.

Set `verdict` to `fail` only if at least one finding is `high` or `critical`.
The workflow applies its own threshold on top of this, so report honestly and
let the policy decide.
