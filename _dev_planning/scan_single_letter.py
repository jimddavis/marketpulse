#!/usr/bin/env python3
"""Scan project source for single-letter variable bindings (CLAUDE.md naming rule).

AST-based: flags single-character identifiers introduced as assignment targets,
for-loop / comprehension targets, except-as names, with-as names, lambda args,
and function/method parameters. Exceptions per CLAUDE.md: `F` (pyspark alias) and
`_` (throwaway). `df` / `*_df` are 2+ chars so never single-letter.

Handles both .py files and Jupyter .ipynb code cells.
"""
from __future__ import annotations

import ast
import json
import sys
from collections import defaultdict
from pathlib import Path

ALLOWED = {"F", "_"}
REPO = Path(__file__).resolve().parent.parent

SEARCH_ROOTS = ["databricks_code", "scripts", "tests", "_dev_planning"]
EXCLUDE_PARTS = {".venv", ".databricks", "__pycache__", ".git", ".claude"}


def is_excluded(path: Path) -> bool:
    return any(part in EXCLUDE_PARTS for part in path.parts)


class Collector(ast.NodeVisitor):
    def __init__(self) -> None:
        # name -> list of (lineno, kind)
        self.hits: dict[str, list[tuple[int, str]]] = defaultdict(list)

    def _flag(self, name: str | None, lineno: int, kind: str) -> None:
        if name and len(name) == 1 and name not in ALLOWED:
            self.hits[name].append((lineno, kind))

    def visit_Assign(self, node: ast.Assign) -> None:
        for tgt in node.targets:
            self._flag_target(tgt, node.lineno, "assign")
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._flag_target(node.target, node.lineno, "assign")
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._flag_target(node.target, node.lineno, "augassign")
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self._flag_target(node.target, node.lineno, "for")
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self._flag_target(node.target, getattr(node.target, "lineno", 0), "comp")
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self._flag(node.name, node.lineno, "except-as")
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                self._flag_target(item.optional_vars, node.lineno, "with-as")
        self.generic_visit(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for arg in self._all_args(node.args):
            self._flag(arg.arg, node.lineno, "lambda-arg")
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for arg in self._all_args(node.args):
            self._flag(arg.arg, node.lineno, "func-param")
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)  # same handling

    @staticmethod
    def _all_args(a: ast.arguments) -> list[ast.arg]:
        result = list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)
        if a.vararg:
            result.append(a.vararg)
        if a.kwarg:
            result.append(a.kwarg)
        return result

    def _flag_target(self, tgt: ast.AST, lineno: int, kind: str) -> None:
        if isinstance(tgt, ast.Name):
            self._flag(tgt.id, lineno, kind)
        elif isinstance(tgt, (ast.Tuple, ast.List)):
            for elt in tgt.elts:
                self._flag_target(elt, lineno, kind)
        elif isinstance(tgt, ast.Starred):
            self._flag_target(tgt.value, lineno, kind)


def scan_source(src: str) -> dict[str, list[tuple[int, str]]]:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return {}
    collector = Collector()
    collector.visit(tree)
    return collector.hits


def notebook_source(path: Path) -> str:
    """Concatenate code cells. Magics (%run, %skip, %sql) and shell (!) lines are
    blanked so the cell still parses as Python; line numbers are approximate per-cell."""
    nb = json.loads(path.read_text(encoding="utf-8"))
    chunks: list[str] = []
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        lines = []
        for raw in cell.get("source", []):
            stripped = raw.lstrip()
            if stripped.startswith(("%", "!")):
                lines.append("pass  # magic\n")
            else:
                lines.append(raw)
        chunks.append("".join(lines))
    return "\n\n".join(chunks)


def main() -> int:
    files: list[Path] = []
    for root in SEARCH_ROOTS:
        base = REPO / root
        if not base.exists():
            continue
        for ext in ("*.py", "*.ipynb"):
            files.extend(p for p in base.rglob(ext) if not is_excluded(p))
    # exclude this scanner itself
    files = sorted(set(files) - {Path(__file__).resolve()})

    grand_total = 0
    for path in files:
        if path.suffix == ".ipynb":
            src = notebook_source(path)
        else:
            src = path.read_text(encoding="utf-8")
        hits = scan_source(src)
        if not hits:
            continue
        rel = path.relative_to(REPO)
        file_count = sum(len(v) for v in hits.values())
        grand_total += file_count
        print(f"\n=== {rel}  ({file_count} hits) ===")
        for name in sorted(hits):
            occ = hits[name]
            kinds = sorted({k for _, k in occ})
            linenos = ", ".join(str(ln) for ln, _ in occ)
            print(f"  '{name}'  x{len(occ)}  [{','.join(kinds)}]  lines~ {linenos}")

    print(f"\n\nGRAND TOTAL single-letter bindings: {grand_total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
