"""
Intake for the Retired Military funnel.

`ARCHITECTURE.md` §2 puts this funnel on the far end of the axis: the future is
largely locked. The income streams are already running -- retired pay, VA
compensation, Social Security to come, perhaps a spouse's SSDI -- and most of
that money is inflation-linked while the VA slice is untaxed. That is the
structural advantage a civilian retirement tool cannot see, and it is exactly
what the scorecard's income-floor component exists to show (§3). What is left
to decide is SEQUENCING: when to claim, how much to convert, which account to
draw first.

So these questions are not here to size a portfolio. They are here to let the
app price three things the owner of a plan like this usually gets wrong:

  1. THE PENSION'S COLA RULE, which is a fact about the retirement system and
     nothing else. Under CSB/REDUX the pension pays CPI minus one point and is
     recomputed at 62 -- about a percent of real value lost every year until
     then. `m.retirement_system` is a DERIVED PROPERTY off the DIEMS date
     (`engine/profile.py`), not a settable field, so the question asked here is
     the DIEMS date and the two elections that modify it. Asking for the system
     directly would name an attribute that cannot be written to.

  2. CRDP AGAINST CRSC, which is a real annual election whose default can be
     the wrong one. `engine/benefits/concurrent_receipt.py` is blunt about why:
     DFAS compares them on GROSS, and CRSC is tax-free while CRDP is not, so
     the larger gross figure is routinely the smaller cheque. Pricing it needs
     years of service and the VA rating, which is why both are asked here.
     WHETHER CRDP APPLIES IS NOT ASKED: the same module says it is automatic
     at twenty years and a 50% rating, so the app works it out. CRSC is asked,
     because it is the one you have to apply for.

  3. THE PART B DECISION AT 65. TRICARE For Life is a wraparound and does not
     exist without Part B, and the premium is set by MAGI from two years
     earlier -- so a Roth conversion at 63 sets the premium at 65
     (`engine/benefits/healthcare.py`). A retiree who believes their RMD
     exposure is "almost nothing" because the VA money is untaxed has usually
     not looked at the traditional TSP balance the common set asks for, and
     this is where that bill lands.

R1 GOVERNS THIS FILE. Every question carries a one-line WHY IT IS ASKED, and
that comment is the standing defence against the set growing back. What this
funnel works out rather than asks:

    CRDP            twenty years and a 50% rating: it is automatic
    Part B at 65    TRICARE For Life does not exist without it
    children        the household's dependants (common set)
    where you live  your legal residence, once you are out of uniform

and what it stops asking once the answer cannot change anything:

    TRICARE plan    not asked from 65, where For Life takes over and
                    `healthcare._phase_at()` stops reading the field

The one pay figure it does NOT work out is retired pay itself. See the comment
on that question: a high-3 needs the pay tables in force in the three years
before retirement and this app ships one year of them.

WHAT IS DELIBERATELY NOT HERE. The common set in `engine/funnel.py` already
asks birth year, sex, spouse, dependents, residence, civilian wages, every
balance, the spending split and the target age; none of it is repeated. Grade,
date of rank, duty ZIP and the TSP election belong to someone still serving. The COLA
assumption (`assumptions.cola_full`) is not asked either: it is a consequence
of the retirement system resolved from the DIEMS date below, and
`engine/assumptions.py::sanity()` already cross-checks the two and says so.

ONE FIELD THIS SET CANNOT ASK FOR: the SBP BASE AMOUNT. `ARCHITECTURE.md` §5
lists "SBP elected and level", and the projection reads a base amount
(`engine/retirement/projection.py`, via `roth_profile.MilitaryRetirement`) --
but `ServiceMember` carries only `sbp_elected`, with no base-amount field to
write into, and `engine/profile.py` is not ours to change. A question naming an
attribute that does not exist fails `validate()`, so the election is asked and
the level is not; the help text says which base the app is therefore assuming.

Contract: `docs/FUNNEL_CONTRACT.md`. A module-level `QUESTIONS` tuple, every
key prefixed `ret_`, every question carrying `funnels=(FUNNEL_RETIRED,)`. No
Streamlit, no `ui.panel`, no `engine.intake` import.
"""

from __future__ import annotations

from engine.benefits import concurrent_receipt as CR
from engine.benefits import healthcare as HC
from engine.funnel import (Question, Derived, FUNNEL_RETIRED, KIND_CHOICE,
                           KIND_INTEGER, KIND_MONEY, KIND_NUMBER, KIND_TEXT,
                           KIND_TOGGLE, GROUP_REVIEW, RANK_REVIEW)
from engine.profile import DIEMS_BRS_START, RETIRED, Household

# --------------------------------------------------------------------------
# Groups
# --------------------------------------------------------------------------
# These are new cards, not additions to the common ones, so they sort after
# every GROUP_ORDER group. Among themselves the order is declared in
# `group_rank` and repeated on every question of the card: pay, then what the
# VA pays, then what healthcare costs.
#
# That order used to ride on the card titles, because card order fell back to
# the title alphabetically. It does not any more -- retitle a card freely and
# move it by changing its rank.
GROUP_PAY = "Retired pay and SBP"
GROUP_VA = "VA compensation and concurrent receipt"
GROUP_HEALTH = "Your healthcare and Medicare"

RANK_PAY = 10
RANK_VA = 20
RANK_HEALTH = 30

# --------------------------------------------------------------------------
# The TRICARE menu
# --------------------------------------------------------------------------
# `HC.plans_for()` takes a COMPONENT, because offering somebody a plan they
# cannot buy is how a page produces a confident wrong answer -- Reserve Select
# is sold to the Selected Reserve and to nobody else. `Question.options` is
# fixed when this module is imported, though, so it cannot consult a household.
#
# THE CHOICE MADE HERE: resolve the menu once, for RETIRED. It is not a
# shortcut, it is what the funnel guarantees. `set_funnel(h, FUNNEL_RETIRED)`
# sets `member.component = RETIRED` (FUNNEL_CONTRACT §2), and a plan that
# reaches this funnel by inference instead did so from a retiree component,
# retired pay on the plan, or twenty years and no component -- never from
# Guard or Reserve, which infer as SERVING unconditionally. So every household
# that sees these questions is a retiree, and `plans_for(RETIRED)` is the menu
# they can actually hold: Prime, Select, For Life.
#
# The alternative -- a `format_func` or a `when` that varies the list per
# household -- cannot work: the schema has no hook for household-dependent
# options, and inventing one would mean changing the renderer. If a component
# ever reaches this funnel that Reserve Select applies to, the fix is in
# `plans_for`, in one place, and this line follows it.
TRICARE_PLANS: tuple[str, ...] = tuple(HC.plans_for(RETIRED))


# --------------------------------------------------------------------------
# Predicates. Named module-level functions, pure, per FUNNEL_CONTRACT §5.
# --------------------------------------------------------------------------

def diems_predates_brs(h: Household) -> bool:
    """
    True when the member joined before 1 Jan 2018 and the two elections apply.

    An unparseable or empty DIEMS date resolves to None and hides both, which
    is right: neither question means anything until the date is entered.
    """
    d = h.member.diems
    return d is not None and d < DIEMS_BRS_START


def is_va_rated(h: Household) -> bool:
    """True when there is a VA rating to ask follow-up questions about."""
    return int(h.member.va_rating or 0) > 0


def crdp_eligible(h: Household) -> bool:
    """
    Both statutory CRDP conditions, read from `concurrent_receipt`.

    Twenty years of service and a 50% rating. Below either one the toggle is
    not a choice the member has, and showing it invites them to assert a
    benefit they will not receive -- so it stays hidden and page 9 explains
    why. CRSC has no length-of-service floor and is gated on the rating alone.
    """
    m = h.member
    return (float(m.years_of_service or 0.0) >= CR.CRDP_MIN_YEARS
            and int(m.va_rating or 0) >= CR.CRDP_MIN_RATING)


def under_medicare_age(h: Household) -> bool:
    """
    True while the Prime-or-Select choice is still a choice.

    From 65 TRICARE For Life takes over and the stored plan stops being read:
    `healthcare._phase_at()` returns the For Life phase at Medicare age for a
    retiree whatever `tricare_plan` says. Asking after that is asking a
    question whose answer changes no number.
    """
    return h.member.age() < HC.MEDICARE_AGE


# --------------------------------------------------------------------------
# Derivations. Pure functions of the Household, like the predicates.
# --------------------------------------------------------------------------

def derive_crdp(h: Household) -> bool:
    """
    CRDP applies when both statutory conditions are met, because it is
    automatic.

    `concurrent_receipt.eligibility()` says so in its own words -- "It is
    automatic — no application is required" -- so there is no election to
    record and no second opinion to have. Twenty years of service and a 50%
    rating are both already on the plan.
    """
    return crdp_eligible(h)


def derive_part_b(h: Household) -> bool:
    """
    Part B at 65, because TRICARE For Life does not exist without it.

    Declining leaves a retiree with no coverage from 65 and a 10%-a-year
    late-enrolment penalty, so the app assumes the normal answer rather than
    asking for it. The review card is where the rare retiree who is covered by
    an employer group plan past 65 says so.
    """
    return True


# --------------------------------------------------------------------------
# The set
# --------------------------------------------------------------------------

QUESTIONS: tuple[Question, ...] = (
    # -- Retired pay and SBP ----------------------------------------------
    Question(key="ret_retired_pay",
             label="What is your gross retired pay, per month?",
             # ASKED, and the one pay figure the app does NOT work out. A
             # pension is a multiplier against a HIGH-3 AVERAGE of the basic
             # pay tables in force in the three years before retirement, and
             # `data/pay/` ships one year — the current one. Computing a 2005
             # retiree's high-3 from the 2026 table would overstate it by every
             # pay raise since, on the largest figure on the plan. The Retiree
             # Account Statement is the only honest source.
             kind=KIND_MONEY, path="member", attr="retired_pay_monthly",
             group=GROUP_PAY, group_rank=RANK_PAY, order=10, funnels=(FUNNEL_RETIRED,),
             step=100.0, min_value=0.0,
             help="Before the SBP premium, before any VA offset and before "
                  "tax — the gross line on your Retiree Account Statement. It "
                  "is taxable as ordinary income federally, and several states "
                  "do not tax it at all. This is the largest piece of the "
                  "inflation-linked income floor everything else is measured "
                  "against."),
    Question(key="ret_years_of_service",
             label="How many years did you serve?",
             # ASKED: there is no retirement date on this funnel to subtract
             # the DIEMS date from — a retiree of ten years standing would
             # otherwise be credited with ten more years of service. It sets
             # the multiplier and it is one of the two CRDP conditions.
             kind=KIND_NUMBER, path="member", attr="years_of_service",
             group=GROUP_PAY, group_rank=RANK_PAY, order=20, funnels=(FUNNEL_RETIRED,),
             min_value=0.0, max_value=45.0, step=0.5,
             help="Creditable service at retirement. It sets the pension "
                  "multiplier, it is one of the two CRDP conditions — twenty "
                  "years and a 50% rating — and it drives the Social Security "
                  "earnings history, because military pay counted in full."),
    Question(key="ret_diems",
             label="What is your DIEMS date, as YYYY-MM-DD?",
             # ASKED: a date on a DD-214, and the only thing that decides the
             # retirement system and therefore the COLA rule.
             kind=KIND_TEXT, path="member", attr="diems_date",
             group=GROUP_PAY, group_rank=RANK_PAY, order=30, funnels=(FUNNEL_RETIRED,),
             placeholder="1998-06-15",
             help="Date of Initial Entry to Military Service — the day you "
                  "first swore in, including at an academy or in contracted "
                  "ROTC status. It is on your DD-214. The app asks for this "
                  "rather than for the name of your retirement system because "
                  "the date decides the system and nothing else does, and the "
                  "system decides your COLA: Final Pay and High-3 track CPI in "
                  "full, CSB/REDUX pays CPI minus one point until a one-time "
                  "recompute at 62 — about a percent of real pension value "
                  "lost every year in between."),
    Question(key="ret_csb_redux",
             label="Did you take the CSB/REDUX bonus at 15 years?",
             # ASKED: an irreversible election recorded nowhere on the plan,
             # and the single answer that most changes what a pension is worth.
             kind=KIND_TOGGLE, path="member", attr="took_csb_redux",
             group=GROUP_PAY, group_rank=RANK_PAY, order=40, funnels=(FUNNEL_RETIRED,),
             when=diems_predates_brs,
             help="The $30,000 bonus, in exchange for a reduced multiplier and "
                  "the reduced COLA above. No new elections have been possible "
                  "since 2017, so this is a historical fact to record, not a "
                  "decision to make — but it is the single answer that most "
                  "changes what your pension is worth."),
    Question(key="ret_brs_optin",
             label="Did you opt into BRS in the 2018 window?",
             # ASKED: the DIEMS date says the window was open, not what you
             # did in it.
             kind=KIND_TOGGLE, path="member", attr="opted_into_brs",
             group=GROUP_PAY, group_rank=RANK_PAY, order=50, funnels=(FUNNEL_RETIRED,),
             when=diems_predates_brs,
             help="Only asked because you joined before 2018. Almost every "
                  "twenty-year retiree drawing pay today was too senior to opt "
                  "in; a medical retiree may not have been. It lowers the "
                  "multiplier and would have added a TSP match."),
    Question(key="ret_sbp_elected",
             label="Did you elect SBP?",
             # ASKED: an election made once, at retirement, and reversible only
             # in a narrow window. Nothing on the plan records it and the
             # survivor component is meaningless without it.
             kind=KIND_TOGGLE, path="member", attr="sbp_elected",
             group=GROUP_PAY, group_rank=RANK_PAY, order=60, funnels=(FUNNEL_RETIRED,),
             help="The Survivor Benefit Plan: a premium of 6.5% of the base "
                  "amount out of your retired pay, for a survivor annuity of "
                  "55% of it, indexed for life and no longer offset by VA "
                  "dependency compensation. The app assumes you elected FULL "
                  "retired pay as the base amount, which is the usual "
                  "election; if you elected a reduced base, read the survivor "
                  "figures as an upper bound."),

    # -- VA compensation and concurrent receipt ---------------------------
    Question(key="ret_va_monthly",
             label="What is your VA compensation, per month?",
             # ASKED: there is no VA compensation rate schedule in this tree,
             # and the award letter already has dependants and any special
             # monthly compensation folded in, which a rating alone never would.
             kind=KIND_MONEY, path="member", attr="va_disability_monthly",
             group=GROUP_VA, group_rank=RANK_VA, order=20, funnels=(FUNNEL_RETIRED,),
             when=is_va_rated, step=50.0, min_value=0.0,
             help="Tax-free at federal and state level, and indexed to the "
                  "same COLA as Social Security. Because it never appears on a "
                  "return it does not raise your taxable income, your Medicare "
                  "IRMAA tier or the taxable share of your Social Security — "
                  "which is what leaves room to convert to Roth. It is also "
                  "the part of the income floor that a civilian planning tool "
                  "has no field for."),
    Question(key="ret_va_rating",
             label="What is your VA rating, as a percentage?",
             # ASKED: a decision the VA made. It sets the healthcare priority
             # group and, with twenty years, whether CRDP applies — which the
             # app then works out rather than asking.
             kind=KIND_INTEGER, path="member", attr="va_rating",
             group=GROUP_VA, group_rank=RANK_VA, order=10, funnels=(FUNNEL_RETIRED,),
             min_value=0, max_value=100, step=10,
             help="The combined rating on your decision letter. It sets your "
                  "VA healthcare priority group, and at 50% or more with "
                  "twenty years of service it is what makes concurrent receipt "
                  "automatic."),
    Question(key="ret_va_permanent_total",
             label="Is your rating permanent and total?",
             # ASKED: whether re-examinations have stopped is a finding on the
             # letter, not a consequence of the percentage.
             kind=KIND_TOGGLE, path="member", attr="va_rating_permanent_total",
             group=GROUP_VA, group_rank=RANK_VA, order=30, funnels=(FUNNEL_RETIRED,),
             when=is_va_rated,
             help="P&T means no future re-examination is scheduled, so the "
                  "app can treat the compensation as a lifetime indexed "
                  "stream rather than an income that might be re-rated. It "
                  "also opens Chapter 35 education benefits for your "
                  "dependents and CHAMPVA for a family without TRICARE."),
    Question(key="ret_crsc",
             label="What CRSC do you receive, per month?",
             # ASKED: unlike CRDP, CRSC is NOT automatic — you apply to your
             # branch, and the amount is theirs to compute from which
             # disabilities they find combat-related. Nothing here can predict
             # either the award or the figure.
             kind=KIND_MONEY, path="member", attr="crsc_monthly",
             group=GROUP_VA, group_rank=RANK_VA, order=50, funnels=(FUNNEL_RETIRED,),
             when=is_va_rated, step=50.0, min_value=0.0,
             help="Combat-Related Special Compensation is tax-free, it is an "
                  "ALTERNATIVE to CRDP rather than an addition, and it is not "
                  "automatic — you apply to your branch of service, not to the "
                  "VA and not to DFAS. There is no twenty-year floor, so a "
                  "medical retiree can hold it. Enter it even if you are "
                  "currently taking CRDP: DFAS compares the two on gross, "
                  "which ignores the tax, and the app compares them after tax."),

    # -- Your healthcare and Medicare -------------------------------------
    Question(key="ret_tricare_plan",
             label="Which TRICARE plan are you on?",
             # ASKED, and only under 65: Prime against Select is a real
             # election with a real fee, and nothing on the plan implies which
             # one you made. From 65 it is not asked at all — For Life takes
             # over and `healthcare._phase_at()` stops reading this field.
             kind=KIND_CHOICE, path="healthcare", attr="tricare_plan",
             group=GROUP_HEALTH, group_rank=RANK_HEALTH, order=10, funnels=(FUNNEL_RETIRED,),
             when=under_medicare_age, options=TRICARE_PLANS,
             help="Prime is the HMO — a primary care manager, referrals, "
                  "near-zero copays, and you must live in a Prime service "
                  "area. Select is the PPO — any authorised provider, with "
                  "copays and a higher enrollment fee. For Life takes over at "
                  "65 and costs nothing itself. Either way there is no "
                  "pre-65 coverage gap, so the subsidy cliff that caps a "
                  "civilian early retiree's Roth conversions does not apply "
                  "to you."),
    # ======================================================================
    # The figures we worked out. NOT ASKED — it renders on the review card at
    # the end of intake with what the app assumed, and why.
    # ======================================================================
    Question(key="ret_part_b",
             label="Will you take Medicare Part B when you are eligible?",
             kind=KIND_TOGGLE, path="healthcare", attr="part_b_when_eligible",
             group=GROUP_REVIEW, group_rank=RANK_REVIEW, order=10,
             funnels=(FUNNEL_RETIRED,),
             derive=derive_part_b, fills_in=True,
             derived_from="TRICARE For Life needing it, which makes taking it "
                          "the normal answer",
             help="TRICARE For Life is a wraparound to Medicare and exists "
                  "only for people enrolled in Part A and Part B. Decline Part "
                  "B and you have no coverage from 65, and a late-enrollment "
                  "penalty of 10% a year if you change your mind. Taking it is "
                  "the normal answer — and the reason conversions have a "
                  "deadline: the premium is set by your income from two years "
                  "earlier, in steps, so what you convert at 63 sets what you "
                  "pay at 65."),
)


# --------------------------------------------------------------------------
# Settled facts: worked out, written into the plan, never a widget
# --------------------------------------------------------------------------

DERIVED: tuple[Derived, ...] = (
    Derived(key="ret_d_crdp", label="Concurrent receipt (CRDP)",
            path="member", attr="crdp_applies", compute=derive_crdp,
            because="twenty years of service and a rating of 50 percent or "
                    "more make it automatic — there is nothing to apply for",
            funnels=(FUNNEL_RETIRED,)),
)
