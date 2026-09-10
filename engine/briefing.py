"""
Builds a self-contained Markdown briefing about a plan, for pasting into an LLM.

The point is a *second opinion*, not a transcript. A raw data dump makes an LLM
agree with you, because it has nothing to push back with. So the briefing also
carries the modelling assumptions, the things the engine deliberately does not
model, and a set of questions worth asking -- enough context for another model
to find what this one missed.

Nothing here touches Streamlit; the file is plain text and is generated locally.
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import date
import json

from engine.roth_profile import Profile, ConversionPlan
from engine.retirement.projection import ss_claim_factor, uniform_lifetime_divisor
from engine.tax import tables as T
from engine.tax import state as ST


@dataclass
class BriefingOptions:
    anonymize: bool = True
    round_to: int = 0            # round dollars to nearest N; 0 = exact
    table_mode: str = "Milestone years"   # or "Every year" / "None"
    include_findings: bool = True
    include_scenarios: bool = True
    include_monte_carlo: bool = True
    include_json: bool = False
    include_questions: bool = True


TABLE_MODES = ["Milestone years", "Every year", "None"]


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------

def _mk_money(opts: BriefingOptions):
    def money(x: float) -> str:
        if opts.round_to > 0:
            x = round(x / opts.round_to) * opts.round_to
        sign = "-" if x < 0 else ""
        return f"{sign}${abs(x):,.0f}"
    return money


def _pct(x: float, dp: int = 1) -> str:
    return f"{x * 100:.{dp}f}%"


def _name(person, fallback: str, opts: BriefingOptions) -> str:
    if opts.anonymize or not person.name:
        return fallback
    return person.name


def _table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


# --------------------------------------------------------------------------
# Year selection
# --------------------------------------------------------------------------

def _milestone_years(p: Profile, base_rows, conv_rows) -> set[int]:
    """Years where something structural happens, plus a regular sample."""
    years = set()
    if not base_rows:
        return years

    first, last = base_rows[0].year, base_rows[-1].year
    years.update({first, last})

    for person in p.people():
        if person.work_through_year >= first:
            years.add(person.work_through_year)
            years.add(person.work_through_year + 1)
        if person.ss_pia_monthly > 0:
            years.add(person.birth_year + person.ss_claim_age)
        years.add(person.birth_year + p.rmd_age(person))
        years.add(person.birth_year + 65)          # Medicare / IRMAA begins
        years.add(person.birth_year + person.death_age)
        years.add(person.birth_year + person.death_age + 1)

    for r in conv_rows:
        if r.conversion > 0:
            years.add(r.year)

    # A regular sample so the shape is visible between events.
    years.update(range(first, last + 1, 5))
    return {y for y in years if first <= y <= last}


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------

def _header(p: Profile, opts: BriefingOptions) -> str:
    return f"""# Roth Conversion Analysis — Briefing for Review

**Plan:** {p.profile_name}
**Generated:** {date.today().isoformat()}
**Source:** Military Roth Conversion Planner

---

## What this document is

A projection of two futures for a **military retiree household**: one where no
Roth conversions are made, and one where they are made on a stated schedule.
Everything below — inputs, assumptions and results — comes from a deterministic
year-by-year model. **All dollar figures are in real (inflation-adjusted) 2026
dollars**, so a number in 2055 is directly comparable to one in 2026.

## What I want from you

Act as a **critical reviewer, not a validator.** I am looking for what this
analysis gets wrong or leaves out. Specifically:

1. **Challenge the assumptions.** Which inputs is the conclusion most sensitive
   to? Which look unrealistic?
2. **Find the omissions.** A list of what the model does not include is in the
   "Known limitations" section. Tell me which of those would actually change
   this answer, and by roughly how much.
3. **Check the military-specific reasoning.** Retired pay, VA compensation,
   concurrent receipt, SBP, DIC and TRICARE/IRMAA interact in ways general
   retirement advice gets wrong. Verify the treatment described below.
4. **Sanity-check the tax math** against current law as you understand it, and
   flag anything stale. Tax tables here are 2026 figures.
5. **Tell me if the conclusion is wrong.** If converting is not actually the
   right call here, say so plainly and explain why.

Do not simply summarise this document back to me.
"""


def _household(p: Profile, opts: BriefingOptions, money) -> str:
    lines = ["## Household\n"]
    rows = []
    for label, person in [("You", p.primary)] + (
            [("Spouse", p.spouse)] if p.has_spouse else []):
        nm = _name(person, label, opts)
        age = p.assumptions.start_year - person.birth_year
        rows.append([
            nm, str(person.birth_year), f"{age}",
            f"{T.full_retirement_age(person.birth_year):.2f}",
            str(person.ss_claim_age), str(p.rmd_age(person)),
            str(person.death_age),
        ])
    lines.append(_table(
        ["Person", "Born", f"Age in {p.assumptions.start_year}",
         "SS full retirement age", "SS claim age", "First RMD age",
         "Assumed age at death"], rows))

    rule = ST.get_rule(p.state)
    rate = p.state_rate_override if p.state_rate_override >= 0 else rule.rate
    mil_exempt = rule.military_pension_exempt
    if p.state_military_exempt_override >= 0:
        mil_exempt = float(p.state_military_exempt_override)

    lines.append(f"""
**Filing status:** {'Married filing jointly' if p.has_spouse else 'Single'}
**State:** {p.state} — about {_pct(rate, 2)} on ordinary income; military
retired pay {'fully exempt' if mil_exempt >= 1 else f'{_pct(1 - mil_exempt, 0)} taxable'}.
{rule.note}
""")
    return "\n".join(lines)


def _military(p: Profile, opts: BriefingOptions, money) -> str:
    m = p.military
    gross = m.retired_pay_monthly * 12
    va = m.va_disability_monthly * 12
    crsc = m.crsc_monthly * 12
    sbp_base = (m.sbp_base_amount_monthly * 12
                if m.sbp_base_amount_monthly > 0 else gross)
    premium = sbp_base * m.sbp_premium_rate if (m.sbp_elected and not m.sbp_paid_up) else 0.0

    out = f"""## Military retirement

| Item | Value |
|---|---|
| Retirement system | {m.system} |
| Years of service | {m.years_of_service:g} |
| Retired in | {m.retirement_year} |
| Gross retired pay | {money(gross)}/yr ({money(m.retired_pay_monthly)}/mo) |
| Real COLA drift | {_pct(m.cola_real_drift, 2)} per year |
| VA disability rating | {m.va_rating}%{' — permanent and total' if m.va_permanent_and_total else ''} |
| VA compensation (tax-free) | {money(va)}/yr |
| Concurrent receipt (CRDP) | {'Yes — retired pay is NOT offset by VA' if m.crdp_applies else 'No — VA compensation offsets retired pay'} |
| CRSC (tax-free) | {money(crsc)}/yr |
| SBP elected | {'Yes' if m.sbp_elected else 'No'} |
| SBP annual premium | {money(premium)} |
| SBP survivor annuity | {money(sbp_base * T.SBP_ANNUITY_RATE)}/yr (taxable to survivor) |
| TRICARE | {'Yes' if m.has_tricare else 'No'} — {money(m.tricare_annual_cost)}/yr |
| Medicare Part B begins | age {m.medicare_part_b_age} |

### Why the military case differs from a civilian one

- **Retired pay is a permanent, fully taxable income floor with a COLA.** It
  fills the low federal brackets before any retirement account is touched, so
  RMDs later stack on top of a partly-filled bracket rather than starting in an
  empty one.
- **VA compensation is tax-free.** It funds spending without producing taxable
  income, so there is no need to draw on pre-tax accounts — which is precisely
  why the pre-tax balance compounds untouched until RMDs force it out.
- **TRICARE means no ACA premium-subsidy cliff** before 65. A civilian retiring
  early loses premium tax credits as income rises, which caps conversions hard.
  This household does not have that constraint, so its conversion window is
  structurally wider.
- **TRICARE For Life still requires Medicare Part B at 65**, so IRMAA applies in
  full. IRMAA is a cliff, not a ramp, and is assessed on income from two years
  prior — conversions at 63 raise premiums at 65.
- **The survivor loses a great deal at once:** retired pay stops (SBP replaces
  {_pct(T.SBP_ANNUITY_RATE, 0)} of the base amount), VA compensation stops, the
  smaller Social Security benefit stops, and the survivor files single, where
  brackets are roughly half as wide.
"""
    sv = p.survivorship
    if sv.model_survivor:
        out += f"""
**Survivor modelling:** first death is {sv.first_death}"""
        if sv.first_death_year:
            out += f" in {sv.first_death_year}"
        out += f""". DIC {'applies' if sv.dic_applies else 'does not apply'}"""
        if sv.dic_applies:
            out += f" at {money(sv.dic_monthly * 12)}/yr, tax-free"
        out += f""". SBP-DIC offset {'applied' if sv.sbp_dic_offset else 'not applied (repealed effective 2023)'}.\n"""
    return out


def _finances(p: Profile, opts: BriefingOptions, money) -> str:
    lines = ["## Income and accounts\n", "### Income\n"]
    rows = []
    for label, person in [("You", p.primary)] + (
            [("Spouse", p.spouse)] if p.has_spouse else []):
        nm = _name(person, label, opts)
        ss = person.ss_pia_monthly * 12 * ss_claim_factor(
            person.birth_year, person.ss_claim_age)
        rows.append([
            nm, money(person.annual_wages), str(person.work_through_year),
            money(person.ss_pia_monthly * 12), money(ss),
            str(person.birth_year + person.ss_claim_age),
        ])
    lines.append(_table(
        ["Person", "Annual wages", "Last wage year", "SS at full retirement age",
         "SS as claimed", "First SS year"], rows))

    oi = p.other_income
    extras = []
    if oi.civilian_pension_monthly:
        extras.append(f"- Civilian pension: {money(oi.civilian_pension_monthly * 12)}/yr "
                      f"from age {oi.civilian_pension_start_age}, real growth "
                      f"{_pct(oi.civilian_pension_cola_real, 2)}/yr")
    if oi.rental_net_annual:
        extras.append(f"- Net rental income: {money(oi.rental_net_annual)}/yr")
    if oi.other_taxable_annual:
        extras.append(f"- Other taxable income: {money(oi.other_taxable_annual)}/yr")
    if oi.other_taxfree_annual:
        extras.append(f"- Other tax-free income: {money(oi.other_taxfree_annual)}/yr")
    if extras:
        lines.append("\n" + "\n".join(extras))

    lines.append("\n### Accounts\n")
    rows = []
    for label, person in [("You", p.primary)] + (
            [("Spouse", p.spouse)] if p.has_spouse else []):
        nm = _name(person, label, opts)
        rows.append([nm, money(person.traditional_balance),
                     money(person.roth_balance),
                     money(person.traditional_contribution),
                     money(person.roth_contribution)])
    lines.append(_table(
        ["Person", "Traditional / pre-tax", "Roth",
         "Annual traditional contribution", "Annual Roth contribution"], rows))

    tx = p.taxable
    trad = sum(x.traditional_balance for x in p.people())
    roth = sum(x.roth_balance for x in p.people())
    total = trad + roth + tx.balance + tx.cash_balance
    lines.append(f"""
| Bucket | Balance | Share |
|---|---|---|
| Pre-tax (traditional) | {money(trad)} | {_pct(trad / total if total else 0, 0)} |
| Roth | {money(roth)} | {_pct(roth / total if total else 0, 0)} |
| Taxable brokerage | {money(tx.balance)} (basis {money(tx.cost_basis)}) | {_pct(tx.balance / total if total else 0, 0)} |
| Cash | {money(tx.cash_balance)} | {_pct(tx.cash_balance / total if total else 0, 0)} |
| **Total** | **{money(total)}** | |

Brokerage dividend yield {_pct(tx.dividend_yield, 2)}, of which
{_pct(tx.qualified_dividend_share, 0)} qualified; annual turnover
{_pct(tx.turnover_rate, 1)}.
""")
    return "\n".join(lines)


def _assumptions(p: Profile, opts: BriefingOptions, money) -> str:
    a = p.assumptions
    h = p.heirs
    tp = p.tax_policy
    return f"""## Assumptions

**These are the numbers the conclusion depends on. Challenge them.**

### Returns and inflation (real returns, above inflation)

| Assumption | Value |
|---|---|
| Traditional / pre-tax real return | {_pct(a.real_return_traditional, 2)} |
| Roth real return | {_pct(a.real_return_roth, 2)} |
| Taxable real return | {_pct(a.real_return_taxable, 2)} |
| Cash real return | {_pct(a.real_return_cash, 2)} |
| Inflation | {_pct(a.inflation, 2)} |
| Discount rate for lifetime comparisons | {_pct(a.discount_rate, 2)} |

Inflation does one job here: the Social Security taxation thresholds and the
NIIT threshold are fixed in nominal dollars and have never been indexed, so the
model deflates them each year. That is why the taxable share of Social Security
rises across the projection even with flat real income.

### Spending

| Assumption | Value |
|---|---|
| Annual spending (excl. income tax) | {money(a.annual_spending)} |
| Spending begins | {a.spending_start_year} |
| Real spending drift | {_pct(a.spending_real_drift, 2)} per year |
| Survivor spending, share of joint | {_pct(a.survivor_spending_factor, 0)} |
| Late-life care | {money(a.late_life_care_annual)}/yr from age {a.late_life_care_start_age} |
| Withdrawal order | {' → '.join(a.withdrawal_order)} |

### Heirs

| Assumption | Value |
|---|---|
| Beneficiaries | {h.n_beneficiaries} |
| Years to empty an inherited account | {h.drain_years} (SECURE Act) |
| Their federal marginal rate | {_pct(h.heir_marginal_rate, 0)} |
| Their state rate | {_pct(h.heir_state_rate, 1)} |
| Their real return | {_pct(h.heir_real_return, 2)} |

### Future federal tax law

**Scenario modelled:** {tp.scenario}
{f"Effective from {tp.change_year}." if tp.scenario != 'Current law holds' else ''}
{f"Surcharge: {tp.surcharge_points:g} percentage points on every rate." if tp.scenario == 'Across-the-board rate increase' else ''}
{f"Bracket width multiplier: {tp.bracket_width_factor:g}." if tp.bracket_width_factor != 1.0 else ''}
Real bracket drag (chained-CPI effect): {_pct(tp.real_bracket_drag, 2)} per year.
Senior deduction {'enabled' if tp.senior_deduction_enabled else 'disabled'}, expiring after {tp.senior_deduction_expiry_year}.
Social Security thresholds {'indexed' if tp.index_ss_thresholds else 'NOT indexed (current law)'}.

Note: the TCJA rate schedule was made permanent by the One Big Beautiful Bill
Act in July 2025, so there is no scheduled sunset — only ordinary political risk.
"""


def _strategy(p: Profile, opts: BriefingOptions, money) -> str:
    cp = p.conversion
    detail = ""
    if cp.strategy == ConversionPlan.STRATEGY_BRACKET:
        detail = f"Fill ordinary taxable income to the top of the **{_pct(cp.target_bracket, 0)} bracket** each year."
    elif cp.strategy == ConversionPlan.STRATEGY_IRMAA:
        detail = f"Convert up to IRMAA tier ceiling #{cp.irmaa_tier_index + 1}."
    elif cp.strategy == ConversionPlan.STRATEGY_FIXED:
        detail = f"Convert {money(cp.fixed_amount)} per year."
    elif cp.strategy == ConversionPlan.STRATEGY_PERCENT:
        detail = f"Convert {_pct(cp.percent_of_balance, 1)} of the remaining balance per year."
    elif cp.strategy == ConversionPlan.STRATEGY_TARGET:
        detail = f"Draw the pre-tax balance down to {money(cp.target_remaining_balance)} by the end of the window."

    return f"""## The conversion strategy being tested

**{cp.strategy}** — {detail}

| Setting | Value |
|---|---|
| Window | {cp.start_year} to {cp.end_year} ({cp.end_year - cp.start_year + 1} years) |
| Your age during the window | {cp.start_year - p.primary.birth_year} to {cp.end_year - p.primary.birth_year} |
| Conversion tax paid from | {'taxable savings (outside the IRA)' if cp.pay_tax_from_taxable else 'the conversion itself (withheld)'} |
| Annual cap | {money(cp.annual_cap) if cp.annual_cap else 'none'} |
| Stop converting below | {money(cp.floor_balance)} |
| Skip years with wage income | {'Yes' if cp.skip_while_working else 'No'} |

The bracket-filling solver uses a bisection search rather than a formula,
because converting raises the taxable share of Social Security, which consumes
the very headroom being filled (the "tax torpedo"). The amounts are therefore
not round numbers.
"""


def _results(p: Profile, c, opts: BriefingOptions, money) -> str:
    base, conv = c.base, c.conv
    return f"""---

## Results

| Measure | No conversions | With conversions | Difference |
|---|---|---|---|
| Lifetime federal tax | {money(base.lifetime_federal_tax)} | {money(conv.lifetime_federal_tax)} | {money(conv.lifetime_federal_tax - base.lifetime_federal_tax)} |
| Lifetime state tax | {money(base.lifetime_state_tax)} | {money(conv.lifetime_state_tax)} | {money(conv.lifetime_state_tax - base.lifetime_state_tax)} |
| Lifetime Medicare IRMAA surcharges | {money(base.lifetime_irmaa_surcharge)} | {money(conv.lifetime_irmaa_surcharge)} | {money(conv.lifetime_irmaa_surcharge - base.lifetime_irmaa_surcharge)} |
| **Lifetime total tax** | **{money(base.lifetime_total_tax)}** | **{money(conv.lifetime_total_tax)}** | **{money(-c.tax_saved)}** |
| Lifetime tax, discounted at {_pct(p.assumptions.discount_rate, 2)} | {money(base.lifetime_total_tax_discounted)} | {money(conv.lifetime_total_tax_discounted)} | {money(-c.tax_saved_discounted)} |
| Total converted | {money(0)} | {money(conv.lifetime_conversions)} | {money(conv.lifetime_conversions)} |
| Lifetime RMDs | {money(base.lifetime_rmds)} | {money(conv.lifetime_rmds)} | {money(conv.lifetime_rmds - base.lifetime_rmds)} |
| Peak marginal federal rate | {_pct(base.peak_marginal_rate, 0)} | {_pct(conv.peak_marginal_rate, 0)} | |
| Pre-tax balance at death | {money(base.ending_traditional)} | {money(conv.ending_traditional)} | {money(conv.ending_traditional - base.ending_traditional)} |
| Roth balance at death | {money(base.ending_roth)} | {money(conv.ending_roth)} | {money(conv.ending_roth - base.ending_roth)} |
| Tax paid by heirs | {money(base.heir_tax_paid)} | {money(conv.heir_tax_paid)} | {money(-c.heir_tax_saved)} |
| **After-tax value to heirs** | **{money(base.heir_value_total)}** | **{money(conv.heir_value_total)}** | **{money(c.legacy_gain)}** |

**Verdict from the model:** converting {'**wins** by ' + money(c.legacy_gain) if c.converting_wins else '**loses** by ' + money(-c.legacy_gain)}
after all taxes — the retiree's, the survivor's and the heirs'.
{f'The conversion path overtakes the no-conversion path in {c.breakeven_year}.' if c.breakeven_year else 'The conversion path never overtakes the no-conversion path.'}

Note on the discount rate: at 0% a dollar of tax decades away counts the same as
a dollar today, which flatters conversions, since conversions pay tax now to
avoid tax later. {'A non-zero discount rate is applied above.' if p.assumptions.discount_rate > 0 else '**The discount rate here is 0%. Treat the undiscounted advantage with suspicion.**'}
"""


def _findings(c, opts: BriefingOptions) -> str:
    if not getattr(c, "findings", None):
        return ""
    out = ["## What the model says is driving this\n"]
    label = {"good": "Favourable", "warn": "Caution", "bad": "Problem",
             "info": "Context"}
    for f in c.findings:
        out.append(f"**[{label.get(f.severity, 'Note')}] {f.headline}**\n")
        out.append(f"{f.detail}\n")
    return "\n".join(out)


def _year_table(p: Profile, c, opts: BriefingOptions, money) -> str:
    if opts.table_mode == "None":
        return ""
    base, conv = c.base, c.conv
    by_year_b = {r.year: r for r in base.rows}
    by_year_c = {r.year: r for r in conv.rows}

    if opts.table_mode == "Every year":
        years = sorted(by_year_b)
        note = "Every projected year."
    else:
        years = sorted(_milestone_years(p, base.rows, conv.rows))
        note = ("Years where something structural changes — wages end, Social "
                "Security starts, Medicare begins, RMDs begin, a conversion is "
                "made, a death occurs — plus a five-year sample in between.")

    rows = []
    for y in years:
        b, cc = by_year_b.get(y), by_year_c.get(y)
        if not b or not cc:
            continue
        rows.append([
            str(y), str(b.age_primary),
            "Joint" if b.filing_status == T.MFJ else "Single",
            money(b.military_retired_pay), money(b.social_security),
            money(b.rmd), money(cc.conversion),
            money(b.agi), money(cc.agi),
            _pct(b.marginal_rate, 0), _pct(cc.marginal_rate, 0),
            money(b.total_tax), money(cc.total_tax),
            money(b.traditional_balance), money(cc.traditional_balance),
        ])

    return f"""## Year by year

{note} "No conv." = the no-conversion future; "Conv." = with conversions.
All figures in real 2026 dollars.

{_table(["Year", "Age", "Filing", "Retired pay", "Social Security",
         "RMD (no conv.)", "Conversion", "AGI (no conv.)", "AGI (conv.)",
         "Marginal (no conv.)", "Marginal (conv.)", "Tax (no conv.)",
         "Tax (conv.)", "Pre-tax bal. (no conv.)", "Pre-tax bal. (conv.)"], rows)}
"""


def _scenarios(sweep, opts: BriefingOptions, money) -> str:
    if not sweep:
        return ""
    rows = [[
        s["scenario"], money(s["tax_no_convert"]), money(s["tax_convert"]),
        money(s["tax_saved"]), money(s["legacy_gain"]),
        "Convert" if s["legacy_gain"] > 0 else "Do not convert",
    ] for s in sweep]
    wins = sum(1 for s in sweep if s["legacy_gain"] > 0)
    return f"""## Sensitivity to future tax law

The same comparison re-run under different assumptions about federal rates.

{_table(["Tax scenario", "Lifetime tax (no conv.)", "Lifetime tax (conv.)",
         "Tax saved", "Extra value to heirs", "Verdict"], rows)}

Converting wins in **{wins} of {len(sweep)}** scenarios.
{'Because it wins in all of them, the decision does not depend on predicting Congress.' if wins == len(sweep) else 'Because the answer varies, the decision does depend on future tax law — size the conversion accordingly.'}
"""


def _brackets(sweep, opts: BriefingOptions, money) -> str:
    if not sweep:
        return ""
    rows = []
    for s in sweep:
        label = ("Convert nothing" if s["target_bracket"] == 0
                 else f"Fill to {_pct(s['target_bracket'], 0)}")
        rows.append([label, money(s["total_converted"]),
                     money(s["lifetime_tax"]), money(s["irmaa"]),
                     money(s["ending_traditional"]), money(s["legacy"]),
                     money(s["legacy_gain"])])
    return f"""## Which target bracket is best

Each row is a complete re-run of the projection at that target, ranked by
after-tax value delivered to heirs.

{_table(["Strategy", "Total converted", "Lifetime tax", "IRMAA surcharges",
         "Pre-tax left at death", "Value to heirs", "vs. converting nothing"],
        rows)}
"""


def _monte_carlo(mc, opts: BriefingOptions, money) -> str:
    if not mc:
        return ""
    import numpy as np
    qs = (5, 25, 50, 75, 95)
    pd_ = mc.percentiles(mc.legacy_delta, qs)
    rows = [[f"{q}th percentile", money(pd_[q])] for q in qs]
    return f"""## Monte Carlo

{mc.n_paths:,} simulated market histories. **Both futures are run on the same
random return sequence in each path**, so the difference between them is not
contaminated by sampling noise.

- Real return standard deviation: {_pct(mc.return_stdev, 1)}
- Inflation standard deviation: {_pct(mc.inflation_stdev, 1)}
- Converting leaves more after-tax value to heirs on **{_pct(mc.win_rate(), 1)}** of paths
- Converting produces lower lifetime tax on **{_pct(mc.tax_win_rate(), 1)}** of paths
- Median extra value from converting: **{money(float(np.median(mc.legacy_delta)))}**
- Paths with an unfunded spending shortfall: {_pct(mc.ruin_rate(False), 1)} without
  conversions, {_pct(mc.ruin_rate(True), 1)} with

Distribution of the paired difference (converting minus not converting):

{_table(["Percentile", "Extra after-tax value to heirs"], rows)}
"""


def _limitations() -> str:
    return """---

## Known limitations — read this before trusting the numbers

### Modelled
Federal ordinary and preferential-rate brackets; standard deduction, the
additional deduction at 65, and the senior deduction with its phase-out and
expiry; Social Security taxation via provisional income, **with the unindexed
thresholds correctly eroding in real terms**; the Social Security tax torpedo;
capital gains and qualified dividends stacked on ordinary income; NIIT; Medicare
Part B and Part D IRMAA as cliffs on a two-year lookback; RMDs on the Uniform
Lifetime Table with SECURE 2.0 ages; military retired pay with configurable real
COLA drift and the REDUX age-62 recomputation; CRDP, the VA offset when it does
not apply, and CRSC; SBP premiums, the 55% survivor annuity, and DIC; the full
survivor transition including the change to single filing; state income tax with
military-pension exemptions and age-gated retirement-income exclusions; heir
taxation under the SECURE Act ten-year rule; early-withdrawal penalties before
59½.

### NOT modelled — any of these could change the answer
- **Itemised deductions, especially the medical-expense deduction.** Large
  late-life care costs can absorb pre-tax withdrawals at a very low effective
  rate. Omitting this makes the model **overstate** the case for converting
  everything. This is the most important omission.
- **Qualified charitable distributions (QCDs).** From 70½ these satisfy RMDs
  tax-free. A charitably inclined retiree has a cheaper alternative to
  converting, and the model does not see it.
- Alternative Minimum Tax
- Net unrealised appreciation on employer stock
- Federal or state estate tax; trusts as beneficiaries
- Roth five-year rules on conversions
- Local and municipal income taxes
- State tax is a simplification: graduated-rate states are represented by a
  single effective rate, credits are approximated as exemptions
- Tax-loss harvesting, asset location, and any active management of the
  brokerage account
- Changes of residence between states
- Long-term care insurance
- The heir model assumes a single flat marginal rate for all beneficiaries
  across the whole drain period

### Structural cautions
- Returns are a **fixed real rate** in the deterministic projection. Sequence of
  returns is only addressed in the Monte Carlo section, if present.
- Both spouses' deaths are at **assumed fixed ages**. The survivor result is
  highly sensitive to these.
- Tax tables are 2026 figures and will drift out of date.
- The model optimises for after-tax value delivered to heirs. If the real goal
  is spending security, or charitable giving, or simplicity, the right answer
  may differ.
"""


def _questions(p: Profile, c) -> str:
    cp = p.conversion
    return f"""---

## Questions worth asking

1. The conclusion rests on a real return of
   {_pct(p.assumptions.real_return_traditional, 2)} and death ages of
   {p.primary.death_age}{f" and {p.spouse.death_age}" if p.has_spouse else ""}.
   How much does the answer move if returns are two points lower, or if the
   first death comes ten years earlier?
2. The discount rate is {_pct(p.assumptions.discount_rate, 2)}. What does the
   conclusion look like at a discount rate equal to the assumed real return?
3. Heirs are assumed to pay
   {_pct(p.heirs.heir_marginal_rate + p.heirs.heir_state_rate, 0)} combined
   during the ten-year drain. Is that realistic for them, and what happens at
   ten points lower?
4. The strategy converts inside {cp.start_year}–{cp.end_year}. Is that window
   right, or should it start earlier or extend further?
5. What is the case **against** converting here that this analysis does not make?
6. Which of the unmodelled items above would most change this answer, and by
   roughly how much?
7. Are there military-specific interactions — CRDP versus CRSC, SBP, DIC,
   TRICARE and IRMAA — that are being handled incorrectly?
8. Is there a simpler strategy that captures most of the benefit — for example
   changing the withdrawal order, or making Roth rather than traditional
   contributions while still working?
"""


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

def build_briefing(p: Profile, comparison, opts: BriefingOptions | None = None,
                   scenario_sweep=None, bracket_sweep=None,
                   monte_carlo=None) -> str:
    opts = opts or BriefingOptions()
    money = _mk_money(opts)

    parts = [
        _header(p, opts),
        _household(p, opts, money),
        _military(p, opts, money),
        _finances(p, opts, money),
        _assumptions(p, opts, money),
        _strategy(p, opts, money),
    ]

    if comparison is not None:
        parts.append(_results(p, comparison, opts, money))
        if opts.include_findings:
            parts.append(_findings(comparison, opts))
        parts.append(_year_table(p, comparison, opts, money))

    if opts.include_scenarios:
        parts.append(_brackets(bracket_sweep, opts, money))
        parts.append(_scenarios(scenario_sweep, opts, money))
    if opts.include_monte_carlo:
        parts.append(_monte_carlo(monte_carlo, opts, money))

    parts.append(_limitations())

    if opts.include_questions and comparison is not None:
        parts.append(_questions(p, comparison))

    if opts.include_json:
        parts.append("---\n\n## Appendix — the full plan as JSON\n\n"
                     "Every input, exactly as the model received it.\n\n"
                     "```json\n" + p.to_json() + "\n```\n")

    parts.append("\n---\n\n*Generated by the Military Roth Conversion Planner. "
                 "An estimator, not tax advice.*\n")

    return "\n\n".join(x for x in parts if x and x.strip())


def briefing_filename(p: Profile) -> str:
    import re
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", p.profile_name).strip("-").lower()
    return f"roth-briefing-{safe or 'plan'}-{date.today().isoformat()}.md"
