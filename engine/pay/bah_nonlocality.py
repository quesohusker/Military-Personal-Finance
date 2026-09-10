"""
Non-locality BAH: Partial, RC/Transit, and Differential.

Locality BAH covers a member assigned to a duty station. These three cover the
cases it does not, and each is a real situation the app has to answer for:

  * BAH-Partial -- a member WITHOUT dependents who is living in government
    quarters. Tiny (single-digit to low-double-digit dollars a month) but it is
    what a barracks-dwelling junior enlisted member actually receives, and
    showing them a locality rate they do not get would be badly wrong.

  * BAH RC/T (Reserve Component / Transit) -- Guard and Reserve members on
    active orders of 30 days or less, and members in a transit status between
    permanent duty stations. A single nationwide rate, not location-based.

  * BAH-DIFF -- a member without dependents living in single-type government
    quarters who pays child support. Paid in addition to nothing else; it
    exists purely to recognise the support obligation.

Rates effective 1 January 2026, from the DTMO non-locality table.

The three move differently, which matters for projections:
  - RC/T is adjusted by the average change in housing costs
  - BAH-DIFF is adjusted by the basic pay raise
  - BAH-Partial is CONSTANT -- it has not changed in decades and should not be
    inflated in a forward projection
"""

from __future__ import annotations
from dataclasses import dataclass

from . import grades as G

NONLOCALITY_YEAR = 2026
NONLOCALITY_EFFECTIVE = "1 January 2026"
NONLOCALITY_SOURCE = "DTMO 2026 Non-Locality BAH Rates"

# grade code -> (partial, rc_t_without_dependents, rc_t_with_dependents, differential)
NONLOCALITY_RATES: dict[str, tuple[float, float, float, float]] = {
    "O10":  (50.70, 2466.30, 3035.10, 465.60),
    "O09":  (50.70, 2466.30, 3035.10, 465.60),
    "O08":  (50.70, 2466.30, 3035.10, 465.60),
    "O07":  (50.70, 2466.30, 3035.10, 465.60),
    "O06":  (39.60, 2261.70, 2731.80, 395.70),
    "O05":  (33.00, 2178.00, 2633.40, 382.50),
    "O04":  (26.70, 2017.80, 2320.80, 255.00),
    "O03":  (22.20, 1618.20, 1920.30, 254.70),
    "O02":  (17.70, 1281.90, 1638.30, 300.60),
    "O01":  (13.20, 1100.70, 1466.70, 324.60),
    "O03E": (22.20, 1746.60, 2063.70, 266.10),
    "O02E": (17.70, 1485.30, 1862.40, 318.60),
    "O01E": (13.20, 1291.80, 1721.40, 374.10),
    "W05":  (25.20, 2051.40, 2241.30, 159.00),
    "W04":  (25.20, 1821.30, 2054.70, 196.20),
    "W03":  (20.70, 1531.20, 1883.40, 295.50),
    "W02":  (15.90, 1359.00, 1730.70, 312.30),
    "W01":  (13.80, 1139.40, 1497.90, 302.70),
    "E09":  (18.60, 1494.90, 1971.60, 399.30),
    "E08":  (15.30, 1374.30, 1818.30, 374.40),
    "E07":  (12.00, 1265.70, 1687.20, 433.20),
    "E06":  ( 9.90, 1169.70, 1559.10, 419.10),
    "E05":  ( 8.70, 1052.70, 1403.70, 380.10),
    "E04":  ( 8.10,  915.60, 1219.50, 338.70),
    "E03":  ( 7.80,  850.50, 1133.70, 277.80),
    "E02":  ( 7.20,  811.50, 1080.60, 371.10),
    "E01":  ( 6.90,  811.50, 1080.60, 439.20),
}

PARTIAL = "BAH-Partial"
RC_TRANSIT = "BAH RC/Transit"
DIFFERENTIAL = "BAH-DIFF"


@dataclass
class NonLocalityResult:
    found: bool = False
    kind: str = ""
    monthly: float = 0.0
    annual: float = 0.0
    year: int = NONLOCALITY_YEAR
    note: str = ""


def _row(grade: str) -> tuple[float, float, float, float] | None:
    try:
        return NONLOCALITY_RATES.get(G.get(grade).code)
    except KeyError:
        return None


def partial(grade: str) -> NonLocalityResult:
    """For a member WITHOUT dependents assigned to government quarters."""
    row = _row(grade)
    if not row:
        return NonLocalityResult(note=f"Unknown pay grade {grade!r}.")
    return NonLocalityResult(
        found=True, kind=PARTIAL, monthly=row[0], annual=row[0] * 12.0,
        note="Paid to a member without dependents living in government quarters. "
             "This rate is fixed and does not rise with inflation.")


def rc_transit(grade: str, has_dependents: bool) -> NonLocalityResult:
    """
    For Guard/Reserve members on active orders of 30 days or less, and for
    members in a transit status. One nationwide rate -- not location-based.
    """
    row = _row(grade)
    if not row:
        return NonLocalityResult(note=f"Unknown pay grade {grade!r}.")
    amount = row[2] if has_dependents else row[1]
    return NonLocalityResult(
        found=True, kind=RC_TRANSIT, monthly=amount, annual=amount * 12.0,
        note="A single nationwide rate for Reserve Component members on orders "
             "of 30 days or less, and for members in transit between permanent "
             "duty stations. Orders of more than 30 days pay locality BAH "
             "instead, which is usually much higher.")


def differential(grade: str) -> NonLocalityResult:
    """
    For a member without dependents in single-type government quarters who pays
    child support.
    """
    row = _row(grade)
    if not row:
        return NonLocalityResult(note=f"Unknown pay grade {grade!r}.")
    return NonLocalityResult(
        found=True, kind=DIFFERENTIAL, monthly=row[3], annual=row[3] * 12.0,
        note="Paid to a member without dependents in single-type government "
             "quarters who pays child support. It does not require the child to "
             "live with you, and it is separate from the support obligation "
             "itself.")


def all_rates(grade: str) -> dict:
    """Every non-locality rate for one grade, for display side by side."""
    return {
        PARTIAL: partial(grade),
        f"{RC_TRANSIT} (without dependents)": rc_transit(grade, False),
        f"{RC_TRANSIT} (with dependents)": rc_transit(grade, True),
        DIFFERENTIAL: differential(grade),
    }
