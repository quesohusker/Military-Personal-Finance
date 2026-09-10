"""
Basic pay: the grade x years-of-service table.

Basic pay is the spine of military compensation. It is the only component that
counts toward retired pay, SBP, the BRS TSP match, severance and leave
sell-back -- so an error here propagates into every projection the app makes.
For that reason this module ships NO guessed table. It reads a data file
installed from the published DFAS table, and until one is installed it says so
and defers to the member's LES, which is authoritative anyway.

Two properties of the table that projections get wrong:

  * Pay rises in STEPS at longevity boundaries (2, 3, 4, 6, 8, 10, 12, 14, 16,
    18, 20, 22, 24, 26...), not smoothly. Modelling it as a growth rate
    misplaces every raise.
  * Each grade stops gaining longevity raises at some point -- an O-5 is flat
    from "over 22" onward, an E-5 from "over 12". A member at the top of their
    grade gets nothing but the annual across-the-board raise.
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json

from . import grades as G

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "pay"

MISSING_DATA_NOTE = (
    "No basic pay table is installed. Enter your basic pay from your LES, or "
    "install the table with `python scripts/import_basepay.py`. Your LES is the "
    "authoritative figure in any case."
)


@dataclass
class BasePayTable:
    year: int = 0
    rates: dict = None          # grade code -> {yos column (str): monthly}
    source: str = ""
    retrieved: str = ""
    raise_pct: float = 0.0      # the across-the-board raise that produced it

    def __post_init__(self):
        if self.rates is None:
            self.rates = {}

    @property
    def n_grades(self) -> int:
        return len(self.rates)


@dataclass
class BasePayResult:
    found: bool = False
    monthly: float = 0.0
    annual: float = 0.0
    grade: str = ""
    yos_column: int = 0
    year: int = 0
    at_top_of_grade: bool = False
    next_raise_at_years: float = 0.0
    note: str = ""


def data_path(year: int, data_dir: Path | None = None) -> Path:
    return (data_dir or DATA_DIR) / f"basepay_{year}.json"


def available_years(data_dir: Path | None = None) -> list[int]:
    d = data_dir or DATA_DIR
    if not d.exists():
        return []
    out = []
    for f in d.glob("basepay_*.json"):
        stem = f.stem.replace("basepay_", "")
        if stem.isdigit():
            out.append(int(stem))
    return sorted(out, reverse=True)


def load(year: int | None = None, data_dir: Path | None = None) -> BasePayTable | None:
    years = available_years(data_dir)
    if not years:
        return None
    use = year if (year and year in years) else years[0]
    raw = json.loads(data_path(use, data_dir).read_text(encoding="utf-8"))
    return BasePayTable(year=raw.get("year", use), rates=raw.get("rates", {}),
                        source=raw.get("source", ""),
                        retrieved=raw.get("retrieved", ""),
                        raise_pct=raw.get("raise_pct", 0.0))


def save(table: BasePayTable, data_dir: Path | None = None) -> Path:
    d = data_dir or DATA_DIR
    d.mkdir(parents=True, exist_ok=True)
    path = data_path(table.year, d)
    path.write_text(json.dumps({
        "year": table.year, "source": table.source,
        "retrieved": table.retrieved, "raise_pct": table.raise_pct,
        "rates": table.rates,
    }, indent=0), encoding="utf-8")
    return path


def lookup(grade: str, years_of_service: float, table: BasePayTable | None = None,
           override_monthly: float = 0.0) -> BasePayResult:
    """
    Monthly basic pay. `override_monthly` short-circuits everything -- the LES
    figure always wins over the table.
    """
    try:
        code = G.get(grade).code
        label = G.get(grade).label
    except KeyError:
        return BasePayResult(note=f"Unknown pay grade {grade!r}.")

    col = G.yos_column(years_of_service)

    if override_monthly > 0:
        return BasePayResult(found=True, monthly=override_monthly,
                             annual=override_monthly * 12.0, grade=label,
                             yos_column=col, note="From your LES.")

    if table is None:
        return BasePayResult(grade=label, yos_column=col, note=MISSING_DATA_NOTE)

    row = table.rates.get(code)
    if not row:
        return BasePayResult(grade=label, yos_column=col, year=table.year,
                             note=f"No {table.year} basic pay published for {label}.")

    # Walk down to the highest published column at or below this longevity.
    amount = 0.0
    used = 0
    for boundary in G.YOS_COLUMNS:
        if boundary > col:
            break
        v = row.get(str(boundary))
        if v:
            amount = float(v)
            used = boundary
    if amount <= 0:
        return BasePayResult(grade=label, yos_column=col, year=table.year,
                             note=f"No rate published for {label} at {col} years.")

    # Is there another longevity raise ahead in this grade?
    next_at = 0.0
    top = True
    for boundary in G.YOS_COLUMNS:
        if boundary <= used:
            continue
        v = row.get(str(boundary))
        if v and float(v) > amount + 0.005:
            next_at, top = float(boundary), False
            break

    note = ""
    if top:
        note = (f"{label} is at the top of its basic pay scale. Longevity raises "
                f"have stopped -- only the annual across-the-board raise and a "
                f"promotion increase basic pay from here.")

    return BasePayResult(found=True, monthly=amount, annual=amount * 12.0,
                         grade=label, yos_column=used, year=table.year,
                         at_top_of_grade=top, next_raise_at_years=next_at,
                         note=note)


def apply_raise(table: BasePayTable, pct: float, new_year: int) -> BasePayTable:
    """
    Roll a table forward by an across-the-board raise.

    Useful for projections, and for a first cut at next year's table -- but
    NOT a substitute for the published one. Targeted raises break uniformity:
    the 2025 raise gave junior enlisted grades substantially more than
    everyone else, and a uniform multiply would have understated them badly.
    Always diff against the published table.
    """
    scaled = {code: {k: round(float(v) * (1.0 + pct), 2) for k, v in row.items()}
              for code, row in table.rates.items()}
    return BasePayTable(year=new_year, rates=scaled, raise_pct=pct,
                        source=f"{table.source} rolled forward by {pct * 100:.1f}%",
                        retrieved=table.retrieved)


def sanity_check(table: BasePayTable) -> list[str]:
    """Shape checks that catch a misparsed or mistyped table."""
    problems = []
    if table.n_grades < 20:
        problems.append(f"Only {table.n_grades} grades; expected 27.")

    for code, row in table.rates.items():
        vals = [float(v) for k, v in sorted(row.items(), key=lambda kv: int(kv[0])) if v]
        if not vals:
            problems.append(f"{code} has no rates.")
            continue
        if any(b < a - 0.005 for a, b in zip(vals, vals[1:])):
            problems.append(f"{code} basic pay decreases with longevity.")
        if min(vals) < 1_000 or max(vals) > 30_000:
            problems.append(f"{code} rates span ${min(vals):,.0f}-${max(vals):,.0f}, "
                            f"outside the plausible range.")

    # An E-1 must not out-earn an O-1; a shifted table shows up here.
    e1 = table.rates.get("E01", {})
    o1 = table.rates.get("O01", {})
    if e1 and o1:
        a = float(e1.get("0", 0) or 0)
        b = float(o1.get("0", 0) or 0)
        if a and b and a > b:
            problems.append("E-1 out-earns O-1 at entry; the table looks shifted.")

    return problems


# --------------------------------------------------------------------------
# Drill pay
# --------------------------------------------------------------------------

DRILLS_PER_WEEKEND = 4
DRILL_DIVISOR = 30      # a drill period is 1/30 of monthly basic pay


@dataclass
class DrillPayResult:
    found: bool = False
    per_drill: float = 0.0
    per_weekend: float = 0.0
    annual_48_drills: float = 0.0
    monthly_basic_pay: float = 0.0
    grade: str = ""
    note: str = ""


def drill_pay(grade: str, years_of_service: float,
              table: BasePayTable | None = None,
              override_monthly: float = 0.0,
              drills_per_year: int = 48) -> DrillPayResult:
    """
    Guard and Reserve drill pay.

    There is no separate drill pay table -- DFAS publishes one, but every figure
    in it is derived: a drill period pays 1/30 of monthly basic pay, and a
    standard drill weekend is four periods. Confirmed against the published
    table: an E-1 under four months at $2,225.70 a month gives $74.19 a drill
    and $296.76 a weekend, exactly as printed.

    `drills_per_year` defaults to 48 -- twelve weekends. Annual training is paid
    separately as active duty and is not included here.
    """
    base = lookup(grade, years_of_service, table, override_monthly)
    if not base.found:
        return DrillPayResult(grade=base.grade, note=base.note)

    per_drill = base.monthly / DRILL_DIVISOR
    return DrillPayResult(
        found=True, per_drill=per_drill,
        per_weekend=per_drill * DRILLS_PER_WEEKEND,
        annual_48_drills=per_drill * drills_per_year,
        monthly_basic_pay=base.monthly, grade=base.grade,
        note=("A drill period pays one thirtieth of monthly basic pay; a drill "
              "weekend is four periods. Drill pay carries no BAH or BAS — those "
              "are paid only on active orders, and BAH only on orders of more "
              "than 30 days. Annual training is paid separately as active duty."),
    )
