"""The expression language (rule R4).

A YAML string of the form ``"${ <expression> }"`` is an expression. The body is parsed with Python's
``ast`` module and only a whitelist of node types is accepted; ``eval`` is never used.

Names are parameter paths (``parts.pole_cap.thickness``) or study variable names (``q``). Values are
pint quantities during evaluation, so units are checked. Literal numbers are dimensionless, except that
``0`` takes whatever dimension it is combined with.
"""
from __future__ import annotations

import ast
import math
import operator
from typing import Any, Callable

import numpy as np
import pint

from bplsim.core.errors import ExpressionError
from bplsim.units import Q_, Dim, UnitSystem, dim_of


def is_expr(value: Any) -> bool:
    return isinstance(value, str) and value.strip().startswith("${") and value.strip().endswith("}")


class SlotPresent:
    """Value of a path naming an occupied slot (``parts.pole_cap``): truthy, not a number."""

    def __init__(self, name: str):
        self.name = name

    def __bool__(self) -> bool:
        return True

    def __repr__(self) -> str:
        return f"<slot {self.name}>"


_FUNCS: dict[str, Callable] = {
    "min": min, "max": max, "abs": abs,
    "sqrt": lambda x: x ** 0.5,
    "sin": lambda x: _trig(np.sin, x), "cos": lambda x: _trig(np.cos, x), "tan": lambda x: _trig(np.tan, x),
    "exp": lambda x: math.exp(_plain(x)), "log": lambda x: math.log(_plain(x)),
    "floor": lambda x: math.floor(_plain(x)), "ceil": lambda x: math.ceil(_plain(x)),
    "round": lambda x, n=0: round(_plain(x), int(n)),
}
_CONSTS = {"pi": math.pi, "true": True, "false": False, "none": None}

_ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.Call,
            ast.Name, ast.Attribute, ast.Constant, ast.Load, ast.Add, ast.Sub, ast.Mult, ast.Div,
            ast.FloorDiv, ast.Mod, ast.Pow, ast.USub, ast.UAdd, ast.Not, ast.And, ast.Or, ast.Eq,
            ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Tuple, ast.List)


def _plain(x):
    if isinstance(x, pint.Quantity):
        if not x.dimensionless:
            raise ExpressionError(f"function needs a dimensionless argument, got {x:~}")
        return float(x.to("").magnitude)
    return x


def _trig(fn, x):
    if isinstance(x, pint.Quantity):
        return float(fn(x.to("rad").magnitude))
    return float(fn(x))


def _dotted(node: ast.AST) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _align(a, b):
    """Apply the literal rules before +, -, comparisons and min/max."""
    qa, qb = isinstance(a, pint.Quantity), isinstance(b, pint.Quantity)
    if qa and not qb and isinstance(b, (int, float)) and not isinstance(b, bool):
        if b == 0:
            return a, Q_(0, a.units)
        if a.dimensionless:
            return float(a.to("").magnitude), b
        raise ExpressionError(f"cannot combine {a:~} with the dimensionless number {b} "
                              "(only 0 takes any dimension; name constants with units as parameters)")
    if qb and not qa:
        b2, a2 = _align(b, a)
        return a2, b2
    return a, b


_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_CMP = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le,
        ast.Gt: operator.gt, ast.GtE: operator.ge}


class Expr:
    """A parsed expression. `names` lists the paths/variables it may read."""

    def __init__(self, text: str, where: str = ""):
        self.text = text.strip()
        self.where = where
        body = self.text[2:-1] if is_expr(self.text) else self.text
        self.body = body.strip()
        try:
            self.tree = ast.parse(self.body, mode="eval")
        except SyntaxError as e:
            raise ExpressionError(f"invalid expression {self.text!r}: {e.msg}", path=where) from None
        for node in ast.walk(self.tree):
            if not isinstance(node, _ALLOWED):
                raise ExpressionError(f"{type(node).__name__} is not allowed in expressions ({self.text!r})",
                                      path=where)
            if isinstance(node, ast.Call) and not (isinstance(node.func, ast.Name) and node.func.id in _FUNCS):
                raise ExpressionError(f"only the functions {', '.join(sorted(_FUNCS))} may be called "
                                      f"({self.text!r})", path=where)
            if isinstance(node, ast.Attribute) and _dotted(node) is None:
                raise ExpressionError(f"attribute access only on parameter paths ({self.text!r})", path=where)

    def __repr__(self) -> str:
        return f"Expr({self.text})"

    def evaluate(self, lookup: Callable[[str], Any]) -> Any:
        try:
            return self._ev(self.tree.body, lookup)
        except ExpressionError as e:
            if not e.path and self.where:
                e.path = self.where
                e.args = (e.format(),)
            raise
        except pint.errors.DimensionalityError as e:
            raise ExpressionError(f"unit mismatch in {self.text!r}: {e}", path=self.where) from None
        except ZeroDivisionError:
            raise ExpressionError(f"division by zero in {self.text!r}", path=self.where) from None

    def _null(self, what: str):
        raise ExpressionError(f"{what} refers to an empty optional slot; guard it, e.g. "
                              f"'x if parts.<slot> else 0' ({self.text!r})", path=self.where)

    def _num(self, v, what):
        if v is None:
            self._null(what)
        if isinstance(v, SlotPresent):
            raise ExpressionError(f"{what} is a slot, not a number ({self.text!r})", path=self.where)
        return v

    def _ev(self, n: ast.AST, look):
        if isinstance(n, ast.Constant):
            if isinstance(n.value, (int, float, str, bool)) or n.value is None:
                return n.value
            raise ExpressionError(f"unsupported constant {n.value!r}", path=self.where)
        if isinstance(n, (ast.Name, ast.Attribute)):
            path = _dotted(n)
            if path in _CONSTS:
                return _CONSTS[path]
            return look(path)
        if isinstance(n, ast.UnaryOp):
            v = self._ev(n.operand, look)
            if isinstance(n.op, ast.Not):
                return not v
            v = self._num(v, ast.unparse(n.operand))
            return -v if isinstance(n.op, ast.USub) else +v
        if isinstance(n, ast.BinOp):
            a = self._num(self._ev(n.left, look), ast.unparse(n.left))
            b = self._num(self._ev(n.right, look), ast.unparse(n.right))
            if isinstance(n.op, (ast.Add, ast.Sub)):
                a, b = _align(a, b)
            return _BIN[type(n.op)](a, b)
        if isinstance(n, ast.BoolOp):
            if isinstance(n.op, ast.And):
                v = True
                for x in n.values:
                    v = self._ev(x, look)
                    if not v:
                        return v
                return v
            v = False
            for x in n.values:
                v = self._ev(x, look)
                if v:
                    return v
            return v
        if isinstance(n, ast.Compare):
            left = self._ev(n.left, look)
            for op, right_node in zip(n.ops, n.comparators):
                right = self._ev(right_node, look)
                if isinstance(op, (ast.In, ast.NotIn)):
                    ok = (left in right) if isinstance(op, ast.In) else (left not in right)
                else:
                    a, b = _align(left, right) if not isinstance(left, str) and not isinstance(right, str) \
                        else (left, right)
                    if (a is None or b is None) and not isinstance(op, (ast.Eq, ast.NotEq)):
                        self._null(ast.unparse(n))
                    ok = _CMP[type(op)](a, b)
                if not ok:
                    return False
                left = right
            return True
        if isinstance(n, ast.IfExp):
            return self._ev(n.body, look) if self._ev(n.test, look) else self._ev(n.orelse, look)
        if isinstance(n, ast.Call):
            args = [self._num(self._ev(a, look), ast.unparse(a)) for a in n.args]
            name = n.func.id
            if name in ("min", "max") and len(args) > 1:
                base = args[0]
                aligned = [base]
                for x in args[1:]:
                    p, q = _align(base, x)
                    aligned[0] = p
                    aligned.append(q)
                args = aligned
            return _FUNCS[name](*args)
        if isinstance(n, (ast.Tuple, ast.List)):
            return [self._ev(x, look) for x in n.elts]
        raise ExpressionError(f"unsupported syntax in {self.text!r}", path=self.where)


def coerce(value: Any, target: Dim | None, units: UnitSystem, what: str = "") -> tuple[Any, Dim | None]:
    """Convert an evaluated expression value to (SI float, Dim) for a target dimension.

    target None means "infer the dimension from the value"."""
    if isinstance(value, pint.Quantity):
        if target is None:
            d = dim_of(value)
            return units.quantity_to_si(value, d), d
        try:
            return units.quantity_to_si(value, target), target
        except ValueError as e:
            raise ExpressionError(f"{what}: {e}") from None
    if isinstance(value, bool) or value is None or isinstance(value, (str, SlotPresent)):
        return value, None
    if isinstance(value, (int, float)):
        if target is None or not target.si or value == 0:
            return (float(value) if not isinstance(value, int) else value), target
        raise ExpressionError(f"{what}: expression gives the dimensionless number {value}, but a "
                              f"{target.name} is required")
    return value, target
