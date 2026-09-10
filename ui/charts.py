"""
Altair chart helpers.

One visual language across the app: two futures are always the same two colours
(blue = convert nothing, orange = with conversions), thin marks, recessive
axes, and a crosshair tooltip on every time series. Colours come from a
validated categorical palette; the app commits to a light surface.
"""

from __future__ import annotations
import altair as alt
import pandas as pd

# Validated categorical slots (light surface #fcfcfb)
BLUE = "#2a78d6"     # slot 1 -- No conversions
ORANGE = "#eb6834"   # slot 2 -- With conversions
AQUA = "#1baf7a"     # slot 3
YELLOW = "#eda100"   # slot 4
MAGENTA = "#e87ba4"  # slot 5
VIOLET = "#4a3aa7"   # slot 7
RED = "#e34948"      # status: serious

TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e6e5e1"

NO_CONVERT = "No conversions"
WITH_CONVERT = "With conversions"

PAIR_DOMAIN = [NO_CONVERT, WITH_CONVERT]
PAIR_RANGE = [BLUE, ORANGE]

_BASE_HEIGHT = 320


def _axis(fmt=None, title=None, grid=True):
    # Altair 6 rejects None for these; omit them with Undefined instead.
    return alt.Axis(
        format=alt.Undefined if fmt is None else fmt,
        title=alt.Undefined if title is None else title,
        grid=grid, gridColor=GRID, gridWidth=1,
        domainColor=GRID, tickColor=GRID, labelColor=TEXT_SECONDARY,
        titleColor=TEXT_SECONDARY, labelFontSize=11, titleFontSize=11,
        titleFontWeight="normal",
    )


def _legend(title=None):
    # Vega-Lite reads a null legend title as "no title". Unlike Axis.format,
    # None is valid here -- passing Undefined would fall back to the field name.
    return alt.Legend(
        title=title, orient="top", direction="horizontal", labelColor=TEXT_PRIMARY,
        titleColor=TEXT_SECONDARY, labelFontSize=12, symbolStrokeWidth=3,
        symbolType="stroke", offset=4,
    )


def compare_lines(df: pd.DataFrame, y: str, y_title: str, *,
                  y_format: str = "$,.0f", y_axis_format: str = "$.3~s",
                  height: int = _BASE_HEIGHT):
    """
    Two futures on one axis, with a crosshair and a shared tooltip.

    `df` must have columns: year, scenario, and whatever `y` names.
    """
    hover = alt.selection_point(
        fields=["year"], nearest=True, on="pointermove", empty=False, clear="pointerout",
    )

    color = alt.Color("scenario:N",
                      scale=alt.Scale(domain=PAIR_DOMAIN, range=PAIR_RANGE),
                      legend=_legend())

    base = alt.Chart(df)

    lines = base.mark_line(strokeWidth=2, interpolate="monotone").encode(
        x=alt.X("year:Q", axis=_axis("d", "Year"), scale=alt.Scale(nice=False, zero=False)),
        y=alt.Y(f"{y}:Q", axis=_axis(y_axis_format, y_title)),
        color=color,
    )

    rule = base.mark_rule(color=TEXT_SECONDARY, strokeWidth=1).encode(
        x="year:Q",
        opacity=alt.condition(hover, alt.value(0.45), alt.value(0)),
        tooltip=[
            alt.Tooltip("year:Q", title="Year", format="d"),
            alt.Tooltip("scenario:N", title="Scenario"),
            alt.Tooltip(f"{y}:Q", title=y_title, format=y_format),
        ],
    ).add_params(hover)

    points = base.mark_point(size=60, filled=True, stroke="#fcfcfb",
                             strokeWidth=2).encode(
        x="year:Q", y=f"{y}:Q", color=color,
        opacity=alt.condition(hover, alt.value(1), alt.value(0)),
    )

    return (lines + rule + points).properties(height=height).configure_view(
        strokeWidth=0).configure_axis(labelFlush=False)


def stacked_income(df: pd.DataFrame, height: int = 360):
    """
    Income sources over time, stacked. A 2px surface gap separates segments.
    `df` needs columns: year, source, amount.
    """
    order = ["Military retired pay", "SBP annuity", "Wages", "Social Security",
             "Other pension", "RMD", "Tax-free (VA / DIC)"]
    palette = [BLUE, VIOLET, ORANGE, AQUA, MAGENTA, RED, YELLOW]

    present = [s for s in order if s in set(df["source"])]
    colors = [palette[order.index(s)] for s in present]

    return alt.Chart(df).mark_area(
        interpolate="monotone", stroke="#fcfcfb", strokeWidth=2,
    ).encode(
        x=alt.X("year:Q", axis=_axis("d", "Year"),
                scale=alt.Scale(nice=False, zero=False)),
        y=alt.Y("amount:Q", stack="zero", axis=_axis("$.3~s", "Income (2026 dollars)")),
        color=alt.Color("source:N",
                        scale=alt.Scale(domain=present, range=colors),
                        legend=_legend()),
        order=alt.Order("order:Q"),
        tooltip=[
            alt.Tooltip("year:Q", title="Year", format="d"),
            alt.Tooltip("source:N", title="Source"),
            alt.Tooltip("amount:Q", title="Amount", format="$,.0f"),
        ],
    ).properties(height=height).configure_view(strokeWidth=0)


def grouped_bars(df: pd.DataFrame, x: str, y: str, x_title: str, y_title: str,
                 height: int = 300):
    """Two futures as grouped bars. 4px rounded data-ends, 2px gap."""
    return alt.Chart(df).mark_bar(
        cornerRadiusTopLeft=4, cornerRadiusTopRight=4, stroke="#fcfcfb",
        strokeWidth=2,
    ).encode(
        x=alt.X(f"{x}:N", axis=_axis(None, x_title, grid=False),
                sort=None),
        xOffset=alt.XOffset("scenario:N", sort=PAIR_DOMAIN),
        y=alt.Y(f"{y}:Q", axis=_axis("$.3~s", y_title)),
        color=alt.Color("scenario:N",
                        scale=alt.Scale(domain=PAIR_DOMAIN, range=PAIR_RANGE),
                        legend=_legend()),
        tooltip=[
            alt.Tooltip(f"{x}:N", title=x_title),
            alt.Tooltip("scenario:N", title="Scenario"),
            alt.Tooltip(f"{y}:Q", title=y_title, format="$,.0f"),
        ],
    ).properties(height=height).configure_view(strokeWidth=0)


def histogram_delta(values, title: str, x_title: str, favourable_above: float = 0.0,
                    height: int = 300):
    """
    Distribution of a paired difference, split at zero so the reader can see
    the win rate directly. Green above the line, red below.
    """
    df = pd.DataFrame({"value": values})
    df["side"] = df["value"].apply(
        lambda v: "Converting wins" if v > favourable_above else "Converting loses")

    return alt.Chart(df).mark_bar(
        cornerRadiusTopLeft=4, cornerRadiusTopRight=4, stroke="#fcfcfb",
        strokeWidth=1,
    ).encode(
        x=alt.X("value:Q", bin=alt.Bin(maxbins=45),
                axis=_axis("$.3~s", x_title)),
        y=alt.Y("count():Q", axis=_axis("d", "Paths")),
        color=alt.Color("side:N",
                        scale=alt.Scale(domain=["Converting wins", "Converting loses"],
                                        range=[AQUA, RED]),
                        legend=_legend()),
        tooltip=[alt.Tooltip("count():Q", title="Paths"),
                 alt.Tooltip("value:Q", title=x_title, format="$,.0f", bin=True)],
    ).properties(height=height, title=title).configure_view(strokeWidth=0)


def marginal_rate_chart(df: pd.DataFrame, height: int = 320):
    """Marginal rate over time -- the chart that shows the conversion window."""
    hover = alt.selection_point(fields=["year"], nearest=True, on="pointermove",
                                empty=False, clear="pointerout")
    color = alt.Color("scenario:N",
                      scale=alt.Scale(domain=PAIR_DOMAIN, range=PAIR_RANGE),
                      legend=_legend())
    base = alt.Chart(df)

    lines = base.mark_line(strokeWidth=2, interpolate="step-after").encode(
        x=alt.X("year:Q", axis=_axis("d", "Year"),
                scale=alt.Scale(nice=False, zero=False)),
        y=alt.Y("marginal_rate:Q", axis=_axis(".0%", "Marginal federal rate"),
                scale=alt.Scale(domain=[0, 0.45])),
        color=color,
    )
    rule = base.mark_rule(color=TEXT_SECONDARY, strokeWidth=1).encode(
        x="year:Q",
        opacity=alt.condition(hover, alt.value(0.45), alt.value(0)),
        tooltip=[
            alt.Tooltip("year:Q", title="Year", format="d"),
            alt.Tooltip("age:Q", title="Your age", format="d"),
            alt.Tooltip("scenario:N", title="Scenario"),
            alt.Tooltip("marginal_rate:Q", title="Marginal rate", format=".0%"),
            alt.Tooltip("filing_status:N", title="Filing"),
        ],
    ).add_params(hover)

    return (lines + rule).properties(height=height).configure_view(strokeWidth=0)


def two_future_frame(base_rows, conv_rows, field: str) -> pd.DataFrame:
    """Tidy frame with one row per (year, scenario) for a single field."""
    recs = []
    for label, rows in ((NO_CONVERT, base_rows), (WITH_CONVERT, conv_rows)):
        for r in rows:
            recs.append({
                "year": r.year,
                "age": r.age_primary,
                "scenario": label,
                "filing_status": r.filing_status,
                field: getattr(r, field),
            })
    return pd.DataFrame(recs)


def cumulative_frame(base_rows, conv_rows, field: str, out: str) -> pd.DataFrame:
    recs = []
    for label, rows in ((NO_CONVERT, base_rows), (WITH_CONVERT, conv_rows)):
        total = 0.0
        for r in rows:
            total += getattr(r, field)
            recs.append({"year": r.year, "age": r.age_primary,
                         "scenario": label, "filing_status": r.filing_status,
                         out: total})
    return pd.DataFrame(recs)
