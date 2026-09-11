"""
The Veteran funnel: served, left, no pension and no TRICARE.

THE DEFINING FACT, and the one that decides every question below: a veteran who
did not retire from the military has NO RETIRED PAY and NO TRICARE.
`engine/benefits/healthcare.py` says it in one line -- "Without a military
retirement there is no TRICARE" -- and it is true at any price and at any age.
So nothing here asks about retired pay, SBP, CRDP or CRSC. Those exist only as
elections against a pension, and asking a veteran about them implies they have
one.

What is left is closest to a civilian problem carrying military assets, which
`docs/ARCHITECTURE.md` §2 calls the case this app has historically said least
about. The assets are real and they are unusual:

  * VA COMPENSATION is tax-free, indexed to the same COLA as Social Security,
    and for many veterans it is the ONLY inflation-linked income they will ever
    have. It also drives two things nobody connects to it -- the VA loan
    funding-fee waiver at a 10% rating, and the state property-tax exemption at
    100% permanent and total.
  * THE SOCIAL SECURITY RECORD is the other half. Military basic pay has been
    fully covered by FICA since 1957, so years served are in the record at
    their full basic-pay value, and years before 2002 earned extra credits on
    top. `engine/income/social_security.py::estimate_pia_from_career` rebuilds
    that record -- which is why this funnel asks when service started, how long
    it ran and what grade it ended at, and not merely "how many years".
  * SGLI ENDED AT SEPARATION. The VGLI-versus-term decision is squarely this
    person's and it is the one on a deadline: guaranteed acceptance for
    `VGLI_GUARANTEED_DAYS` days, proof of good health to
    `VGLI_FINAL_DEADLINE_DAYS`, and then gone.
    `engine/benefits/life_insurance.py` prices both sides of it.

Contract: `docs/FUNNEL_CONTRACT.md`. Every key here is prefixed `vet_`, every
question carries `funnels=(FUNNEL_VETERAN,)`, and the whole registration is the
module-level `QUESTIONS` tuple at the bottom. This module imports from
`engine.funnel` directly -- never from `engine.intake`, which imports it -- and
never from `streamlit` or `ui.panel`.

NOT ASKED HERE, and deliberately: anything the common set in `engine/funnel.py`
already asks (birth year, spouse, dependents, residence, balances, spending,
target retirement age), and anything that only exists against retired pay.

NOT ASKED HERE, for want of somewhere to put the answer: months of Post-9/11
GI Bill entitlement remaining, and a civilian employer retirement plan and its
match. `engine/profile.py` carries no field for either -- `SpouseIncome` has
`employer_match_pct` but that models the SPOUSE's interrupted career, not the
veteran's own job -- and `validate()` rejects an `attr` that does not resolve.
Both want a field on `ServiceMember` before they can be asked, and that file
belongs to nobody in this pass.
"""

from __future__ import annotations

from engine.benefits import life_insurance as LI
from engine.funnel import (Question, FUNNEL_VETERAN, KIND_CHOICE, KIND_MONEY,
                           KIND_NUMBER, KIND_TEXT, KIND_TOGGLE)
from engine.pay import grades as G
from engine.profile import Household

# --------------------------------------------------------------------------
# Cards
# --------------------------------------------------------------------------
# Three, and none of them reuses a common group: a veteran's questions do not
# belong on the same card as everybody's. They sort after the common ones,
# which is the right place for them -- the common set establishes who the
# household is before this asks what the service left behind.
#
# Among themselves they run in the order the story runs: what service left you,
# then the VA, then the civilian life it all has to pay for. That order is
# declared in `group_rank` and repeated on every question of the card.
#
# It used to be smuggled through the card titles, because card order fell back
# to the title alphabetically -- and this module got away with it only by
# accident: "Your VA benefits" sorted above "Your civilian life" because an
# uppercase V sorts below a lowercase c. Capitalising one word would have
# reordered the page. The titles are now free prose.

GROUP_SEPARATION = "Leaving the service"
GROUP_VA = "Your VA benefits"
GROUP_CIVILIAN = "Your civilian life"

RANK_SEPARATION = 10
RANK_VA = 20
RANK_CIVILIAN = 30

#: VA disability ratings are awarded in ten-point steps. A free integer box
#: invites a 37% that no award letter has ever carried, so this is a menu.
VA_RATINGS: tuple[int, ...] = tuple(range(0, 101, 10))

#: Below this, "permanent and total" cannot arise and the question is noise.
#: Total means 100% schedular OR individual unemployability, and TDIU needs one
#: condition at 60% or a combined 70%, so 50 is under every route to it. It is
#: also where `healthcare.va_priority_group()` starts caring about the answer.
VA_PERMANENT_TOTAL_FLOOR = 50


# --------------------------------------------------------------------------
# Predicates. Named functions, not lambdas, so a failure names something.
# --------------------------------------------------------------------------

def has_va_rating(h: Household) -> bool:
    """True once there is a service-connected rating to be paid against."""
    return int(getattr(h.member, "va_rating", 0) or 0) > 0


def may_be_permanent_and_total(h: Household) -> bool:
    """True where a permanent-and-total finding is even possible."""
    return int(getattr(h.member, "va_rating", 0) or 0) >= VA_PERMANENT_TOTAL_FLOOR


def _as_percent(value) -> str:
    return f"{int(value)}%"


# --------------------------------------------------------------------------
# The set
# --------------------------------------------------------------------------

QUESTIONS: tuple[Question, ...] = (

    # -- Leaving the service ----------------------------------------------
    # Entry, length and final grade are the three inputs
    # `estimate_pia_from_career()` rebuilds a covered-earnings record from, so
    # they sit together and they sit first.
    Question(key="vet_service_entry",
             label="When did you first enter the service?",
             kind=KIND_TEXT, path="member", attr="diems_date",
             group=GROUP_SEPARATION, group_rank=RANK_SEPARATION, order=10, funnels=(FUNNEL_VETERAN,),
             placeholder="2003-08-11",
             help="Your DIEMS date, off your DD-214 or your last leave and "
                  "earnings statement, written as year-month-day. It does not "
                  "give you a pension — leaving short of twenty years means "
                  "there is no retirement system to resolve — but it is where "
                  "your Social Security earnings record starts, and a year "
                  "out is a year of basic pay missing from the estimate."),
    Question(key="vet_years_served",
             label="How many years did you serve?",
             kind=KIND_NUMBER, path="member", attr="years_of_service",
             group=GROUP_SEPARATION, group_rank=RANK_SEPARATION, order=20, funnels=(FUNNEL_VETERAN,),
             min_value=0.0, max_value=40.0, step=0.5, fmt="%.1f",
             help="Total creditable service, Guard and Reserve time included. "
                  "Military basic pay has carried Social Security tax since "
                  "1957, so every one of these years is in your earnings "
                  "record at its full basic-pay value, and active duty before "
                  "2002 earned extra credits on top of it."),
    Question(key="vet_grade_at_separation",
             label="What pay grade did you hold when you left?",
             kind=KIND_CHOICE, path="member", attr="grade",
             group=GROUP_SEPARATION, group_rank=RANK_SEPARATION, order=30, funnels=(FUNNEL_VETERAN,),
             options=tuple(G.GRADE_LABELS),
             help="Your grade at separation, not the one you are proudest of. "
                  "It is what the earnings estimate rebuilds your basic pay "
                  "from, year by year, back to the year you entered. Nothing "
                  "else reads it once you are out."),

    Question(key="vet_separation_date",
             label="When did you leave the service?",
             kind=KIND_TEXT, path="member", attr="planned_separation_date",
             group=GROUP_SEPARATION, group_rank=RANK_SEPARATION, order=40, funnels=(FUNNEL_VETERAN,),
             placeholder="2019-06-30",
             help=f"The separation date on your DD-214, written as "
                  f"year-month-day. Everything with a deadline runs off it: "
                  f"SGLI ran {LI.SGLI_FREE_DAYS_AFTER_SEPARATION} days past "
                  f"it for free, VGLI's guaranteed acceptance lasts "
                  f"{LI.VGLI_GUARANTEED_DAYS} days, and the final door closes "
                  f"at {LI.VGLI_FINAL_DEADLINE_DAYS} days."),
    Question(key="vet_life_cover",
             label="How much life insurance do you carry now?",
             kind=KIND_MONEY, path="member", attr="sgli_coverage",
             group=GROUP_SEPARATION, group_rank=RANK_SEPARATION, order=50, funnels=(FUNNEL_VETERAN,),
             step=50_000.0, min_value=0.0,
             help="SGLI ended when you separated, so whatever you hold now is "
                  "VGLI, a commercial term policy, or nothing. VGLI is priced "
                  "in five-year age bands and the premium climbs hard exactly "
                  "when a fixed income is least able to absorb it; level term "
                  "is usually a fraction of it for anyone who can pass "
                  "underwriting, and VGLI is the right answer for anyone who "
                  "cannot. Separation & Insurance prices the two against your "
                  "age."),

    # -- Your VA benefits --------------------------------------------------
    Question(key="vet_va_rating",
             label="What is your VA disability rating?",
             kind=KIND_CHOICE, path="member", attr="va_rating",
             group=GROUP_VA, group_rank=RANK_VA, order=10, funnels=(FUNNEL_VETERAN,),
             options=VA_RATINGS, format_func=_as_percent,
             help="The combined rating on your award letter, not the sum of "
                  "the individual ones. Ten percent is the whole threshold "
                  "for the VA loan funding fee: at or above it the fee is "
                  "waived outright, which is worth five figures on an "
                  "ordinary loan and is left at the lender every day. Fifty "
                  "percent puts you in VA healthcare Priority Group 1."),
    Question(key="vet_va_monthly",
             label="What does the VA pay you each month?",
             kind=KIND_MONEY, path="member", attr="va_disability_monthly",
             group=GROUP_VA, group_rank=RANK_VA, order=20, funnels=(FUNNEL_VETERAN,),
             when=has_va_rating, step=50.0, min_value=0.0,
             help="Take it from your latest award letter rather than the rate "
                  "table, so dependents and any special monthly compensation "
                  "are already in the figure. It is untaxed and it rises with "
                  "the same COLA as Social Security, which makes it the most "
                  "valuable income on this plan: with no military retirement "
                  "behind you it may be the only inflation-linked income you "
                  "have."),
    Question(key="vet_va_permanent_total",
             label="Is your rating permanent and total?",
             kind=KIND_TOGGLE, path="member", attr="va_rating_permanent_total",
             group=GROUP_VA, group_rank=RANK_VA, order=30, funnels=(FUNNEL_VETERAN,),
             when=may_be_permanent_and_total,
             help="Total means a hundred percent, whether schedular or by "
                  "individual unemployability. Permanent means the VA does "
                  "not expect it to improve and has stopped scheduling "
                  "re-examinations. Both together are the line most states "
                  "draw for a full property-tax exemption on your home, and "
                  "they are what opens CHAMPVA to a family that has no "
                  "TRICARE to fall back on."),

    # -- Your civilian life ------------------------------------------------
    Question(key="vet_civilian_wages",
             label="What do you earn in your civilian job, per year?",
             kind=KIND_MONEY, path="member", attr="civilian_wages_annual",
             group=GROUP_CIVILIAN, group_rank=RANK_CIVILIAN, order=10, funnels=(FUNNEL_VETERAN,),
             step=1_000.0, min_value=0.0,
             help="Gross wages, before tax and before anything you divert "
                  "into a retirement plan. These years and your service years "
                  "are one earnings record as far as Social Security is "
                  "concerned, and the civilian years are usually the higher "
                  "of the two — which is why leaving early costs a pension "
                  "but not, on its own, a benefit."),
    Question(key="vet_health_cost",
             label="What does your health cover cost you in a year?",
             kind=KIND_MONEY, path="healthcare", attr="out_of_pocket_annual",
             group=GROUP_CIVILIAN, group_rank=RANK_CIVILIAN, order=20, funnels=(FUNNEL_VETERAN,),
             step=500.0, min_value=0.0,
             help="Premiums, deductibles and what you actually spend, for "
                  "everyone on the plan. Without a military retirement there "
                  "is no TRICARE at any price, so this is a civilian cost for "
                  "the rest of your life and the model will not guess it well "
                  "— left blank it falls back to an estimate of a worker's "
                  "share of an employer plan. VA care covers you for "
                  "service-connected conditions. It does not cover your "
                  "family."),
)
