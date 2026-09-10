"""
Basic Allowance for Housing: ZIP code -> Military Housing Area -> rate.

BAH is the largest non-taxable component of most members' pay and the single
biggest driver of what they can afford. It varies by MHA (~340 of them), pay
grade, and whether the member has dependents.

DTMO publishes the whole thing as a small ASCII archive that includes the
ZIP-to-MHA crosswalk, so this does not need scraping. `scripts/refresh_bah.py`
downloads and parses it into data/pay/bah_YYYY.json; this module only reads
that file.

THE FAILURE MODE THAT MATTERS: the DTMO rate files ship with no header row, so
the grade order is positional. If the column order is wrong by one, every rate
in the app is silently attributed to the wrong grade -- wrong in a way that
looks completely plausible. So the parser validates the column count against
the expected grade list and refuses to load on a mismatch rather than guessing.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import json

from . import grades as G

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "pay"

# Positional order of rate columns in the DTMO ASCII files: enlisted, then
# warrant, then prior-enlisted officer, then officer.
BAH_COLUMN_ORDER = [
    "E01", "E02", "E03", "E04", "E05", "E06", "E07", "E08", "E09",
    "W01", "W02", "W03", "W04", "W05",
    "O01E", "O02E", "O03E",
    "O01", "O02", "O03", "O04", "O05", "O06", "O07", "O08", "O09", "O10",
]

BAH_SOURCE_URL = ("https://www.travel.dod.mil/Portals/119/Documents/BAH/"
                  "BAH_Rates_All_Locations_All_Pay_Grades/ASCII/BAH-ASCII-{year}.zip")


class BAHFormatError(ValueError):
    """The DTMO file did not have the shape we expect. Never guess past this."""


@dataclass
class BAHData:
    year: int = 0
    zip_to_mha: dict = field(default_factory=dict)
    mha_names: dict = field(default_factory=dict)
    with_dependents: dict = field(default_factory=dict)
    without_dependents: dict = field(default_factory=dict)
    source: str = ""
    retrieved: str = ""

    @property
    def n_zips(self) -> int:
        return len(self.zip_to_mha)

    @property
    def n_mhas(self) -> int:
        return len(self.with_dependents)


@dataclass
class BAHResult:
    found: bool = False
    monthly: float = 0.0
    annual: float = 0.0
    mha: str = ""
    mha_name: str = ""
    year: int = 0
    is_average: bool = False     # a national typical rate, not this member's
    note: str = ""


# --------------------------------------------------------------------------
# Parsing (pure functions, so they can be tested without the real archive)
# --------------------------------------------------------------------------

def parse_zip_mha(text: str) -> dict[str, str]:
    """`sorted_zipmha{YY}.txt` -- whitespace-delimited: ZIP then MHA code."""
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].strip():
            out[parts[0].strip().zfill(5)] = parts[1].strip().upper()
    if not out:
        raise BAHFormatError("ZIP-to-MHA file produced no rows.")
    return out


def parse_mha_names(text: str) -> dict[str, str]:
    """
    `mhanames{YY}.txt` -- MHA code then display name.

    DTMO uses a SEMICOLON here, not a comma, because the names themselves
    contain commas ("AK400;KETCHIKAN, AK"). Splitting on comma first would cut
    the name in half and leave the state as a separate field.
    """
    out = {}
    for line in text.splitlines():
        line = line.rstrip()
        if not line:
            continue
        for sep in (";", "\t", "|"):
            if sep in line:
                code, _, name = line.partition(sep)
                out[code.strip().upper()] = name.strip().strip('"')
                break
        else:
            # No delimiter found: assume "CODE Name of place".
            parts = line.split(None, 1)
            if len(parts) == 2:
                out[parts[0].strip().upper()] = parts[1].strip()
    return out


def parse_rates(text: str, column_order: list[str] | None = None) -> dict[str, dict[str, float]]:
    """
    `bahw{YY}.txt` / `bahwo{YY}.txt` -- CSV, no header: MHA code then one rate
    per pay grade in a fixed positional order.

    Refuses to parse if the column count does not match the expected grade
    list. A silent off-by-one here would misattribute every rate in the app.
    """
    order = column_order or BAH_COLUMN_ORDER
    out: dict[str, dict[str, float]] = {}

    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        mha = parts[0].upper()
        raw = parts[1:]

        if len(raw) != len(order):
            raise BAHFormatError(
                f"Line {lineno} ({mha}) has {len(raw)} rate columns; expected "
                f"{len(order)}. The DTMO column layout has changed. Compare "
                f"against the published XLSX header before trusting any rate -- "
                f"do NOT adjust this blindly, an off-by-one silently shifts "
                f"every rate by one pay grade."
            )

        row = {}
        for code, value in zip(order, raw):
            try:
                row[code] = float(value.replace("$", "").replace(",", ""))
            except ValueError:
                row[code] = 0.0
        out[mha] = row

    if not out:
        raise BAHFormatError("Rate file produced no rows.")
    return out


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def data_path(year: int, data_dir: Path | None = None) -> Path:
    return (data_dir or DATA_DIR) / f"bah_{year}.json"


def available_years(data_dir: Path | None = None) -> list[int]:
    d = data_dir or DATA_DIR
    if not d.exists():
        return []
    years = []
    for f in d.glob("bah_*.json"):
        stem = f.stem.replace("bah_", "")
        if stem.isdigit():
            years.append(int(stem))
    return sorted(years, reverse=True)


def load(year: int | None = None, data_dir: Path | None = None) -> BAHData | None:
    """Load a prepared BAH dataset. Returns None when no data is installed."""
    years = available_years(data_dir)
    if not years:
        return None
    use = year if (year and year in years) else years[0]
    raw = json.loads(data_path(use, data_dir).read_text(encoding="utf-8"))
    return BAHData(
        year=raw.get("year", use),
        zip_to_mha=raw.get("zip_to_mha", {}),
        mha_names=raw.get("mha_names", {}),
        with_dependents=raw.get("with_dependents", {}),
        without_dependents=raw.get("without_dependents", {}),
        source=raw.get("source", ""),
        retrieved=raw.get("retrieved", ""),
    )


def save(data: BAHData, data_dir: Path | None = None) -> Path:
    d = data_dir or DATA_DIR
    d.mkdir(parents=True, exist_ok=True)
    path = data_path(data.year, d)
    path.write_text(json.dumps({
        "year": data.year,
        "source": data.source,
        "retrieved": data.retrieved,
        "zip_to_mha": data.zip_to_mha,
        "mha_names": data.mha_names,
        "with_dependents": data.with_dependents,
        "without_dependents": data.without_dependents,
    }, indent=0), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Lookup
# --------------------------------------------------------------------------

MISSING_DATA_NOTE = (
    "No BAH rate data is installed. Run `python scripts/refresh_bah.py` to "
    "download the current tables from the Defense Travel Management Office, "
    "or enter your BAH from your LES."
)


def lookup(zipcode: str, grade: str, has_dependents: bool,
           data: BAHData | None = None) -> BAHResult:
    """BAH for a ZIP code and pay grade. Always returns a result; check `found`."""
    if data is None:
        return BAHResult(note=MISSING_DATA_NOTE)

    z = "".join(c for c in str(zipcode) if c.isdigit()).zfill(5)[:5]
    if not z or z == "00000":
        return BAHResult(year=data.year, note="Enter a 5-digit ZIP code.")

    mha = data.zip_to_mha.get(z)
    if not mha:
        return BAHResult(
            year=data.year,
            note=f"ZIP {z} is not in the {data.year} BAH tables. Overseas "
                 f"locations use OHA instead of BAH; enter the amount from "
                 f"your LES.")

    try:
        code = G.get(grade).code
    except KeyError:
        return BAHResult(year=data.year, mha=mha, note=f"Unknown pay grade {grade!r}.")

    table = data.with_dependents if has_dependents else data.without_dependents
    rates = table.get(mha)
    if not rates or code not in rates:
        return BAHResult(
            year=data.year, mha=mha,
            mha_name=data.mha_names.get(mha, ""),
            note=f"No {data.year} rate published for {code} in {mha}.")

    monthly = float(rates[code])
    return BAHResult(
        found=True, monthly=monthly, annual=monthly * 12.0, mha=mha,
        mha_name=data.mha_names.get(mha, mha), year=data.year,
    )


def mha_options(data: BAHData | None) -> list[tuple[str, str]]:
    """(code, name) for every MHA, for a manual picker when the ZIP is unknown."""
    if not data:
        return []
    return sorted(((k, data.mha_names.get(k, k)) for k in data.with_dependents),
                  key=lambda t: t[1])


# --------------------------------------------------------------------------
# National average, for when the duty location is not known yet
# --------------------------------------------------------------------------

def average_bah(grade: str, has_dependents: bool, data: BAHData | None = None,
                method: str = "median") -> float:
    """
    A typical BAH rate across all Military Housing Areas for a grade.

    Used when the member does not yet know where they are going. The median is
    the default rather than the mean: a handful of very expensive areas
    (Honolulu, the DC metro, the Bay Area) pull the mean well above what a
    typical assignment pays.
    """
    if data is None:
        return 0.0
    try:
        code = G.get(grade).code
    except KeyError:
        return 0.0

    table = data.with_dependents if has_dependents else data.without_dependents
    values = sorted(float(row[code]) for row in table.values()
                    if code in row and row[code])
    if not values:
        return 0.0
    if method == "mean":
        return sum(values) / len(values)
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2.0


def bah_range(grade: str, has_dependents: bool,
              data: BAHData | None = None) -> tuple[float, float]:
    """Lowest and highest published rate for a grade, for context on an average."""
    if data is None:
        return (0.0, 0.0)
    try:
        code = G.get(grade).code
    except KeyError:
        return (0.0, 0.0)
    table = data.with_dependents if has_dependents else data.without_dependents
    values = [float(row[code]) for row in table.values() if code in row and row[code]]
    return (min(values), max(values)) if values else (0.0, 0.0)


def lookup_or_average(zipcode: str, grade: str, has_dependents: bool,
                      data: BAHData | None = None) -> BAHResult:
    """
    BAH for a known location, falling back to the national median when the
    location is not known yet.

    A member who has not received orders still needs a number to plan with, and
    a typical rate is far more useful than a zero. The result is flagged so the
    UI can say plainly that it is an estimate.
    """
    exact = lookup(zipcode, grade, has_dependents, data)
    if exact.found or data is None:
        return exact

    avg = average_bah(grade, has_dependents, data)
    if avg <= 0:
        return exact

    lo, hi = bah_range(grade, has_dependents, data)
    return BAHResult(
        found=True, monthly=avg, annual=avg * 12.0, year=data.year,
        is_average=True, mha_name="National median",
        note=(f"Using the national median for {G.get(grade).label}, since the "
              f"duty location is not set. Published rates for this grade run "
              f"from ${lo:,.0f} to ${hi:,.0f} a month, so treat this as a "
              f"placeholder and replace it once you have orders."),
    )


# --------------------------------------------------------------------------
# What BAH is actually worth
# --------------------------------------------------------------------------

# Housing and utilities are assumed to cost slightly MORE than BAH.
#
# This is not pessimism, it is policy. Since 2015 BAH has been deliberately set
# below full local housing cost, with members absorbing an out-of-pocket share
# of roughly 5%. So the typical member pays about 105% of their allowance to be
# housed, and the allowance is a housing offset rather than income.
#
# Treating BAH as free cash flow is the single most common way a military
# budget projection goes wrong: it banks the allowance as savings and forgets
# the rent it exists to pay.
DEFAULT_HOUSING_COST_SHARE = 1.05


@dataclass
class HousingPosition:
    bah_monthly: float = 0.0
    housing_cost_monthly: float = 0.0
    surplus_monthly: float = 0.0
    surplus_annual: float = 0.0
    share_consumed: float = 0.0
    note: str = ""


def housing_position(bah_monthly: float, housing_cost_monthly: float = 0.0,
                     assumed_share: float = DEFAULT_HOUSING_COST_SHARE) -> HousingPosition:
    """
    What is actually left over from BAH after housing.

    Pass the member's real rent or PITI plus utilities when known. Otherwise a
    default share is assumed, because BAH is set to cover median local cost --
    it is not a moneymaker, and a model that banks it as savings will overstate
    what the household can put away.
    """
    cost = housing_cost_monthly if housing_cost_monthly > 0 else bah_monthly * assumed_share
    surplus = bah_monthly - cost
    share = (cost / bah_monthly) if bah_monthly else 0.0

    estimated = housing_cost_monthly <= 0

    if bah_monthly <= 0:
        note = "No housing allowance."
    elif surplus > 200:
        note = (f"You keep about ${surplus:,.0f} a month of your allowance. That "
                f"is real, tax-free surplus, and unusual — most members pay more "
                f"than their BAH to be housed. It also disappears the moment you "
                f"move somewhere more expensive, so do not build a fixed "
                f"commitment on it.")
    elif surplus < -50:
        if estimated:
            note = (f"Assuming housing and utilities run "
                    f"{assumed_share * 100:.0f}% of BAH, you pay about "
                    f"${-surplus:,.0f} a month out of taxable pay to be housed. "
                    f"BAH has been set below full local housing cost since 2015 — "
                    f"the out-of-pocket share is deliberate policy, not a "
                    f"budgeting failure. Enter your actual rent or PITI plus "
                    f"utilities to replace this estimate.")
        else:
            note = (f"You pay about ${-surplus:,.0f} a month above your allowance "
                    f"out of taxable pay. That is a genuine budget line, not a "
                    f"rounding error.")
    else:
        note = ("Your housing costs consume essentially all of your allowance, "
                "which is what BAH is designed to do. Treat it as covering "
                "housing rather than as income you can save.")

    return HousingPosition(bah_monthly=bah_monthly, housing_cost_monthly=cost,
                           surplus_monthly=surplus, surplus_annual=surplus * 12.0,
                           share_consumed=share, note=note)
