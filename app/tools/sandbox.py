"""Restricted Python executor for planner-generated analysis.

The agent never executes source text from the user. It executes a short program
that this service generated, and only after the AST is on the allowlist.
"""

from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout

ALLOWED_FUNCS = {
    "len",
    "range",
    "sorted",
    "min",
    "max",
    "sum",
    "abs",
    "round",
    "str",
    "int",
    "float",
    "list",
    "dict",
    "set",
    "enumerate",
}
ALLOWED_ATTRS = {"get", "items", "keys", "values", "append", "lower", "split", "update", "add"}
ALLOWED_NODES = (
    ast.Module,
    ast.Assign,
    ast.AnnAssign,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Constant,
    ast.For,
    ast.If,
    ast.Compare,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.Subscript,
    ast.Call,
    ast.Attribute,
    ast.keyword,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.Expr,
    ast.Continue,
    ast.Break,
    ast.Pass,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.FloorDiv,
    ast.And,
    ast.Or,
    ast.Not,
    ast.UAdd,
    ast.USub,
)


class SandboxError(Exception):
    pass


def execute(code: str, **bindings) -> dict:
    if len(code) > 4000:
        raise SandboxError("code is too long")
    tree = _parse(code)
    _validate(tree, set(bindings))
    result: dict = {}
    safe_builtins = {name: __builtins__[name] if isinstance(__builtins__, dict) else getattr(__builtins__, name) for name in ALLOWED_FUNCS}
    env: dict = {"__builtins__": safe_builtins, **bindings, "result": result}

    def runner() -> None:
        exec(compile(tree, "<analysis>", "exec"), env, env)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runner)
        try:
            future.result(timeout=1)
        except FuturesTimeout as exc:
            raise SandboxError("timeout") from exc
        except SandboxError:
            raise
        except Exception as exc:
            raise SandboxError(type(exc).__name__) from exc
    if not isinstance(env.get("result"), dict):
        raise SandboxError("result must be a dict")
    return env["result"]


def _parse(code: str) -> ast.AST:
    try:
        return ast.parse(code)
    except SyntaxError as exc:
        raise SandboxError("syntax error") from exc


def _validate(tree: ast.AST, bindings: set[str]) -> None:
    stored = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }
    allowed_names = ALLOWED_FUNCS | bindings | stored | {"result"}
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_NODES):
            raise SandboxError(f"unsupported syntax: {type(node).__name__}")
        if isinstance(node, ast.Name):
            if node.id.startswith("_") or (isinstance(node.ctx, ast.Load) and node.id not in allowed_names):
                raise SandboxError(f"name not allowed: {node.id}")
        if isinstance(node, ast.Attribute) and (node.attr not in ALLOWED_ATTRS or node.attr.startswith("_")):
            raise SandboxError(f"attribute not allowed: {node.attr}")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("__"):
            raise SandboxError("dunder constants are not allowed")
        if isinstance(node, ast.Call):
            _validate_call(node)


def _validate_call(node: ast.Call) -> None:
    if isinstance(node.func, ast.Name):
        if node.func.id not in ALLOWED_FUNCS:
            raise SandboxError(f"call not allowed: {node.func.id}")
        if node.func.id == "range":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, int) and abs(arg.value) > 10_000:
                    raise SandboxError("range is too large")
        return
    if isinstance(node.func, ast.Attribute):
        return
    raise SandboxError("indirect calls are not allowed")
