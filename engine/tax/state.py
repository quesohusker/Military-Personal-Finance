"""
State income tax treatment, focused on the four things that actually move a
military retiree's Roth conversion decision:

  1. Is military retired pay exempt from state tax?
  2. Is Social Security taxed?
  3. Is there a retirement-income exclusion that a Roth conversion can use?
  4. What is the marginal rate on the conversion itself?

This is a simplification. Graduated-rate states are represented by a single
effective rate, credits are approximated as exemptions, and local income taxes
are ignored. The app lets the user override every state's rate and exemption
directly, and shows the override prominently, because state law changes faster
than any table ships.

Verify against your own state's current instructions before acting.
"""

from __future__ import annotations
from dataclasses import dataclass, asdict


@dataclass
class StateRule:
    name: str
    rate: float                       # effective marginal rate on ordinary income
    military_pension_exempt: float    # 0.0 = fully taxed, 1.0 = fully exempt
    taxes_social_security: bool
    retirement_exclusion: float       # per person, applies to IRA/TSP income
    retirement_exclusion_age: int     # age at which the exclusion becomes available
    conversion_uses_exclusion: bool   # can a Roth conversion absorb the exclusion?
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _s(name, rate, mil=1.0, ss=False, excl=0.0, excl_age=0,
       conv_excl=False, note=""):
    return StateRule(name, rate, mil, ss, excl, excl_age, conv_excl, note)


# --------------------------------------------------------------------------
# The table. Rates are 2026 effective marginal rates at a retiree's typical
# income level, not necessarily the statutory top rate.
# --------------------------------------------------------------------------
STATE_RULES: dict[str, StateRule] = {
    "Alabama":      _s("Alabama", 0.050, 1.0, False, 6_000, 65, True,
                       "Military retirement fully exempt."),
    "Alaska":       _s("Alaska", 0.0, 1.0, False, note="No state income tax."),
    "Arizona":      _s("Arizona", 0.025, 1.0, False,
                       note="Flat 2.5%. Military retirement fully exempt."),
    "Arkansas":     _s("Arkansas", 0.039, 1.0, False, 6_000, 59, True,
                       "Military retirement fully exempt."),
    "California":   _s("California", 0.093, 0.0, False,
                       note="TAXES military retired pay in full. High marginal "
                            "rates make in-state conversions expensive."),
    "Colorado":     _s("Colorado", 0.044, 0.0, True, 24_000, 65, True,
                       "Age-based cap covers military pay and IRA income together."),
    "Connecticut":  _s("Connecticut", 0.050, 1.0, False, 0, 0, False,
                       "Military retirement fully exempt."),
    "Delaware":     _s("Delaware", 0.066, 0.0, False, 12_500, 60, True,
                       "Pension exclusion applies to military and IRA income."),
    "District of Columbia": _s("District of Columbia", 0.085, 0.0, False,
                               note="Taxes military retired pay."),
    "Florida":      _s("Florida", 0.0, 1.0, False, note="No state income tax."),
    "Georgia":      _s("Georgia", 0.0519, 1.0, False, 65_000, 65, True,
                       "Flat tax. Retirement exclusion is large at 65+."),
    "Hawaii":       _s("Hawaii", 0.079, 1.0, False, 0, 0, False,
                       "Military retirement fully exempt; IRA income taxed."),
    "Idaho":        _s("Idaho", 0.053, 1.0, False, 0, 65, False,
                       "Military retirement deduction at 65+ (or 62 if disabled)."),
    "Illinois":     _s("Illinois", 0.0495, 1.0, False, 0, 0, True,
                       "Illinois exempts nearly all retirement income, including "
                            "IRA distributions and conversions."),
    "Indiana":      _s("Indiana", 0.029, 1.0, False,
                       note="Military retirement fully exempt."),
    "Iowa":         _s("Iowa", 0.038, 1.0, False, 0, 55, True,
                       "Retirement income exempt at 55+."),
    "Kansas":       _s("Kansas", 0.0558, 1.0, False,
                       note="Military retirement fully exempt."),
    "Kentucky":     _s("Kentucky", 0.035, 1.0, False, 31_110, 0, True,
                       "Exclusion applies across retirement income types."),
    "Louisiana":    _s("Louisiana", 0.030, 1.0, False, 6_000, 65, True,
                       "Military retirement fully exempt."),
    "Maine":        _s("Maine", 0.0715, 1.0, False, 30_000, 0, True,
                       "Military pension fully exempt."),
    "Maryland":     _s("Maryland", 0.0475, 1.0, False, 39_500, 65, True,
                       "Military retirement subtraction; local piggyback tax "
                            "not modeled."),
    "Massachusetts": _s("Massachusetts", 0.050, 1.0, False,
                        note="Military retirement fully exempt."),
    "Michigan":     _s("Michigan", 0.0425, 1.0, False, 68_000, 67, True,
                       "Military retirement fully exempt at any age. The phased-in "
                            "retirement deduction covers IRA and TSP income (and a "
                            "conversion) but is age-gated -- verify your own tier "
                            "and override the age on the Household page if it differs."),
    "Minnesota":    _s("Minnesota", 0.0785, 1.0, True, 0, 0, False,
                       "Military pension subtraction or credit."),
    "Mississippi":  _s("Mississippi", 0.044, 1.0, False, 0, 59, True,
                       "Retirement income exempt at 59.5+."),
    "Missouri":     _s("Missouri", 0.047, 1.0, False, 0, 0, False,
                       "Military retirement fully exempt."),
    "Montana":      _s("Montana", 0.059, 0.5, True, 0, 0, False,
                       "Partial military retirement exemption with conditions."),
    "Nebraska":     _s("Nebraska", 0.0520, 1.0, False,
                       note="Military retirement fully exempt."),
    "Nevada":       _s("Nevada", 0.0, 1.0, False, note="No state income tax."),
    "New Hampshire": _s("New Hampshire", 0.0, 1.0, False,
                        note="No tax on earned or retirement income."),
    "New Jersey":   _s("New Jersey", 0.0637, 1.0, False, 100_000, 62, True,
                       "Military pension exempt; large pension exclusion at 62+ "
                            "but it phases out sharply above $150k of income."),
    "New Mexico":   _s("New Mexico", 0.049, 0.6, True, 0, 0, False,
                       "Capped military retirement exemption."),
    "New York":     _s("New York", 0.0685, 1.0, False, 20_000, 59, True,
                       "Military pension fully exempt; $20k private pension and "
                            "IRA exclusion at 59.5+."),
    "North Carolina": _s("North Carolina", 0.0399, 1.0, False,
                         note="Military retirement fully exempt (Bailey/HB 83)."),
    "North Dakota": _s("North Dakota", 0.0195, 1.0, False,
                       note="Military retirement fully exempt."),
    "Ohio":         _s("Ohio", 0.035, 1.0, False,
                       note="Military retirement fully exempt."),
    "Oklahoma":     _s("Oklahoma", 0.0475, 1.0, False, 10_000, 0, True,
                       "Military retirement fully exempt."),
    "Oregon":       _s("Oregon", 0.099, 0.0, False,
                       note="Taxes military retired pay for service after Oct "
                            "1991. High rate makes conversions costly."),
    "Pennsylvania": _s("Pennsylvania", 0.0307, 1.0, False, 0, 59, True,
                       "Does not tax retirement income, including conversions "
                            "after 59.5. Local earned income tax not modeled."),
    "Rhode Island": _s("Rhode Island", 0.0475, 1.0, False, 20_000, 0, True,
                       "Military pension exempt."),
    "South Carolina": _s("South Carolina", 0.062, 1.0, False, 10_000, 65, True,
                         "Military retirement fully deductible."),
    "South Dakota": _s("South Dakota", 0.0, 1.0, False, note="No state income tax."),
    "Tennessee":    _s("Tennessee", 0.0, 1.0, False, note="No state income tax."),
    "Texas":        _s("Texas", 0.0, 1.0, False, note="No state income tax."),
    "Utah":         _s("Utah", 0.0455, 1.0, True, 0, 0, False,
                       "Military retirement credit offsets the tax."),
    "Vermont":      _s("Vermont", 0.066, 1.0, True, 0, 0, False,
                       "Military retirement exemption is income-capped."),
    "Virginia":     _s("Virginia", 0.0575, 1.0, False, 40_000, 55, True,
                       "Military benefits subtraction, age-gated."),
    "Washington":   _s("Washington", 0.0, 1.0, False,
                       note="No income tax. A 7% tax applies to large long-term "
                            "capital gains, not to conversions."),
    "West Virginia": _s("West Virginia", 0.0482, 1.0, False, 8_000, 0, True,
                        "Military retirement fully exempt."),
    "Wisconsin":    _s("Wisconsin", 0.053, 1.0, False, 5_000, 65, True,
                       "Military retirement fully exempt."),
    "Wyoming":      _s("Wyoming", 0.0, 1.0, False, note="No state income tax."),
}

STATE_NAMES = sorted(STATE_RULES.keys())

NO_INCOME_TAX_STATES = [n for n, r in STATE_RULES.items() if r.rate == 0.0]


def get_rule(state: str) -> StateRule:
    return STATE_RULES.get(state, _s(state, 0.0, 1.0, False))


def state_tax(
    rule: StateRule,
    age: int,
    military_pension: float,
    social_security: float,
    other_ordinary: float,
    conversion: float,
    capital_gains: float,
) -> float:
    """
    State income tax for one year.

    `other_ordinary` covers wages, IRA/TSP withdrawals, SBP and any other
    ordinary income that is not military retired pay. `conversion` is the Roth
    conversion amount, kept separate so the exclusion logic can decide whether
    it qualifies.
    """
    if rule.rate <= 0.0:
        return 0.0

    taxable = 0.0
    taxable += military_pension * (1.0 - rule.military_pension_exempt)
    if rule.taxes_social_security:
        taxable += social_security
    taxable += other_ordinary
    taxable += capital_gains

    conversion_taxable = conversion

    # Apply the retirement-income exclusion, if the taxpayer is old enough.
    if rule.retirement_exclusion > 0 and age >= rule.retirement_exclusion_age:
        remaining = rule.retirement_exclusion
        # The exclusion is consumed by ordinary retirement income first.
        used = min(remaining, other_ordinary)
        taxable -= used
        remaining -= used
        if rule.conversion_uses_exclusion and remaining > 0:
            offset = min(remaining, conversion_taxable)
            conversion_taxable -= offset

    taxable += conversion_taxable
    return max(0.0, taxable) * rule.rate
