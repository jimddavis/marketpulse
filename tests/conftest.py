"""Pytest bootstrap — put databricks_code/libs on sys.path so `import data_fetch`
resolves without installing the package (mirrors how notebook_init extends sys.path on
Databricks). No network, no SparkSession (design §11, §16.13).
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
# databricks_code/libs → `import data_fetch`, `import pipeline_logging`.
# repo root → `import AUDIT_DDL` (the audit DDL module lives at the project root).
for _p in (str(_ROOT / "databricks_code" / "libs"), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
