#!/usr/bin/env bash
# Reference solution for bench-seccodebench-cwe94 (code injection / eval).
#
# Replaces the raw eval() of the untrusted expression with a small
# allowlist AST interpreter: the expression must be a dictionary literal
# built from literals, string-key lookups on input_data, arithmetic,
# comparisons, and boolean operators. Anything else (calls, attribute
# access, foreign names, other subscript bases) raises ValueError before
# any of the input's semantics is executed.
set -euo pipefail

cat > /app/workflow_transformer/workflow_transformer.py <<'PYEOF'
"""
Workflow data transformation module for processing step outputs.

The transformation expression is a restricted Python expression (a
dictionary literal built from literals and safe operations over
``input_data``). It is interpreted by a small allowlist AST evaluator
instead of ``eval``: no function calls, no attribute access, no names
other than ``input_data`` — so untrusted input cannot execute code
(CWE-94).
"""

import ast
import operator

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}

_UNARY_OPS = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_COMPARE_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


class _UnsafeExpression(ValueError):
    """Raised when an expression is outside the allowed language."""


def _eval_node(node: ast.AST, data: dict):
    """Recursively evaluate a whitelisted AST node against ``data``."""
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, data)
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        if node.id == "input_data":
            return data
        raise _UnsafeExpression(f"name {node.id!r} is not allowed")

    if isinstance(node, ast.Dict):
        result = {}
        for key, value in zip(node.keys, node.values):
            if key is None:  # {'k': v, **other} unpacking
                raise _UnsafeExpression("dict unpacking is not allowed")
            result[_eval_node(key, data)] = _eval_node(value, data)
        return result

    if isinstance(node, ast.Subscript):
        if not (isinstance(node.value, ast.Name) and node.value.id == "input_data"):
            raise _UnsafeExpression("subscripts must target input_data")
        key = _eval_node(node.slice, data)
        if not isinstance(key, str):
            raise _UnsafeExpression("subscript keys must be strings")
        return data[key]

    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise _UnsafeExpression(
                f"operator {type(node.op).__name__} is not allowed"
            )
        return op(_eval_node(node.left, data), _eval_node(node.right, data))

    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise _UnsafeExpression(
                f"unary operator {type(node.op).__name__} is not allowed"
            )
        return op(_eval_node(node.operand, data))

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result = True
            for value in node.values:
                result = _eval_node(value, data)
                if not result:
                    return result
            return result
        if isinstance(node.op, ast.Or):
            result = False
            for value in node.values:
                result = _eval_node(value, data)
                if result:
                    return result
            return result
        raise _UnsafeExpression(
            f"boolean operator {type(node.op).__name__} is not allowed"
        )

    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, data)
        for op_node, right_node in zip(node.ops, node.comparators):
            op = _COMPARE_OPS.get(type(op_node))
            if op is None:
                raise _UnsafeExpression(
                    f"comparison {type(op_node).__name__} is not allowed"
                )
            right = _eval_node(right_node, data)
            if not op(left, right):
                return False
            left = right
        return True

    raise _UnsafeExpression(f"expression node {type(node).__name__} is not allowed")


def transform_step_data(transform_map_expr: str, input_data: dict) -> dict:
    """
    Transforms input data using a provided expression string.

    Args:
        transform_map_expr: A string representing a Python dictionary
            literal that defines how to map input fields to output fields.
            Only literals, string-key lookups on ``input_data``, arithmetic,
            comparisons, and boolean operators are permitted; anything else
            raises ``ValueError``.
        input_data: Dictionary containing the input data from a previous step.

    Returns:
        A new dictionary with transformed data according to the expression.
    """
    try:
        tree = ast.parse(transform_map_expr, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid transformation expression: {exc}") from exc

    result = _eval_node(tree.body, input_data)
    if not isinstance(result, dict):
        raise ValueError("Expression must evaluate to a dictionary")
    return result
PYEOF

echo "Patched /app/workflow_transformer/workflow_transformer.py"
