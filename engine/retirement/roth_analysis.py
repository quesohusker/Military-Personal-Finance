"""
Turns two projections into a decision.

The engine produces numbers. This module produces findings: where the
conversion window is, what the RMD actually stacks on top of, what the survivor
pays, and whether converting wins or loses.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import copy

from engine.roth_profile import Profile, ConversionPlan
from engine.retirement.projection import run_projection, ProjectionResult
from engine.tax import tables as T
from engine.tax import federal as TX
from engine.tax import state as ST


@dataclass
class Finding:
    severity: str      # "good", "warn", "bad", "info"
    headline: str
    detail: str


@dataclass
class Comparison:
    base: ProjectionResult = None
    conv: ProjectionResult = None

    tax_saved: float = 0.0
    tax_saved_discounted: float = 0.0
    legacy_gain: float = 0.0
    heir_tax_saved: float = 0.0
    irmaa_cost: float = 0.0
    breakeven_year: int = 0
    findings: list = field(default_factory=list)

    @property
    def converting_wins(self) -> bool:
        return self.legacy_gain > 0


def compare(p: Profile) -> Comparison:
    base = run_projection(p, convert=False, label="No conversions")
    conv = run_projection(p, convert=True, label="With conversions")

    c = Comparison(base=base, conv=conv)
    c.tax_saved = base.lifetime_total_tax - conv.lifetime_total_tax
    c.tax_saved_discounted = (base.lifetime_total_tax_discounted
                              - conv.lifetime_total_tax_discounted)
    c.legacy_gain = conv.heir_value_total - base.heir_value_total
    c.heir_tax_saved = base.heir_tax_paid - conv.heir_tax_paid
    c.irmaa_cost = conv.lifetime_irmaa_surcharge - base.lifetime_irmaa_surcharge
    c.breakeven_year = _breakeven(base, conv)
    c.findings = build_findings(p, c)
    return c


def _breakeven(base: ProjectionResult, conv: ProjectionResult) -> int:
    """
    First year in which the conversion path's total after-tax position
    (portfolio, with the traditional balance discounted for embedded tax)
    overtakes the no-conversion path.
    """
    n = min(len(base.rows), len(conv.rows))
    for i in range(n):
        rb, rc = base.rows[i], conv.rows[i]
        eff = 0.24
        vb = rb.roth_balance + rb.taxable_balance + rb.cash_balance + rb.traditional_balance * (1 - eff)
        vc = rc.roth_balance + rc.taxable_balance + rc.cash_balance + rc.traditional_balance * (1 - eff)
        if vc > vb:
            return rc.year
    return 0


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------

def _money(x: float) -> str:
    return f"${x:,.0f}"


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def build_findings(p: Profile, c: Comparison) -> list[Finding]:
    f: list[Finding] = []
    base, conv = c.base, c.conv
    rows = base.rows
    if not rows:
        return f

    # ---- The RMD stack ----
    rmd_rows = [r for r in rows if r.rmd > 0]
    if rmd_rows:
        first = rmd_rows[0]
        peak = max(rmd_rows, key=lambda r: r.rmd)
        floor_income = (first.military_retired_pay + first.social_security
                        + first.civilian_pension + first.wages + first.sbp_annuity)
        f.append(Finding(
            "warn" if first.marginal_rate >= 0.22 else "info",
            f"Your first RMD is {_money(first.rmd)} at age {first.age_primary}, "
            f"and it does not start in a low bracket.",
            f"By {first.year} you already have {_money(floor_income)} of taxable "
            f"income from pension, Social Security and other fixed sources before "
            f"a dollar comes out of the IRA. The RMD stacks on top of that, at a "
            f"{_pct(first.marginal_rate)} marginal rate. RMDs peak at "
            f"{_money(peak.rmd)} in {peak.year}. This is the part people miss: "
            f"the RMD is not taxed at your average rate, it is taxed at the rate "
            f"above everything else you already receive."))
    else:
        f.append(Finding(
            "good", "No RMDs are projected during your lifetime.",
            "Either the traditional balance is small or it is spent down before "
            "the required beginning date. The case for converting is weaker here "
            "-- check the legacy and survivor numbers before deciding."))

    # ---- The conversion window ----
    window = _find_window(p, rows)
    if window:
        y0, y1, rate = window
        f.append(Finding(
            "good",
            f"Your conversion window is {y0} to {y1} -- {y1 - y0 + 1} years at a "
            f"{_pct(rate)} marginal rate.",
            f"Wages have stopped, Social Security and RMDs have not started, and "
            f"your bracket is at its lifetime low. Every dollar converted in this "
            f"window is taxed at {_pct(rate)} instead of the "
            f"{_pct(base.peak_marginal_rate)} you hit later."))

    # ---- The widow's penalty ----
    widow = _widow_effect(rows)
    if widow:
        before, after = widow
        f.append(Finding(
            "bad",
            f"The survivor's marginal rate jumps from {_pct(before.marginal_rate)} "
            f"to {_pct(after.marginal_rate)} -- on less income.",
            f"In {before.year} the household had {_money(before.agi)} of AGI and "
            f"paid {_money(before.federal_tax)} in federal tax. In {after.year} "
            f"the survivor has {_money(after.agi)} -- less -- and pays "
            f"{_money(after.federal_tax)}. Retired pay stops, one Social Security "
            f"check stops, and single brackets are half as wide as joint ones. "
            f"This is usually the single largest argument for converting while "
            f"both of you are alive."))

    # ---- Military-specific: TRICARE removes the ACA constraint ----
    if p.military.has_tricare:
        f.append(Finding(
            "good",
            "TRICARE means no ACA subsidy cliff limits how much you convert.",
            "A civilian retiring before 65 loses premium tax credits as income "
            "rises, which caps conversions hard. You do not have that constraint. "
            "Your conversion window is wider than a civilian's with the same "
            "balance sheet. It closes at 65, when Medicare Part B -- required for "
            "TRICARE For Life -- brings IRMAA into play."))

    # ---- VA disability: tax-free income does not fill brackets ----
    va_annual = p.military.va_disability_monthly * 12
    if va_annual > 0:
        f.append(Finding(
            "info",
            f"Your {_money(va_annual)} of VA compensation is tax-free, which cuts "
            f"both ways.",
            "It funds your spending without generating taxable income, so you need "
            "fewer IRA withdrawals -- which is exactly why the traditional balance "
            "keeps growing untouched until RMDs force it out. Tax-free income does "
            "not fill your low brackets. Conversions are what fill them."))

    # ---- State treatment ----
    rule = ST.get_rule(p.state)
    if p.state_rate_override >= 0:
        rate = p.state_rate_override
    else:
        rate = rule.rate
    if rate <= 0:
        f.append(Finding(
            "good", f"{p.state} has no income tax, so a conversion costs you "
                    f"federal tax only.",
            "If you might move to a state that taxes retirement income, converting "
            "before the move is worth a hard look."))
    elif rule.military_pension_exempt >= 1.0:
        f.append(Finding(
            "info",
            f"{p.state} exempts military retired pay but taxes conversions at "
            f"about {_pct(rate)}.",
            f"{rule.note} Your pension escapes state tax; the conversion does not. "
            f"Total lifetime state tax differs by "
            f"{_money(base.lifetime_state_tax - conv.lifetime_state_tax)} between "
            f"the two futures."))
    else:
        f.append(Finding(
            "warn",
            f"{p.state} taxes military retired pay at about {_pct(rate)}.",
            rule.note or "Both your pension and any conversion are exposed."))

    # ---- IRMAA ----
    if c.irmaa_cost > 1000:
        f.append(Finding(
            "warn",
            f"Converting adds {_money(c.irmaa_cost)} of lifetime Medicare IRMAA "
            f"surcharges.",
            "IRMAA is a cliff, not a ramp: one dollar over a threshold raises the "
            "premium for the whole year, and it is assessed on income from two "
            "years earlier. If you are within two years of 65, try the "
            "'Fill to an IRMAA tier ceiling' strategy and compare."))
    elif c.irmaa_cost < -1000:
        f.append(Finding(
            "good",
            f"Converting saves {_money(-c.irmaa_cost)} of lifetime IRMAA "
            f"surcharges.",
            "Draining the traditional balance early keeps later RMDs from pushing "
            "MAGI over the Medicare thresholds."))

    # ---- Heirs ----
    if p.heirs.n_beneficiaries > 0 and base.ending_traditional > 0:
        per = base.ending_traditional / max(1, p.heirs.n_beneficiaries)
        f.append(Finding(
            "warn",
            f"Your heirs inherit {_money(base.ending_traditional)} of pre-tax "
            f"money and must empty it within {p.heirs.drain_years} years.",
            f"That is about {_money(per)} each, forced out during their peak "
            f"earning years at an assumed "
            f"{_pct(p.heirs.heir_marginal_rate + p.heirs.heir_state_rate)} combined "
            f"rate -- {_money(base.heir_tax_paid)} of tax. Converting cuts that to "
            f"{_money(conv.heir_tax_paid)}. A Roth passes to them with no tax bill "
            f"and ten more years of tax-free growth."))

    # ---- The verdict ----
    if c.legacy_gain > 0:
        f.append(Finding(
            "good",
            f"Converting leaves {_money(c.legacy_gain)} more, after all taxes.",
            f"Lifetime tax falls by {_money(c.tax_saved)}. Total converted: "
            f"{_money(conv.lifetime_conversions)}. RMDs drop from "
            f"{_money(base.lifetime_rmds)} to {_money(conv.lifetime_rmds)}."
            + (f" The conversion path pulls ahead in {c.breakeven_year}."
               if c.breakeven_year else "")))
    else:
        f.append(Finding(
            "bad",
            f"Converting loses {_money(-c.legacy_gain)} under these assumptions.",
            "Do not convert on faith. Common reasons this happens: your retirement "
            "bracket is genuinely lower than your conversion bracket, the "
            "conversion is too aggressive and spills into a higher bracket, or the "
            "tax is being paid out of the IRA rather than from outside money. "
            "Try a lower target bracket before concluding conversions do not work."))

    # ---- Paying the tax from the wrong pocket ----
    if not p.conversion.pay_tax_from_taxable:
        f.append(Finding(
            "bad",
            "You are paying the conversion tax out of the IRA itself.",
            "This is the most common way a Roth conversion fails to pay off. Money "
            "withheld for tax never reaches the Roth, so you lose its growth "
            "forever -- and before 59.5 it is also hit with a 10% penalty. If you "
            "have taxable savings, pay the tax from there and switch this setting."))

    return f


def _find_window(p: Profile, rows) -> tuple[int, int, float] | None:
    """Longest run of consecutive years at the lowest marginal rate seen."""
    candidates = [r for r in rows if r.wages <= 0 and r.rmd <= 0]
    if not candidates:
        return None
    low = min(r.marginal_rate for r in candidates)
    best = cur = None
    for r in candidates:
        if abs(r.marginal_rate - low) < 1e-9:
            if cur is None:
                cur = [r.year, r.year]
            else:
                cur[1] = r.year
        else:
            if cur and (best is None or (cur[1] - cur[0]) > (best[1] - best[0])):
                best = cur
            cur = None
    if cur and (best is None or (cur[1] - cur[0]) > (best[1] - best[0])):
        best = cur
    if not best:
        return None
    return best[0], best[1], low


def _widow_effect(rows):
    """The last joint year and the first single year that follows it."""
    for i in range(1, len(rows)):
        if rows[i].n_alive < rows[i - 1].n_alive and rows[i].filing_status == T.SINGLE:
            return rows[i - 1], rows[i]
    return None


# --------------------------------------------------------------------------
# Sweeps
# --------------------------------------------------------------------------

def sweep_target_brackets(p: Profile, brackets=(0.10, 0.12, 0.22, 0.24, 0.32)) -> list[dict]:
    """Run the conversion future at each target bracket and rank the outcomes."""
    out = []
    base = run_projection(p, convert=False)
    for b in brackets:
        q = copy.deepcopy(p)
        q.conversion.enabled = True
        q.conversion.strategy = ConversionPlan.STRATEGY_BRACKET
        q.conversion.target_bracket = b
        r = run_projection(q, convert=True)
        out.append({
            "target_bracket": b,
            "total_converted": r.lifetime_conversions,
            "lifetime_tax": r.lifetime_total_tax,
            "legacy": r.heir_value_total,
            "legacy_gain": r.heir_value_total - base.heir_value_total,
            "irmaa": r.lifetime_irmaa_surcharge,
            "ending_traditional": r.ending_traditional,
        })
    out.append({
        "target_bracket": 0.0,
        "total_converted": 0.0,
        "lifetime_tax": base.lifetime_total_tax,
        "legacy": base.heir_value_total,
        "legacy_gain": 0.0,
        "irmaa": base.lifetime_irmaa_surcharge,
        "ending_traditional": base.ending_traditional,
    })
    return sorted(out, key=lambda d: -d["legacy_gain"])


def sweep_tax_scenarios(p: Profile, scenarios: list) -> list[dict]:
    """
    Re-run the comparison under each future-tax scenario. This answers the
    question the deterministic view cannot: does the conversion decision hold up
    if rates rise?
    """
    out = []
    for name, policy in scenarios:
        q = copy.deepcopy(p)
        q.tax_policy = policy
        b = run_projection(q, convert=False)
        c = run_projection(q, convert=True)
        out.append({
            "scenario": name,
            "tax_no_convert": b.lifetime_total_tax,
            "tax_convert": c.lifetime_total_tax,
            "tax_saved": b.lifetime_total_tax - c.lifetime_total_tax,
            "legacy_no_convert": b.heir_value_total,
            "legacy_convert": c.heir_value_total,
            "legacy_gain": c.heir_value_total - b.heir_value_total,
        })
    return out
