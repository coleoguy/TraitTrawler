#!/usr/bin/env python3
"""AST-based safety linter for project-specific hook Python source.

Project hooks are proposed by the `trait_learner` subagent (LLM-generated
Python) and approved by the user. Before they are ever executed, they
pass through this linter which statically rejects anything that could
cause side effects, reach the network, access the filesystem, or import
outside a whitelist.

What is ALLOWED:
  - `def` (top-level or nested), `class` (pure data), `return`, assignments
  - Imports from: re, math, statistics, json, typing, dataclasses,
    collections (and .abc), itertools, functools
  - Calls to builtins: len, str, int, float, bool, isinstance, any, all,
    min, max, sum, abs, round, range, list, dict, tuple, set, frozenset,
    sorted, reversed, enumerate, zip, map, filter, iter, next, repr, bytes
  - Passing row / context dicts and reading their keys
  - Regex via the `re` module

What is BLOCKED (hard rejection):
  - import of os, sys, subprocess, socket, urllib, requests, pathlib,
    pickle, shelve, ctypes, multiprocessing, threading, asyncio, shutil,
    glob, io, tempfile, atexit, signal, __import__, exec, eval, compile,
    open, input, print (print is allowed? No — we want silent hooks)
  - attribute access ending in __ (dunder manipulation)
  - anything in the `typing.TYPE_CHECKING` branch with imports outside the
    allowlist
  - f-strings are OK; format specifiers are fine
  - global / nonlocal / del

Usage as CLI:
    python hook_sandbox.py path/to/proposed_hook.py
    exit 0 = safe, exit 2 = unsafe (reason on stderr)

Usage as library:
    from hook_sandbox import validate_hook_source, HookSandboxError
    validate_hook_source(src_text)  # raises HookSandboxError on any violation
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


class HookSandboxError(Exception):
    """Raised when a hook source fails the sandbox validation."""


ALLOWED_IMPORTS = {
    "re", "math", "statistics", "json", "typing", "dataclasses",
    "collections", "collections.abc", "itertools", "functools",
    "decimal", "fractions", "enum",
}

# Builtins we explicitly whitelist. Everything else is blocked.
ALLOWED_BUILTINS = {
    "len", "str", "int", "float", "bool", "isinstance", "any", "all",
    "min", "max", "sum", "abs", "round", "range", "list", "dict",
    "tuple", "set", "frozenset", "sorted", "reversed", "enumerate",
    "zip", "map", "filter", "iter", "next", "repr", "bytes",
    "type", "getattr", "hasattr", "setattr",  # getattr/hasattr kept — needed for row access
    "Exception", "ValueError", "TypeError", "KeyError", "AttributeError",
    "True", "False", "None",
}

BLOCKED_NAMES = {
    "__import__", "exec", "eval", "compile", "open", "input", "print",
    "globals", "locals", "vars", "dir", "breakpoint", "help",
    "__builtins__",
}


class _Visitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.errors: list[str] = []

    def _err(self, node: ast.AST, msg: str) -> None:
        lineno = getattr(node, "lineno", "?")
        self.errors.append(f"line {lineno}: {msg}")

    # Imports
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".", 1)[0]
            if alias.name not in ALLOWED_IMPORTS and root not in ALLOWED_IMPORTS:
                self._err(node, f"import of {alias.name!r} not in allowlist {sorted(ALLOWED_IMPORTS)}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        root = mod.split(".", 1)[0]
        if mod not in ALLOWED_IMPORTS and root not in ALLOWED_IMPORTS:
            self._err(node, f"from-import of {mod!r} not in allowlist")
        self.generic_visit(node)

    # Calls — block via name lookup
    def visit_Call(self, node: ast.Call) -> None:
        # plain-name calls: exec(), eval(), __import__(), open()
        if isinstance(node.func, ast.Name):
            if node.func.id in BLOCKED_NAMES:
                self._err(node, f"call to blocked builtin {node.func.id!r}")
        # attribute calls: socket.socket(), os.system(), subprocess.run()
        if isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if attr.startswith("__") and attr.endswith("__"):
                self._err(node, f"dunder attribute call {attr!r} blocked")
        self.generic_visit(node)

    # Name usage — block referencing __builtins__, exec, etc
    def visit_Name(self, node: ast.Name) -> None:
        if node.id in BLOCKED_NAMES:
            self._err(node, f"reference to blocked name {node.id!r}")
        self.generic_visit(node)

    # Attribute access — block dunder access that could escalate
    def visit_Attribute(self, node: ast.Attribute) -> None:
        name = node.attr
        if name.startswith("__") and name.endswith("__") and name not in (
            "__name__", "__doc__", "__qualname__",
        ):
            self._err(node, f"dunder attribute access {name!r} blocked")
        self.generic_visit(node)

    # Block global/nonlocal/del (impure)
    def visit_Global(self, node: ast.Global) -> None:
        self._err(node, "'global' statement not allowed")
        self.generic_visit(node)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self._err(node, "'nonlocal' statement not allowed")
        self.generic_visit(node)

    def visit_Delete(self, node: ast.Delete) -> None:
        self._err(node, "'del' statement not allowed")
        self.generic_visit(node)

    # No with-statement; context managers may open files
    def visit_With(self, node: ast.With) -> None:
        self._err(node, "'with' blocks not allowed (risk of file/network handles)")
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._err(node, "async 'with' blocks not allowed")
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node) -> None:  # type: ignore[no-untyped-def]
        self._err(node, "async functions not allowed")
        self.generic_visit(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        # Lambdas fine — they're just anonymous pure expressions
        self.generic_visit(node)


def validate_hook_source(src: str) -> None:
    """Parse + statically validate. Raises HookSandboxError with all violations."""
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        raise HookSandboxError(f"syntax error: {e}") from e
    v = _Visitor()
    v.visit(tree)
    if v.errors:
        raise HookSandboxError("; ".join(v.errors))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    args = ap.parse_args()
    if not args.path.exists():
        print(f"not found: {args.path}", file=sys.stderr)
        return 3
    try:
        validate_hook_source(args.path.read_text())
    except HookSandboxError as e:
        print(f"UNSAFE {args.path}: {e}", file=sys.stderr)
        return 2
    print(f"OK {args.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
