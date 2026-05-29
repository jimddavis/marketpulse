"""RunContext — the per-run, environment-supplied context (WS0).

A frozen, dependency-free value object. Built by the composition root (the Databricks
notebook entry, or local main()/pytest) and threaded through the framework. The
package never reads notebook_init, dbutils, os.environ, or a SparkSession to fill it —
every field is injected (design §5, §8.1, §16.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable


@dataclass(frozen=True)
class RunContext:
    catalog: str                   # notebook_init CATALOG on Databricks; dummy locally
    pipeline_run_id: str           # notebook_init PIPELINE_RUN_ID (assumed present); "LOCALDEV" locally
    step_log_id: str               # minted once per run (uuid4) by the entry
    audit_schema: str              # f"{catalog}.audit" (notebook_init AUDIT)
    scratch_dir: str               # tempfile.gettempdir() — NEVER hardcode /local_disk0 (§16.8)
    now: Callable[[], datetime]    # injected clock for deterministic tests
