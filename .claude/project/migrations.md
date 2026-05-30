# In-flight migrations and forbidden strings

## In-flight migrations

A LIVING list. New code MUST use the new pattern. Do not "fix" new-pattern
code back to the old. Do not propagate the old pattern to new files.

Protocol for completing one: see § 20 of `CLAUDE.md`. When complete, remove
from this section and add the old-pattern tripwire to *Forbidden strings*
below.

_(none currently in flight)_

---

## Forbidden strings

Regression tripwires for COMPLETED migrations. Before declaring any task
complete, grep changed files for these strings. If found in NEW or MODIFIED
code, stop and fix.

This list grows as migrations finish; it never shrinks except by deliberate
decision.

### `except dbutils.NotebookExit: raise` (treating `dbutils.NotebookExit` as a real class)

**Forbidden as of 2026-05-30.** There is no `dbutils.NotebookExit` class — the
guard was a no-op invented in vinoworld. `dbutils.notebook.exit()` raises an
ordinary exception that `except Exception` swallows, so it must be called
**OUTSIDE** the `try` (set a flag inside the try, exit after). See
`.claude/project/gotchas.md` → "`except Exception` swallows
`dbutils.notebook.exit()`".

Tripwire greps (must return zero in NEW or MODIFIED code):
- `except dbutils.NotebookExit`
- `NotebookExit: raise`

Allowed ONLY in corrective prose that documents the ban (gotchas.md, this file,
design-doc errata, the implement-prompt warning). Pre-existing exploration
notebooks under `_dev_planning/log_error_handling_alternatives/` are historical
artifacts and were intentionally left unchanged.

