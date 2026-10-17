from __future__ import annotations

import ast
import re

CELL_REFERENCE = re.compile(r"\b([A-Z]+)([1-9][0-9]*)\b")
PERCENTAGE = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)%")
FUNCTION_RANGE = re.compile(
    r"(SUM|SOMME|AVERAGE|MOYENNE|MIN|MAX|COUNT|NB)\(([A-Z]+[1-9][0-9]*):([A-Z]+[1-9][0-9]*)\)",
    re.IGNORECASE,
)


def evaluate_table(text: str) -> list[list[str]]:
    rows = [row.split("\t") for row in text.splitlines()]
    return _evaluate_rows(rows)


def evaluate_table_cells(cells: list[list[dict[str, str]]]) -> list[list[str]]:
    """Evaluate the textual/formula content of structured document-table cells."""
    return _evaluate_rows(
        [[cell.get("text", "") for cell in row] for row in cells]
    )


def _evaluate_rows(rows: list[list[str]]) -> list[list[str]]:
    if not rows:
        return [[""]]
    width = max((len(row) for row in rows), default=1)
    rows = [row + [""] * (width - len(row)) for row in rows]
    cache: dict[tuple[int, int], float | str] = {}

    def value(row: int, column: int, trail: set[tuple[int, int]]) -> float | str:
        key = (row, column)
        if key in cache:
            return cache[key]
        if key in trail or not (0 <= row < len(rows) and 0 <= column < width):
            return "#ERREUR"
        raw = rows[row][column].strip()
        if not raw.startswith("="):
            try:
                result: float | str = float(raw.replace(",", "."))
            except ValueError:
                result = raw
            cache[key] = result
            return result
        expression = raw[1:].upper().replace(",", ".")
        expression = _expand_functions(expression, lambda r, c: value(r, c, trail | {key}))

        def replace_cell(match: re.Match[str]) -> str:
            row_index, column_index = _cell_coordinates(match.group(0))
            resolved = value(row_index, column_index, trail | {key})
            return str(resolved) if isinstance(resolved, float) else "0"

        expression = CELL_REFERENCE.sub(replace_cell, expression)
        expression = PERCENTAGE.sub(lambda match: str(float(match.group(1).replace(",", ".")) / 100), expression)
        try:
            result = _safe_calculate(expression)
        except (ValueError, ZeroDivisionError, SyntaxError):
            result = "#ERREUR"
        cache[key] = result
        return result

    return [[_format(value(row, column, set())) for column in range(width)] for row in range(len(rows))]


def _expand_functions(expression: str, resolver: object) -> str:
    def replace(match: re.Match[str]) -> str:
        function = match.group(1).upper()
        start_row, start_column = _cell_coordinates(match.group(2))
        end_row, end_column = _cell_coordinates(match.group(3))
        values: list[float] = []
        for row in range(min(start_row, end_row), max(start_row, end_row) + 1):
            for column in range(min(start_column, end_column), max(start_column, end_column) + 1):
                resolved = resolver(row, column)  # type: ignore[operator]
                if isinstance(resolved, float):
                    values.append(resolved)
        if function in {"COUNT", "NB"}:
            return str(float(len(values)))
        if not values:
            return "0"
        if function in {"AVERAGE", "MOYENNE"}:
            return str(sum(values) / len(values))
        if function == "MIN":
            return str(min(values))
        if function == "MAX":
            return str(max(values))
        return str(sum(values))

    return FUNCTION_RANGE.sub(replace, expression)


def _cell_coordinates(reference: str) -> tuple[int, int]:
    match = CELL_REFERENCE.fullmatch(reference.upper())
    if not match:
        raise ValueError(reference)
    column = 0
    for character in match.group(1):
        column = column * 26 + ord(character) - 64
    return int(match.group(2)) - 1, column - 1


def _safe_calculate(expression: str) -> float:
    tree = ast.parse(expression, mode="eval")

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            return left / right
        raise ValueError("Expression interdite")

    return visit(tree)


def _format(value: float | str) -> str:
    if isinstance(value, str):
        return value
    return str(int(value)) if value.is_integer() else f"{value:.4f}".rstrip("0").rstrip(".").replace(".", ",")
