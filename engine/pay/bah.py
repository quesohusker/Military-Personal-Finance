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
    """`mhanames{YY}.txt` -- MHA code then display name, comma or tab separated."""
    out = {}
    for line in text.splitlines():
        line = line.rstrip()
        if not line:
            continue
        for sep in ("\t", ","):
            if sep in line:
                code, _, name = line.partition(sep)
                out[code.strip().upper()] = name.strip().strip('"')
                break
        else:
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
