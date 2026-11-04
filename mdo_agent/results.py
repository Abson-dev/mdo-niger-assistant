"""Turn a tool result into what the reader sees: rows, a checked chart choice, the sources and the cautions.

The model only names columns and a chart type. This module checks them against the rows and refuses a chart the data
cannot support; the browser draws the chart from this checked description, so nothing the model writes runs as code.
The cautions come from the tool that made the table, so the model cannot leave them out.
"""
from __future__ import annotations

import math

import pandas as pd

CHARTS = ("table", "line", "bar", "scatter", "heatmap", "map")
TIME_COLUMNS = ("year", "week")


class PublishError(ValueError):
    pass


def records(df: pd.DataFrame) -> list[dict]:
    """JSON-safe rows: missing values become null."""
    out = []
    for row in df.to_dict(orient="records"):
        out.append({k: (None if isinstance(v, float) and math.isnan(v) else v.item() if hasattr(v, "item") else v)
                    for k, v in row.items()})
    return out


def _numeric(df: pd.DataFrame, col: str) -> bool:
    return pd.api.types.is_numeric_dtype(df[col]) and not pd.api.types.is_bool_dtype(df[col])


def _need(df: pd.DataFrame, col: str, role: str) -> None:
    if not col:
        raise PublishError(f"A {role} column is required for this chart.")
    if col not in df.columns:
        raise PublishError(f"No column '{col}'.")


def check_chart(df: pd.DataFrame, chart: str, x: str, y: str, series: str, limits: dict, regions: set[str]) -> None:
    if chart not in CHARTS:
        raise PublishError(f"Chart must be one of {', '.join(CHARTS)}.")
    if chart == "table":
        return
    _need(df, x, "x")
    _need(df, y, "y")
    if series:
        _need(df, series, "series")
    if chart == "map":
        if not _numeric(df, y):
            raise PublishError(f"Column '{y}' is not numeric.")
        names = set(df[x].dropna().astype(str))
        if not names or not names <= regions:
            raise PublishError(f"A map needs one row per region in column x; the map has the 8 regions only, and '{x}' holds {sorted(names - regions)[:3]}.")
        if df[x].duplicated().any():
            raise PublishError("A map needs one row per region; filter to one year first.")
        return
    if chart == "heatmap":
        if not series or not _numeric(df, series):
            raise PublishError("A heatmap needs a numeric series column for its cells.")
        if df.duplicated([x, y]).any():
            raise PublishError(f"A heatmap needs one row per {x} and {y}; filter the table first.")
        return
    if chart == "scatter":
        if not (_numeric(df, x) and _numeric(df, y)):
            raise PublishError("A scatter plot needs two numeric columns.")
        if df[[x, y]].dropna().shape[0] < 3:
            raise PublishError("A scatter plot needs at least 3 points.")
        return
    if not _numeric(df, y) and not (chart == "bar" and _numeric(df, x)):
        raise PublishError(f"Column '{y}' is not numeric.")
    if series and df[series].nunique() > limits["max_series"]:
        raise PublishError(f"Too many series ({df[series].nunique()}, at most {limits['max_series']}); narrow the groups.")
    keys = [x] + ([series] if series else [])
    if df.duplicated(keys).any():
        raise PublishError(f"More than one row per {' and '.join(keys)}; add a series or filter the table first.")
    if chart == "line":
        if df[x].nunique() < 2:
            raise PublishError("A line needs at least 2 periods; use a bar chart for one period.")
        if x == "year" and "partial_year" in df.columns and df["partial_year"].astype(bool).any():
            raise PublishError("A line over years must not end on a partial year, which would look like a fall: "
                               "pass through_week to cut every year to the same week, or leave the partial year out with years.")


def build_publication(stored: dict, chart: str, x: str, y: str, series: str, title: str, note: str, limits: dict, regions: set[str]) -> dict:
    df: pd.DataFrame = stored["rows"]
    if len(df) > limits["max_rows_shown"]:
        raise PublishError(f"{len(df)} rows, at most {limits['max_rows_shown']}: narrow the table first.")
    chart = (chart or "table").strip().lower()
    x, y, series = x.strip(), y.strip(), series.strip()
    check_chart(df, chart, x, y, series, limits, regions)
    spec = None
    if chart != "table":
        spec = {"type": chart, "x": x, "y": y, "series": series or None, "x_time": x in TIME_COLUMNS, "y_time": y in TIME_COLUMNS,
                "series_time": series in TIME_COLUMNS}
    return {"result_id": stored["id"], "title": (title or stored["title"]).strip()[:160], "note": (note or "").strip()[:300],
            "caveats": list(stored.get("caveats", [])), "columns": list(df.columns), "rows": records(df), "row_count": len(df), "chart": spec,
            "source": {"tool": stored["tool"], "args": stored["args"]}}


def default_publication(results: dict, limits: dict, regions: set[str]) -> dict | None:
    """When the model published nothing and made one table, show that table."""
    if len(results) != 1:
        return None
    stored = next(iter(results.values()))
    if len(stored["rows"]) > limits["max_rows_shown"]:
        return None
    return build_publication(stored, "table", "", "", "", "", "", limits, regions)
