"""Safe parser for simple function-call strings.

Parses strings like:
  check_build_plate(allowed_build_plates=[2, 4], check_empty=True)

Returns (function_name, kwargs_dict). Supports ints, floats, strings, booleans (True/False or true/false), None, lists/tuples/dicts/sets of those.
"""

from __future__ import annotations
import ast
from typing import Any, Dict, Tuple


class ParseError(ValueError):
    pass


def _safe_eval(node: ast.AST | None) -> Any:
    """Recursively evaluate a limited set of AST nodes into Python literals.
    Allows lowercase true/false/none as well as Python True/False/None.
    """
    # Constant covers numbers, strings, booleans, None in modern Python
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        name = node.id
        lower = name.lower()
        if lower == "true":
            return True
        if lower == "false":
            return False
        if lower in ("none", "null"):
            return None
        raise ParseError(f"unsupported name literal: {name}")

    if isinstance(node, ast.List):
        return [_safe_eval(elt) for elt in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_safe_eval(elt) for elt in node.elts)
    if isinstance(node, ast.Set):
        return set(_safe_eval(elt) for elt in node.elts)
    if isinstance(node, ast.Dict):
        keys = [_safe_eval(k) for k in node.keys]
        values = [_safe_eval(v) for v in node.values]
        return dict(zip(keys, values))

    # Not allowed node types
    raise ParseError(f"unsupported expression node: {type(node).__name__}")


def parse_function_call(s: str) -> Tuple[str, Dict[str, Any]]:
    """Parse a function call string and return (func_name, kwargs dict).

    Raises ParseError for invalid input. Only named keyword arguments are allowed.
    """
    try:
        tree = ast.parse(s, mode="eval")
    except SyntaxError as e:
        raise ParseError(f"syntax error: {e}")

    node = tree.body
    if not isinstance(node, ast.Call):
        raise ParseError("expected a single function call expression")

    # Only allow simple function names (no attributes, subscripts, etc.)
    func = node.func
    if isinstance(func, ast.Name):
        func_name = func.id
    else:
        raise ParseError("function must be a simple name")

    # Disallow positional args
    if node.args:
        raise ParseError(
            "positional arguments are not supported; use named arguments only"
        )

    kwargs: Dict[str, Any] = {}
    for kw in node.keywords:
        if kw.arg is None:
            raise ParseError("**kwargs (keyword unpacking) is not supported")
        try:
            value = _safe_eval(kw.value)
        except ParseError:
            raise
        except Exception as e:
            raise ParseError(f"failed to parse value for '{kw.arg}': {e}")
        kwargs[kw.arg] = value

    return func_name, kwargs


__all__ = ["parse_function_call", "ParseError"]
