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

