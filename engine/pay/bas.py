"""
Basic Allowance for Subsistence.

Two numbers a year, but two numbers people get wrong in projections: BAS is
indexed to the USDA food cost index, NOT to the annual military pay raise. In
2026 the pay raise was 3.8% while BAS rose 2.4%. Deriving one from the other
silently overstates compensation.

BAS is non-taxable.
"""

from __future__ import annotations
from dataclasses import dataclass

# Monthly rates. Update annually, effective 1 January.
BAS_RATES = {
    # CHECKED 2026-09-10 against dfas.mil BAS pay table (browser save).
    # Exact, and it settles the direction for good: ENLISTED BAS is the
    # larger of the two. The brief for this project had them the other
    # way round, and the repo was right to be followed over it.
    2026: {"enlisted": 476.95, "officer": 328.48, "bas_ii": 953.90},
    2025: {"enlisted": 465.77, "officer": 320.78, "bas_ii": 931.54},
}

BAS_SOURCE = ("DFAS BAS rate table. Indexed to the USDA food cost index, "
              "effective 1 January.")


@dataclass
class BASResult:
    monthly: float
    annual: float
    year: int
    is_estimate: bool
    note: str = ""


def bas_monthly(is_officer_grade: bool, year: int = 2026,
                bas_ii: bool = False) -> BASResult:
    """
    BAS for one member. `bas_ii` is the higher enlisted rate paid when a member
    is required to eat in a dining facility that cannot support them; it does
    not apply to officers.
    """
    known = sorted(BAS_RATES)
    estimate = year not in BAS_RATES
    use = year if not estimate else (known[-1] if year > known[-1] else known[0])
    rates = BAS_RATES[use]

    if is_officer_grade:
        amount = rates["officer"]
    elif bas_ii:
        amount = rates["bas_ii"]
    else:
        amount = rates["enlisted"]

    note = ""
    if estimate:
        note = (f"No published BAS rate for {year}; using the {use} rate. "
                f"Run the pay data refresh to update.")

    return BASResult(monthly=amount, annual=amount * 12.0, year=use,
                     is_estimate=estimate, note=note)


def latest_year() -> int:
    return max(BAS_RATES)
