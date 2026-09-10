"""
Year-by-year projection of a military retiree household, in real (2026) dollars.

`run_projection(profile, convert=False)` and `run_projection(profile, convert=True)`
produce the two futures the app compares. Everything the engine needs comes from
the Profile object -- there are no hidden constants here beyond the statutory
tax tables.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional, Sequence

from engine.tax import tables as T
from engine.tax import federal as TX
from engine.tax import state as ST
from engine.roth_profile import Profile, Person, ConversionPlan, SYS_REDUX


# ==========================================================================
# Per-year output record
# ==========================================================================

@dataclass
class YearRow:
    year: int = 0
    age_primary: int = 0
    age_spouse: int = 0
    filing_status: str = ""
    n_alive: int = 2

    # Income, all real dollars
    wages: float = 0.0
    military_retired_pay: float = 0.0      # taxable portion, net of SBP premium
    sbp_premium: float = 0.0
    sbp_annuity: float = 0.0               # survivor only, taxable
    va_disability: float = 0.0             # tax-free
    crsc: float = 0.0                      # tax-free
    dic: float = 0.0                       # tax-free, survivor only
    social_security: float = 0.0
    taxable_ss: float = 0.0
    civilian_pension: float = 0.0
    other_taxable: float = 0.0
    other_taxfree: float = 0.0
    dividends: float = 0.0
    realized_gains: float = 0.0

    rmd: float = 0.0
    conversion: float = 0.0
    traditional_withdrawal: float = 0.0    # beyond the RMD, for spending
    roth_withdrawal: float = 0.0
    taxable_withdrawal: float = 0.0
    cash_withdrawal: float = 0.0

    # Tax
    agi: float = 0.0
    magi: float = 0.0
    taxable_income: float = 0.0
    federal_tax: float = 0.0
    state_tax: float = 0.0
    niit: float = 0.0
    irmaa: float = 0.0
    irmaa_surcharge_only: float = 0.0
    total_tax: float = 0.0
    marginal_rate: float = 0.0
    effective_rate: float = 0.0
    penalty: float = 0.0

    # Balances at end of year
    traditional_balance: float = 0.0
    roth_balance: float = 0.0
    taxable_balance: float = 0.0
    taxable_basis: float = 0.0
    cash_balance: float = 0.0
    total_portfolio: float = 0.0
    net_worth_after_tax: float = 0.0

    spending: float = 0.0
    shortfall: float = 0.0                 # unfunded spending, if assets ran out


@dataclass
class ProjectionResult:
    rows: list = field(default_factory=list)
    label: str = ""

    lifetime_federal_tax: float = 0.0
    lifetime_state_tax: float = 0.0
    lifetime_irmaa: float = 0.0
    lifetime_irmaa_surcharge: float = 0.0
    lifetime_penalty: float = 0.0
    lifetime_total_tax: float = 0.0
    lifetime_total_tax_discounted: float = 0.0

    lifetime_conversions: float = 0.0
    lifetime_rmds: float = 0.0

    ending_traditional: float = 0.0
    ending_roth: float = 0.0
    ending_taxable: float = 0.0
    ending_cash: float = 0.0

    heir_value_traditional: float = 0.0
    heir_value_roth: float = 0.0
    heir_value_taxable: float = 0.0
    heir_value_total: float = 0.0
    heir_tax_paid: float = 0.0

    total_shortfall: float = 0.0
    years_with_shortfall: int = 0
    peak_marginal_rate: float = 0.0
    max_irmaa_year: int = 0

    def to_frame(self):
        import pandas as pd
        return pd.DataFrame([asdict(r) for r in self.rows])


# ==========================================================================
# Income helpers
# ==========================================================================

def ss_claim_factor(birth_year: int, claim_age: int) -> float:
    """Benefit multiplier relative to the Primary Insurance Amount."""
    fra = T.full_retirement_age(birth_year)
    months = (claim_age - fra) * 12.0
    if abs(months) < 1e-9:
        return 1.0
    if months < 0:
        early = -months
        reduction = (min(early, 36) * T.SS_EARLY_REDUCTION_FIRST_36
                     + max(0.0, early - 36) * T.SS_EARLY_REDUCTION_BEYOND_36)
        return max(0.0, 1.0 - reduction)
    return 1.0 + (months / 12.0) * T.SS_DELAYED_CREDIT_PER_YEAR


def military_pay_real(mil, year: int, age: int) -> float:
    """
    Annual gross military retired pay in real dollars.

    REDUX pays CPI minus one percent, so its real value falls about 1% a year.
    At the recomputation age the multiplier and COLA are restored to what
    High-3 would have paid -- then the reduced COLA resumes.
    """
    gross_annual = mil.retired_pay_monthly * 12.0
    if gross_annual <= 0:
        return 0.0

    years_since = max(0, year - mil.retirement_year)
    drift = mil.cola_real_drift

    if mil.system == SYS_REDUX and mil.redux_catchup_applies and age >= mil.redux_recompute_age:
        years_since = max(0, age - mil.redux_recompute_age)

    return gross_annual * ((1.0 + drift) ** years_since)


def uniform_lifetime_divisor(age: int) -> float:
    if age in T.UNIFORM_LIFETIME_TABLE:
        return T.UNIFORM_LIFETIME_TABLE[age]
    if age < min(T.UNIFORM_LIFETIME_TABLE):
        return T.UNIFORM_LIFETIME_TABLE[min(T.UNIFORM_LIFETIME_TABLE)]
    return T.UNIFORM_LIFETIME_TABLE[max(T.UNIFORM_LIFETIME_TABLE)]


# ==========================================================================
# The projection
# ==========================================================================

class _Balances:
    """Mutable account state carried across years."""

    def __init__(self, p: Profile):
        self.trad = {"primary": p.primary.traditional_balance,
                     "spouse": p.spouse.traditional_balance if p.has_spouse else 0.0}
        self.roth = {"primary": p.primary.roth_balance,
                     "spouse": p.spouse.roth_balance if p.has_spouse else 0.0}
        self.taxable = p.taxable.balance
        self.basis = p.taxable.cost_basis if p.taxable.cost_basis > 0 else p.taxable.balance
        self.cash = p.taxable.cash_balance

    @property
    def trad_total(self) -> float:
        return sum(self.trad.values())

    @property
    def roth_total(self) -> float:
        return sum(self.roth.values())

    def draw_traditional(self, amount: float) -> float:
        """Pull pro-rata across both people's traditional accounts."""
        total = self.trad_total
        if total <= 0 or amount <= 0:
            return 0.0
        take = min(amount, total)
        for k in self.trad:
            self.trad[k] -= take * (self.trad[k] / total)
        return take

    def draw_roth(self, amount: float) -> float:
        total = self.roth_total
        if total <= 0 or amount <= 0:
            return 0.0
        take = min(amount, total)
        for k in self.roth:
            self.roth[k] -= take * (self.roth[k] / total)
        return take

    def draw_taxable(self, amount: float) -> tuple[float, float]:
        """Returns (proceeds, realized_gain). Basis recovers pro-rata."""
        if self.taxable <= 0 or amount <= 0:
            return 0.0, 0.0
        take = min(amount, self.taxable)
        basis_share = self.basis * (take / self.taxable) if self.taxable > 0 else 0.0
        gain = take - basis_share
        self.taxable -= take
        self.basis -= basis_share
        return take, max(0.0, gain)

    def draw_cash(self, amount: float) -> float:
        take = min(max(0.0, amount), self.cash)
        self.cash -= take
        return take


def run_projection(
    p: Profile,
    convert: bool,
    label: str = "",
    return_path: Optional[Sequence[float]] = None,
    inflation_path: Optional[Sequence[float]] = None,
) -> ProjectionResult:
    """
    Run one future.

    `convert` selects whether the ConversionPlan is executed. `return_path` and
    `inflation_path`, when supplied by the Monte Carlo driver, override the flat
    real-return and inflation assumptions year by year.
    """
    a = p.assumptions
    plan = p.conversion
    mil = p.military
    surv = p.survivorship

    bal = _Balances(p)
    result = ProjectionResult(label=label or ("With conversions" if convert else "No conversions"))

    start = a.start_year
    end = p.final_year()

    # Who dies first, and when
    death_year = {"primary": p.primary.birth_year + p.primary.death_age,
                  "spouse": (p.spouse.birth_year + p.spouse.death_age) if p.has_spouse else 10_000}
    if surv.model_survivor and surv.first_death != "None" and surv.first_death_year > 0:
        key = "primary" if surv.first_death == "Primary" else "spouse"
        death_year[key] = surv.first_death_year

    magi_history: dict[int, float] = {}
    cumulative_inflation = 1.0

    for year in range(start, end + 1):
        infl = inflation_path[year - start] if inflation_path is not None and (year - start) < len(inflation_path) else a.inflation
        if year > start:
            cumulative_inflation *= (1.0 + infl)
        deflator = 1.0 / cumulative_inflation

        r_trad = r_roth = r_tax = None
        if return_path is not None and (year - start) < len(return_path):
            shock = return_path[year - start]
            r_trad = a.real_return_traditional + shock
            r_roth = a.real_return_roth + shock
            r_tax = a.real_return_taxable + shock
        else:
            r_trad, r_roth, r_tax = (a.real_return_traditional,
                                     a.real_return_roth,
                                     a.real_return_taxable)

        row = YearRow(year=year)

        alive = {"primary": year <= death_year["primary"],
                 "spouse": p.has_spouse and year <= death_year["spouse"]}
        if not alive["primary"] and not alive["spouse"]:
            break

        # Spousal rollover: when one dies, their accounts move to the survivor.
        for who in ("primary", "spouse"):
            if not alive[who] and bal.trad[who] > 0:
                other = "spouse" if who == "primary" else "primary"
                bal.trad[other] += bal.trad[who]
                bal.trad[who] = 0.0
            if not alive[who] and bal.roth[who] > 0:
                other = "spouse" if who == "primary" else "primary"
                bal.roth[other] += bal.roth[who]
                bal.roth[who] = 0.0

        age_p = year - p.primary.birth_year
        age_s = (year - p.spouse.birth_year) if p.has_spouse else 0
        row.age_primary, row.age_spouse = age_p, age_s

        # Age used for rules that key off "the taxpayer": state retirement-income
        # exclusions, early-withdrawal penalties, late-life care. After a death
        # these must follow the survivor, not the person who died.
        living_age = age_p if alive["primary"] else age_s

        # Filing status: a survivor may file jointly in the year of death,
        # then files single.
        both_alive = alive["primary"] and alive["spouse"]
        # A joint return is allowed in the year a spouse dies -- but only if the
        # other spouse is alive to file it. A lone survivor's own final year is
        # still a single return.
        joint_final_year = (
            (year == death_year["primary"] and alive["spouse"])
            or (year == death_year["spouse"] and alive["primary"])
        )
        status = T.MFJ if (p.has_spouse and (both_alive or joint_final_year)) else T.SINGLE
        row.filing_status = status
        row.n_alive = int(alive["primary"]) + int(alive["spouse"])

        n_65 = sum(1 for who, ag in (("primary", age_p), ("spouse", age_s))
                   if alive[who] and ag >= 65)
        n_people = row.n_alive
        n_medicare = sum(
            1 for who, ag in (("primary", age_p), ("spouse", age_s))
            if alive[who] and ag >= mil.medicare_part_b_age)

        # ---------------- Income ----------------
        wages = 0.0
        for who, person in (("primary", p.primary), ("spouse", p.spouse if p.has_spouse else None)):
            if person is None or not alive[who]:
                continue
            if year <= person.work_through_year and person.annual_wages > 0:
                yrs = max(0, year - start)
                wages += person.annual_wages * ((1.0 + person.wage_real_growth) ** yrs)
        row.wages = wages

        # Military retired pay -- stops at the retiree's death, replaced by SBP
        mil_gross = 0.0
        sbp_prem = 0.0
        va = 0.0
        crsc = 0.0
        sbp_annuity = 0.0
        dic = 0.0

        if alive["primary"] and mil.retired_pay_monthly > 0:
            mil_gross = military_pay_real(mil, year, age_p)
            if mil.sbp_elected and not mil.sbp_paid_up:
                base = (mil.sbp_base_amount_monthly * 12.0
                        if mil.sbp_base_amount_monthly > 0 else mil_gross)
                sbp_prem = base * mil.sbp_premium_rate
            va = mil.va_disability_monthly * 12.0
            crsc = mil.crsc_monthly * 12.0
            # Without concurrent receipt, VA compensation offsets retired pay.
            if not mil.crdp_applies:
                mil_gross = max(0.0, mil_gross - va)
            if crsc > 0:
                mil_gross = max(0.0, mil_gross - crsc)
        elif p.has_spouse and alive["spouse"] and mil.retired_pay_monthly > 0 and mil.sbp_elected:
            # Survivor: SBP annuity replaces retired pay. VA compensation ends;
            # DIC may begin.
            # The SBP base is fixed at the retiree's death; it does not keep
            # drifting with the COLA rule that applied to them in life.
            death_yr = death_year["primary"]
            base = (mil.sbp_base_amount_monthly * 12.0
                    if mil.sbp_base_amount_monthly > 0
                    else military_pay_real(mil, death_yr,
                                           death_yr - p.primary.birth_year))
            sbp_annuity = base * T.SBP_ANNUITY_RATE
            if surv.dic_applies:
                dic = surv.dic_monthly * 12.0
                if surv.sbp_dic_offset:
                    sbp_annuity = max(0.0, sbp_annuity - dic)

        row.military_retired_pay = max(0.0, mil_gross - sbp_prem)
        row.sbp_premium = sbp_prem
        row.sbp_annuity = sbp_annuity
        row.va_disability = va
        row.crsc = crsc
        row.dic = dic

        # Social Security. A survivor keeps the larger of the two benefits.
        ss_each = {}
        for who, person in (("primary", p.primary), ("spouse", p.spouse if p.has_spouse else None)):
            if person is None:
                ss_each[who] = 0.0
                continue
            amt = 0.0
            age_this = age_p if who == "primary" else age_s
            if person.ss_pia_monthly > 0 and age_this >= person.ss_claim_age:
                amt = (person.ss_pia_monthly * 12.0
                       * ss_claim_factor(person.birth_year, person.ss_claim_age))
            if person.receives_ssdi and person.ssdi_monthly > 0 and age_this < person.ss_claim_age:
                amt = max(amt, person.ssdi_monthly * 12.0)
            ss_each[who] = amt

        if row.n_alive == 2:
            ss_total = ss_each["primary"] + ss_each["spouse"]
        elif alive["primary"]:
            ss_total = max(ss_each["primary"], ss_each["spouse"]) if p.has_spouse else ss_each["primary"]
        else:
            ss_total = max(ss_each["primary"], ss_each["spouse"])
        row.social_security = ss_total

        # Civilian pension
        oi = p.other_income
        civ = 0.0
        if oi.civilian_pension_monthly > 0:
            ref_age = living_age
            if ref_age >= oi.civilian_pension_start_age:
                yrs = ref_age - oi.civilian_pension_start_age
                civ = (oi.civilian_pension_monthly * 12.0
                       * ((1.0 + oi.civilian_pension_cola_real) ** yrs))
                if row.n_alive < 2 and not alive["primary"]:
                    civ *= oi.civilian_pension_survivor_pct
        row.civilian_pension = civ
        row.other_taxable = oi.rental_net_annual + oi.other_taxable_annual
        row.other_taxfree = oi.other_taxfree_annual + row.va_disability + row.crsc + row.dic

        # Taxable-account income
        dividends = bal.taxable * p.taxable.dividend_yield
        qual_div = dividends * p.taxable.qualified_dividend_share
        nonqual_div = dividends - qual_div
        gain_fraction = 0.0 if bal.taxable <= 0 else max(0.0, 1.0 - bal.basis / bal.taxable)
        turnover_gains = bal.taxable * p.taxable.turnover_rate * gain_fraction
        row.dividends = dividends
        bal.basis += turnover_gains   # realised gains step up remaining basis

        # ---------------- RMD ----------------
        rmd = 0.0
        for who, person in (("primary", p.primary), ("spouse", p.spouse if p.has_spouse else None)):
            if person is None or not alive[who] or bal.trad[who] <= 0:
                continue
            age_this = age_p if who == "primary" else age_s
            if age_this >= p.rmd_age(person):
                rmd += bal.trad[who] / uniform_lifetime_divisor(age_this)
        rmd = min(rmd, bal.trad_total)
        row.rmd = rmd
        if rmd > 0:
            bal.draw_traditional(rmd)

        # ---------------- Tax assembly closure ----------------
        magi_lookback = magi_history.get(year - T.IRMAA_LOOKBACK_YEARS, 0.0)
        irmaa_full = TX.irmaa_annual(magi_lookback, status, n_medicare)
        irmaa_surcharge = TX.irmaa_annual(magi_lookback, status, n_medicare,
                                          count_base_premium=False)

        regime = TX.regime_for_year(p.tax_policy, year, status, n_65, n_people)

        state_rule = ST.get_rule(p.state)
        if p.state_rate_override >= 0:
            state_rule = ST.StateRule(**{**state_rule.to_dict(),
                                         "rate": p.state_rate_override})
        if p.state_military_exempt_override >= 0:
            state_rule = ST.StateRule(**{**state_rule.to_dict(),
                                         "military_pension_exempt": float(p.state_military_exempt_override)})

        def tax_for(conversion: float, extra_trad: float, extra_gain: float):
            other_ordinary = (row.wages + row.sbp_annuity + row.civilian_pension
                              + row.other_taxable + row.rmd + extra_trad)
            st = ST.state_tax(
                state_rule, living_age,
                military_pension=row.military_retired_pay,
                social_security=row.social_security,
                other_ordinary=other_ordinary,
                conversion=conversion,
                capital_gains=turnover_gains + extra_gain + dividends,
            )
            return TX.compute_year_tax(
                regime=regime,
                status=status,
                wages=row.wages,
                military_pension=row.military_retired_pay,
                other_pension=row.civilian_pension + row.sbp_annuity,
                taxable_withdrawals=row.rmd + extra_trad,
                conversion=conversion,
                social_security=row.social_security,
                interest_and_nonqual_div=nonqual_div + row.other_taxable,
                qualified_dividends=qual_div,
                capital_gains=turnover_gains + extra_gain,
                tax_exempt_interest=0.0,
                n_people_65plus=n_65,
                ss_deflator=deflator,
                niit_deflator=deflator,
                index_niit=p.tax_policy.index_niit_threshold,
                state_tax_amount=st,
                irmaa_amount=irmaa_full,
            )

        # ---------------- Roth conversion ----------------
        conversion = 0.0
        if convert and plan.enabled and plan.start_year <= year <= plan.end_year:
            conversion = _solve_conversion(
                plan, p, bal, tax_for, regime, status, year, living_age,
                still_working=row.wages > 0,
                irmaa_status=status,
            )
        row.conversion = conversion
        if conversion > 0:
            bal.draw_traditional(conversion)

        # ---------------- Spending and withdrawals ----------------
        spending = 0.0
        if year >= a.spending_start_year and a.annual_spending > 0:
            yrs = max(0, year - a.spending_start_year)
            spending = a.annual_spending * ((1.0 + a.spending_real_drift) ** yrs)
            if row.n_alive < 2 and p.has_spouse:
                spending *= a.survivor_spending_factor
        if a.late_life_care_annual > 0 and living_age >= a.late_life_care_start_age:
            spending += a.late_life_care_annual
        if mil.has_tricare:
            spending += mil.tricare_annual_cost
        row.spending = spending

        # Cash in hand before touching investments. The RMD is already a
        # distribution, so it counts here.
        base_cash_in = (row.wages + row.military_retired_pay + row.sbp_annuity
                        + row.social_security + row.civilian_pension
                        + row.other_taxable + row.other_taxfree + row.rmd
                        + dividends)

        extra_trad = extra_gain = roth_draw = taxable_draw = cash_draw = 0.0
        tr = tax_for(conversion, 0.0, 0.0)

        def conversion_tax(tr_now, et, eg) -> float:
            """Marginal tax created by the conversion, holding all else equal."""
            if conversion <= 0:
                return 0.0
            return max(0.0, tr_now.total_tax - tax_for(0.0, et, eg).total_tax)

        # Withdrawing from a traditional account raises tax, which raises the
        # amount that must be withdrawn. Iterate to a fixed point.
        for _ in range(10):
            conv_tax = conversion_tax(tr, extra_trad, extra_gain)
            # If the tax is withheld from the conversion itself, it is already
            # funded and must not also be drawn from the portfolio.
            withheld = conv_tax if (conversion > 0 and not plan.pay_tax_from_taxable) else 0.0

            need = max(0.0, spending + tr.total_tax - base_cash_in - withheld)
            if need <= 1.0:
                cash_draw = taxable_draw = extra_gain = extra_trad = roth_draw = 0.0
                tr = tax_for(conversion, 0.0, 0.0)
                break

            cash_draw = taxable_draw = extra_gain = extra_trad = roth_draw = 0.0
            remaining = need
            for source in a.withdrawal_order:
                if remaining <= 0:
                    break
                if source == "cash":
                    cash_draw = min(remaining, bal.cash)
                    remaining -= cash_draw
                elif source == "taxable":
                    taxable_draw = min(remaining, bal.taxable)
                    gf = 0.0 if bal.taxable <= 0 else max(0.0, 1.0 - bal.basis / bal.taxable)
                    extra_gain = taxable_draw * gf
                    remaining -= taxable_draw
                elif source == "traditional":
                    extra_trad = min(remaining, bal.trad_total)
                    remaining -= extra_trad
                elif source == "roth":
                    roth_draw = min(remaining, bal.roth_total)
                    remaining -= roth_draw

            new_tr = tax_for(conversion, extra_trad, extra_gain)
            converged = abs(new_tr.total_tax - tr.total_tax) < 1.0
            tr = new_tr
            if converged:
                break

        conv_tax = conversion_tax(tr, extra_trad, extra_gain)
        withheld = conv_tax if (conversion > 0 and not plan.pay_tax_from_taxable) else 0.0

        # Apply the draws to real balances
        cash_draw = bal.draw_cash(cash_draw)
        taxable_draw, realized = bal.draw_taxable(taxable_draw)
        extra_trad = bal.draw_traditional(extra_trad)
        roth_draw = bal.draw_roth(roth_draw)

        # Early-withdrawal penalty on traditional dollars taken before 59.5.
        penalty = 0.0
        if extra_trad > 0 and living_age < plan.penalty_free_age:
            penalty += extra_trad * plan.early_withdrawal_penalty
        if withheld > 0 and living_age < plan.penalty_free_age:
            # Tax withheld from a conversion is itself a taxable distribution.
            penalty += withheld * plan.early_withdrawal_penalty

        row.penalty = penalty
        row.traditional_withdrawal = extra_trad
        row.roth_withdrawal = roth_draw
        row.taxable_withdrawal = taxable_draw
        row.cash_withdrawal = cash_draw
        row.realized_gains = turnover_gains + realized

        funded = base_cash_in + cash_draw + taxable_draw + extra_trad + roth_draw + withheld
        required = spending + tr.total_tax + penalty
        row.shortfall = max(0.0, required - funded)

        # Route the conversion into the Roth.
        if conversion > 0:
            bal.roth["primary"] += max(0.0, conversion - withheld)

        # Surplus income is reinvested in the taxable account rather than
        # disappearing. Without this the no-conversion future would silently
        # throw away its RMD proceeds and look better than it is.
        surplus = max(0.0, funded - required)
        if surplus > 0 and (cash_draw + taxable_draw + extra_trad + roth_draw) <= 1.0:
            bal.taxable += surplus
            bal.basis += surplus

        # Ongoing contributions while working
        for who, person in (("primary", p.primary), ("spouse", p.spouse if p.has_spouse else None)):
            if person is None or not alive[who] or year > person.work_through_year:
                continue
            bal.trad[who] += person.traditional_contribution
            bal.roth[who] += person.roth_contribution
        if year <= max(pp.work_through_year for pp in p.people()):
            bal.taxable += p.taxable.annual_contribution
            bal.basis += p.taxable.annual_contribution

        # ---------------- Record tax ----------------
        row.agi, row.magi = tr.agi, tr.magi
        row.taxable_income = tr.taxable_income
        row.taxable_ss = tr.taxable_ss
        row.federal_tax = tr.federal_ordinary_tax + tr.federal_cap_gains_tax
        row.niit = tr.niit
        row.state_tax = tr.state_total
        row.irmaa = irmaa_full
        row.irmaa_surcharge_only = irmaa_surcharge
        row.total_tax = tr.total_tax + penalty
        row.marginal_rate = tr.marginal_rate
        row.effective_rate = (row.total_tax / tr.agi) if tr.agi > 0 else 0.0
        magi_history[year] = tr.magi

        # ---------------- Growth ----------------
        for k in bal.trad:
            bal.trad[k] *= (1.0 + r_trad)
        for k in bal.roth:
            bal.roth[k] *= (1.0 + r_roth)
        # Dividends were distributed as cash above, so they leave the balance.
        bal.taxable = max(0.0, bal.taxable * (1.0 + r_tax) - dividends)
        bal.cash *= (1.0 + a.real_return_cash)

        row.traditional_balance = bal.trad_total
        row.roth_balance = bal.roth_total
        row.taxable_balance = bal.taxable
        row.taxable_basis = bal.basis
        row.cash_balance = bal.cash
        row.total_portfolio = bal.trad_total + bal.roth_total + bal.taxable + bal.cash

        result.rows.append(row)

    _summarise(result, p)
    return result


def _solve_conversion(plan, p: Profile, bal, tax_for, regime, status, year,
                      age_p, still_working: bool, irmaa_status: str) -> float:
    """
    Decide how much to convert this year.

    Bracket and IRMAA targeting use a bisection search rather than a formula,
    because converting raises the taxable share of Social Security, which in
    turn eats the headroom. The search finds the amount that lands exactly on
    the ceiling with that feedback included.
    """
    available = bal.trad_total - plan.floor_balance
    if available <= 0:
        return 0.0
    if plan.skip_while_working and still_working:
        return 0.0

    cap = plan.annual_cap if plan.annual_cap > 0 else float("inf")

    if plan.strategy == ConversionPlan.STRATEGY_FIXED:
        return max(0.0, min(plan.fixed_amount, available, cap))

    if plan.strategy == ConversionPlan.STRATEGY_PERCENT:
        return max(0.0, min(bal.trad_total * plan.percent_of_balance, available, cap))

    if plan.strategy == ConversionPlan.STRATEGY_TARGET:
        years_left = max(1, plan.end_year - year + 1)
        excess = bal.trad_total - plan.target_remaining_balance
        if excess <= 0:
            return 0.0
        return max(0.0, min(excess / years_left, available, cap))

    if plan.strategy == ConversionPlan.STRATEGY_IRMAA:
        ceilings = TX.irmaa_tier_ceilings(irmaa_status)
        idx = min(max(0, plan.irmaa_tier_index), len(ceilings) - 1)
        target_magi = ceilings[idx]

        def over(x: float) -> bool:
            return tax_for(x, 0.0, 0.0).magi > target_magi

        if over(0.0):
            return 0.0
        return _bisect(over, 0.0, min(available, cap))

    # STRATEGY_BRACKET
    ceiling = 0.0
    for bound, rate in regime.ordinary_brackets:
        if rate <= plan.target_bracket + 1e-9:
            ceiling = bound
    if ceiling == float("inf") or ceiling == 0.0:
        return max(0.0, min(available, cap))

    def over_bracket(x: float) -> bool:
        return tax_for(x, 0.0, 0.0).ordinary_taxable > ceiling

    if over_bracket(0.0):
        return 0.0
    return _bisect(over_bracket, 0.0, min(available, cap))


def _bisect(is_over, lo: float, hi: float, iters: int = 45) -> float:
    """Largest value in [lo, hi] for which is_over() is still False."""
    if hi <= lo:
        return 0.0
    if not is_over(hi):
        return hi
    for _ in range(iters):
        mid = (lo + hi) / 2.0
        if is_over(mid):
            hi = mid
        else:
            lo = mid
    return max(0.0, lo)


def _summarise(result: ProjectionResult, p: Profile) -> None:
    a = p.assumptions
    h = p.heirs

    disc = 0.0
    for i, r in enumerate(result.rows):
        result.lifetime_federal_tax += r.federal_tax + r.niit
        result.lifetime_state_tax += r.state_tax
        result.lifetime_irmaa += r.irmaa
        result.lifetime_irmaa_surcharge += r.irmaa_surcharge_only
        result.lifetime_penalty += r.penalty
        result.lifetime_conversions += r.conversion
        result.lifetime_rmds += r.rmd
        result.total_shortfall += r.shortfall
        if r.shortfall > 1.0:
            result.years_with_shortfall += 1
        result.peak_marginal_rate = max(result.peak_marginal_rate, r.marginal_rate)
        disc += r.total_tax / ((1.0 + a.discount_rate) ** i)

    result.lifetime_total_tax = (result.lifetime_federal_tax + result.lifetime_state_tax
                                 + result.lifetime_irmaa + result.lifetime_penalty)
    result.lifetime_total_tax_discounted = disc

    if result.rows:
        last = result.rows[-1]
        result.ending_traditional = last.traditional_balance
        result.ending_roth = last.roth_balance
        result.ending_taxable = last.taxable_balance
        result.ending_cash = last.cash_balance

        peak = max(result.rows, key=lambda r: r.irmaa_surcharge_only)
        result.max_irmaa_year = peak.year if peak.irmaa_surcharge_only > 0 else 0

    # ---- Value delivered to heirs, after their taxes ----
    heir_rate = h.heir_marginal_rate + h.heir_state_rate
    n_years = max(1, h.drain_years)
    r_h = h.heir_real_return

    def drain_value(balance: float, taxed: bool) -> tuple[float, float]:
        """Present value at death of an inherited account emptied over n_years."""
        if balance <= 0:
            return 0.0, 0.0
        remaining = balance
        pv, tax_paid = 0.0, 0.0
        for i in range(1, n_years + 1):
            remaining *= (1.0 + r_h)
            take = remaining / (n_years - i + 1)
            remaining -= take
            t = take * heir_rate if taxed else 0.0
            tax_paid += t
            pv += (take - t) / ((1.0 + r_h) ** i)
        return pv, tax_paid

    trad_pv, trad_tax = drain_value(result.ending_traditional, taxed=True)
    roth_pv, _ = drain_value(result.ending_roth, taxed=False) if h.value_roth_tax_free_growth \
        else (result.ending_roth, 0.0)

    # Taxable accounts receive a step-up in basis at death.
    taxable_pv = result.ending_taxable + result.ending_cash

    result.heir_value_traditional = trad_pv
    result.heir_value_roth = roth_pv
    result.heir_value_taxable = taxable_pv
    result.heir_value_total = trad_pv + roth_pv + taxable_pv
    result.heir_tax_paid = trad_tax

    if result.rows:
        result.rows[-1].net_worth_after_tax = result.heir_value_total
