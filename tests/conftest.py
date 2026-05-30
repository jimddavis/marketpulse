"""Pytest bootstrap — put databricks_code/libs on sys.path so `import data_fetch`
resolves without installing the package (mirrors how notebook_init extends sys.path on
Databricks). No network, no SparkSession (design §11, §16.13).
"""

from __future__ import annotations

import sys
from pathlib import Path

# databricks_code/libs → `import data_fetch`, `import ddl`, `import pipeline_logging`.
_LIBS = Path(__file__).resolve().parent.parent / "databricks_code" / "libs"
if str(_LIBS) not in sys.path:
    sys.path.insert(0, str(_LIBS))
