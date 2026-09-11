"""
The Currently Serving question set.

`docs/ARCHITECTURE.md` §2: this funnel exists because for someone in uniform
almost none of the future is settled yet -- stay to 20 or leave at 12, take the
BRS lump sum or not, deploy, transfer the GI Bill, pick a separation date. The
questions here are the facts those decisions are computed from, and nothing
else: the common set in `engine/funnel.py` already asks birth year, sex,
spouse, dependents, residence, balances, spending and target retirement age,
and none of that is repeated here.

R1 GOVERNS THIS FILE. "A question earns its place only if the answer cannot be
derived. The test is not 'is this useful?' -- it is 'can the app work it
out?'" Every question below carries a one-line WHY IT IS ASKED, and that
comment is the standing defence against the set growing back. If you are
adding a question here and cannot write that line, the app should be working
the answer out instead.

PAUL, ON PAY, and it decides three of the cards below: "Base pay, BAS, and BAH
is a known quantity. Ask about special pays, and confirm the gross and net pay
amounts, as they may be affected by deduction amounts or something like a
garnishment."

So basic pay, BAS and BAH are not asked in any form -- not as questions, and
not as override fields sitting blank in the flow either. They are computed and
shown back on the confirmation step, where the member confirms the two figures
a deduction actually moves. `engine/intake/pay_check.py` does that arithmetic;
`statement()` and `findings()` at the bottom of this file hand it to the page.

What this funnel works out rather than asks:

    basic pay, BAS, BAH     grade, longevity and duty ZIP. Known quantities.
    years of service        DIEMS date to today
    date of rank            two years in grade, the fallback `time_in_grade()`
                            already uses
    SGLI cover              the maximum: every member is enrolled at it
    dependants for pay      a spouse or dependants on the household
    hostile fire pay        being in a designated combat zone
    children                the household's dependants (common set)

The pay packet, years of service, date of rank, SGLI and the gross and net are
on the review card at the end of intake -- they are figures, and a figure the
app got wrong has to be correctable. The last three are settled: there is no
second opinion to have, and a toggle that flips back on the next render is
worse than no toggle. See `engine/funnel.py`, "Facts the app works out".

What it still asks about pay: SPECIAL PAYS AND BONUSES. Flight pay, sea pay,
hazardous duty, language pay, a re-enlistment bonus -- each is an assignment or
a contract, not a consequence of a pay grade, and no table produces one.

THE DIEMS DATE IS ASKED FIRST AND IT IS ASKED ALONE-ISH ON PURPOSE. It resolves
the retirement system (`ServiceMember.retirement_system`), the retirement
system decides whether a TSP match exists at all (`has_tsp_match`), and the
match reorders the entire financial priority waterfall. Nothing else in the
app decides it, and a wrong DIEMS date makes every downstream recommendation
wrong while looking perfectly reasonable. `HANDOFF.md` calls it the most
load-bearing field in the app; it gets the first card and help text that says
what it is, where to find it, and what it is not. It now also decides how long
you have served, which is one more reason it is first.

Two things that are NOT asked here, deliberately:

  * Component and branch. `set_funnel()` already guarantees the component is
    Active, Guard or Reserve for this funnel, and branch changes no number in
    any projection -- it changes a rank title. The profile page still offers
    both.
  * Promotion expectations. `ARCHITECTURE.md` §5 lists them, but there is no
    field on `ServiceMember` to write one into and `engine/profile.py` is not
    ours to change. Grade and years of service are what the pay tables and the
    Social Security earnings history actually read. The Career page still
    models a promotion timeline.

ON GROUP ORDER. These cards render after the common ones, in the order their
`group_rank` declares -- the story of a career, front to back:

    10  About your service          DIEMS, BRS, REDUX, grade
    20  Where you are stationed     duty ZIP, quarters
    25  Special pays and bonuses    the one part of pay no table produces
    30  Contributing to the TSP     contribution % and Roth share
    40  Deployment and combat zone  deployed, months, CZTE, SDP
    70  Leaving the service         planned separation date
   900  The figures we worked out   the pay packet and the corrections, last

This module was first written when `Question` had no `group_rank` and card
order fell back to the card TITLE, alphabetically -- so the titles were chosen
to come out right, and renaming one silently reordered the page. They no longer
carry that load: rename a card freely, and move it by changing its rank.
"""

from __future__ import annotations

from datetime import date, timedelta

from engine.benefits import life_insurance as LI
from engine.funnel import (Question, Derived, FUNNEL_SERVING, KIND_MONEY,
                           KIND_TOGGLE, KIND_INTEGER, KIND_TEXT, KIND_CHOICE,
                           KIND_PCT, KIND_NUMBER, GROUP_REVIEW, RANK_REVIEW,
                           is_deployed)
from engine.intake import pay_check as PC
from engine.intake.pay_check import derive_gross, derive_net
from engine.pay import grades as G
from engine.profile import (DIEMS_BRS_START, DIEMS_REDUX_START, Household)

# --------------------------------------------------------------------------
# Cards, and the order they render in. Every question on a card must repeat
# its card's rank -- `validate()` rejects a card that carries two.
# --------------------------------------------------------------------------
GROUP_SERVICE = "About your service"
GROUP_STATION = "Where you are stationed"
GROUP_SPECIAL = "Special pays and bonuses"
GROUP_TSP = "Contributing to the TSP"
GROUP_DEPLOYMENT = "Deployment and combat zone"
GROUP_SEPARATION = "Leaving the service"

RANK_SERVICE = 10
RANK_STATION = 20
RANK_SPECIAL = 25
RANK_TSP = 30
RANK_DEPLOYMENT = 40
RANK_SEPARATION = 70

#: Years in grade assumed when there is no Date of Rank. It is the declared
#: default of `ServiceMember.time_in_grade_years` and the only thing
#: `time_in_grade()` falls back to, so the review card states it as the
#: assumption it is rather than asking for a number that goes stale.
ASSUMED_TIME_IN_GRADE = 2.0


# --------------------------------------------------------------------------
# Predicates. Named functions, not lambdas, so a failure names something.
# Pure: no writes, no Streamlit, no session state.
# --------------------------------------------------------------------------

def diems_before_brs(h: Household) -> bool:
    """
    Joined before 1 Jan 2018, so BRS was an opt-in rather than the default.

    A DIEMS date that does not parse is not evidence of anything, so the
    question stays hidden rather than being asked of someone whose date is
    simply mistyped.
    """
    d = h.member.diems
    return d is not None and d < DIEMS_BRS_START


def in_csb_redux_window(h: Household) -> bool:
    """
    DIEMS inside the window in which CSB/REDUX could ever have been elected.

    `retirement_system_for_diems()` only honours `took_csb_redux` for a DIEMS
    on or after 1 Aug 1986, and no new election has been possible since the end
    of 2017, so outside that window the answer cannot change any number.
    """
    d = h.member.diems
    return d is not None and DIEMS_REDUX_START <= d < DIEMS_BRS_START


def draws_special_pay(h: Household) -> bool:
    """
    Whether a special pay is taxable only matters once there is one.

    A bonus is separate and is asked on its own: it is taxable unless paid in
    a combat zone, which the app already knows from the deployment card.
    """
    return float(h.member.special_pay_monthly or 0.0) > 0


def sdp_in_play(h: Household) -> bool:
    """
    Hostile fire or imminent danger pay is what opens the SDP -- not deployment.

    A balance already on the plan keeps the question on screen after the
    deployment ends, because the account keeps paying interest for 90 days
    after redeployment and the money still has to be brought home.
    """
    m = h.member
    return bool(m.drawing_hostile_fire_pay) or m.sdp_balance > 0


# --------------------------------------------------------------------------
# Derivations. Pure functions of the Household, like the predicates.
# --------------------------------------------------------------------------

def derive_years_of_service(h: Household) -> float | None:
    """
    Years served: DIEMS date to today, to one decimal.

    The date the app already holds for the retirement system is the same date
    the clock starts on, so nobody is asked for a number that is right on the
    day it is typed and wrong at every opening afterwards. Broken service, and
    a Pay Entry Base Date adjusted for time not served, are what this cannot
    see -- which is exactly why it is offered back for correction.
    """
    d = h.member.diems
    if d is None:
        return None
    return round(max(0.0, (date.today() - d).days / 365.25), 1)


def derive_date_of_rank(h: Household) -> str:
    """
    The Date of Rank implied by the two years in grade the app assumes.

    `ServiceMember.time_in_grade()` falls back to `time_in_grade_years`, whose
    default is two years, and the ONLY thing that reads it is the Social
    Security earnings history -- `grade_history()` splits a career into two
    grade steps at `years_of_service - time_in_grade`. So the app already has
    an answer, and this states it as a date rather than asking for one.
    """
    return (date.today()
            - timedelta(days=round(ASSUMED_TIME_IN_GRADE * 365.25))).isoformat()


def derive_sgli(h: Household) -> float:
    """
    Full SGLI cover, because that is what every member is enrolled at.

    Enrolment is automatic at the maximum and stays there unless the member
    files to reduce or decline it, so the maximum is the answer for almost
    everyone and the review card is where the few who reduced it say so.
    """
    return LI.SGLI_MAX


def derive_has_dependents(h: Household) -> bool:
    """
    Dependants for pay: a spouse, or dependants on the household.

    BAH is binary -- with or without dependants -- and the household has
    already said whether there is a spouse and how many dependants there are.
    A member whose rate differs anyway, dual-military most often, corrects the
    BAH figure itself on the review card rather than this flag.
    """
    return bool(h.has_spouse) or int(h.n_dependents or 0) > 0


# WHY HOSTILE FIRE PAY IS ASKED AND NOT DERIVED FROM THE COMBAT ZONE.
#
# It was derived, from `in_combat_zone`, on the reasoning that the designation
# is what pays it. They are two different designations: a combat zone is
# designated by Executive Order for the tax exclusion (IRC 112), hostile fire
# and imminent danger pay by DoD under 37 U.S.C. 310. They overlap heavily and
# they are not the same list.
#
# Ordinarily a derivation that is right most of the time and correctable is a
# good trade. This one could not be corrected. It derives to True, and
# `is_untouched()` only lets a derivation write into a field still at its
# declared default -- which for a boolean deriving True is the contrary answer.
# So a member who said "no, I am not drawing it" had it flipped back on the
# next render pass, with no widget anywhere to say so again.
#
# And it is load-bearing. `coach/prime_directive._step_sdp` gates the Savings
# Deposit Program on exactly this flag, at weight 2.0 -- the heaviest step in
# the waterfall, ranked above the TSP match. A false positive tells a member to
# deposit ten thousand dollars into an account they cannot open. `1_Profile`'s
# own help text has always said the distinction out loud: "This is what gates
# Savings Deposit Program eligibility, NOT deployment on its own."
#
# R1 asks for the minimum number of questions, and a question earns its place
# when the answer cannot be derived. This one cannot be derived reliably AND
# cannot be corrected, so it is asked -- of the small number of people who are
# deployed, and of nobody else.


# --------------------------------------------------------------------------
# The set
# --------------------------------------------------------------------------

QUESTIONS: tuple[Question, ...] = (
    # -- About your service ------------------------------------------------
    # DIEMS is order 10 of the first card for the reason in the docstring.
    Question(key="srv_diems",
             label="What is your DIEMS date?",
             # ASKED: a date printed on a document. Nothing on the plan implies
             # it, and it decides the retirement system, the TSP match and how
             # long you have served.
             kind=KIND_TEXT, path="member", attr="diems_date",
             group=GROUP_SERVICE, group_rank=RANK_SERVICE, order=10, funnels=(FUNNEL_SERVING,),
             placeholder="2016-05-28",
             help="Enter it as YYYY-MM-DD. Date of Initial Entry to Military "
                  "Service — the day you first swore in, including at an "
                  "academy or in ROTC contracted status. It is on your LES and "
                  "your DD-214. It is NOT the date you started your current "
                  "period of service. "
                  "This one date decides your retirement system, and nothing "
                  "else does: on or after 1 January 2018 you are in the "
                  "Blended Retirement System and there is a TSP match to "
                  "capture; before it, unless you opted in, there is no match "
                  "at all and the whole order of what to fund first changes. "
                  "It is also where your years of service are counted from."),
    Question(key="srv_brs_optin",
             label="Did you opt into BRS in the 2018 window?",
             # ASKED: a choice made in one year and recorded nowhere on the
             # plan. The DIEMS date says the window was open, not what you did.
             kind=KIND_TOGGLE, path="member", attr="opted_into_brs",
             group=GROUP_SERVICE, group_rank=RANK_SERVICE, order=20, funnels=(FUNNEL_SERVING,),
             when=diems_before_brs,
             help="Asked because your DIEMS date is before 2018, so BRS was a "
                  "choice you either made or did not make during that year. "
                  "If you opted in you have a match; if you did not, you have "
                  "a larger pension multiplier and no match."),
    Question(key="srv_csb_redux",
             label="Did you take the CSB/REDUX bonus at 15 years?",
             # ASKED: an irreversible election, and the single answer that most
             # changes what a pension is worth. No trace of it on the plan.
             kind=KIND_TOGGLE, path="member", attr="took_csb_redux",
             group=GROUP_SERVICE, group_rank=RANK_SERVICE, order=30, funnels=(FUNNEL_SERVING,),
             when=in_csb_redux_window,
             help="No new elections have been possible since 2017. This is a "
                  "historical fact to record, not a decision to make."),
    Question(key="srv_grade", label="What is your pay grade?",
             # ASKED: rank is not computable from anything. With years of
             # service it produces basic pay, BAH, BAS and the Social Security
             # earnings history, which is why it stays and they go.
             kind=KIND_CHOICE, path="member", attr="grade",
             group=GROUP_SERVICE, group_rank=RANK_SERVICE, order=40, funnels=(FUNNEL_SERVING,),
             options=tuple(G.GRADE_LABELS),
             help="O-1E, O-2E and O-3E are for officers with at least four "
                  "years of prior enlisted or warrant service. They are paid "
                  "on a separate, higher line."),

    # -- Where you are stationed ------------------------------------------
    Question(key="srv_duty_zip",
             label="What is your duty station ZIP code?",
             # ASKED: where you are posted. It prices BAH and it names the
             # state you live in, and neither is on the plan any other way.
             kind=KIND_TEXT, path="member", attr="duty_zip",
             group=GROUP_STATION, group_rank=RANK_STATION, order=10, funnels=(FUNNEL_SERVING,),
             placeholder="28310",
             help="Drives your BAH, and tells the app which state you live in. "
                  "Leave it blank if you do not know where you are going yet — "
                  "the app will use a national median rate instead."),
    Question(key="srv_gov_housing",
             label="Do you live in government housing?",
             # ASKED: a fact about where you sleep. It decides whether BAH is
             # income to you or paid past you to the housing partner, a
             # four-figure swing a year that nothing on the plan implies.
             kind=KIND_TOGGLE, path="member",
             attr="lives_in_government_housing",
             group=GROUP_STATION, group_rank=RANK_STATION, order=20, funnels=(FUNNEL_SERVING,),
             help="On-base or privatized housing. BAH is paid to the housing "
                  "partner rather than to you, so your out-of-pocket is zero "
                  "and so is the allowance you keep."),

    # -- Special pays and bonuses -----------------------------------------
    # THE ONE PART OF A PAY PACKET THE TABLES CANNOT PRODUCE. Basic pay, BAS
    # and BAH all fall out of grade, longevity and ZIP code and are never
    # asked. Special pays do not: flight pay, sea pay, hazardous duty,
    # dive pay, language pay, medical and dental special pays are each an
    # assignment or a qualification, none of them is on the plan, and whether
    # a given one is taxable turns on where it is earned.
    Question(key="srv_special_pay",
             label="What do you get in special pays, per month?",
             # ASKED: an assignment or a qualification, not a consequence of
             # grade. Nothing the app holds implies it.
             kind=KIND_MONEY, path="member", attr="special_pay_monthly",
             group=GROUP_SPECIAL, group_rank=RANK_SPECIAL, order=10,
             funnels=(FUNNEL_SERVING,), step=50.0, min_value=0.0,
             help="Flight pay, sea pay, hazardous duty, dive pay, jump pay, "
                  "language pay, medical and dental special pays. Leave it at "
                  "zero if you draw none. None of them counts toward retired "
                  "pay, which is why they are worth seeing separately."),
    Question(key="srv_special_pay_taxable",
             label="Are your special pays taxable?",
             # ASKED: most are, some are not, and the answer decides which
             # side of the taxable-untaxed split the money falls on.
             kind=KIND_TOGGLE, path="member", attr="special_pay_taxable",
             group=GROUP_SPECIAL, group_rank=RANK_SPECIAL, order=20,
             funnels=(FUNNEL_SERVING,), when=draws_special_pay,
             help="Most special pays are ordinary taxable income. Pays earned "
                  "in a combat zone are not, and neither is a separate "
                  "allowance for the cost of living overseas. If you draw a "
                  "mix, answer for the larger part and correct the gross "
                  "figure at the bottom of this form."),
    Question(key="srv_bonus",
             label="What bonuses will you receive this year?",
             # ASKED: an enlistment or retention bonus is a contract, not a
             # consequence of anything on the plan — and it is often the
             # largest single taxable event of a career.
             kind=KIND_MONEY, path="member", attr="bonus_annual_taxable",
             group=GROUP_SPECIAL, group_rank=RANK_SPECIAL, order=30,
             funnels=(FUNNEL_SERVING,), step=500.0, min_value=0.0,
             help="Enlistment, re-enlistment, retention or career-field "
                  "bonuses, as a lump sum for the year. Ordinary taxable "
                  "income — unless it is paid while you are in a combat zone, "
                  "in which case it is excluded entirely. That is why people "
                  "time re-enlistment to a deployment."),

    # -- Contributing to the TSP ------------------------------------------
    Question(key="srv_tsp_pct",
             label="How much of your basic pay do you contribute?",
             # ASKED: an election you made at myPay. The app can say what you
             # SHOULD contribute; it cannot know what you do.
             kind=KIND_PCT, path="member", attr="tsp_contribution_pct",
             group=GROUP_TSP, group_rank=RANK_TSP, order=10, funnels=(FUNNEL_SERVING,),
             min_value=0.0, max_value=92.0, step=1.0,
             help="TSP elections are a percentage of BASIC PAY — not of your "
                  "total compensation, and not of BAH or BAS."),
    Question(key="srv_tsp_roth_share",
             label="What share goes to Roth?",
             # ASKED: the other half of the same election, and the one that
             # decides which balance grows — the whole tax-position component
             # of the scorecard turns on it.
             kind=KIND_PCT, path="member", attr="tsp_roth_share",
             group=GROUP_TSP, group_rank=RANK_TSP, order=20, funnels=(FUNNEL_SERVING,),
             min_value=0.0, max_value=100.0, step=5.0,
             help="Of your own contribution. Service automatic and matching "
                  "contributions always go to the traditional balance however "
                  "you designate yours, so 100% here still leaves you with a "
                  "traditional balance to plan around."),

    # -- Deployment and combat zone ---------------------------------------
    Question(key="srv_deployed", label="Are you deployed right now?",
             # ASKED: where you are this year. Nothing on a plan dated in years
             # knows about a nine-month absence.
             kind=KIND_TOGGLE, path="member", attr="is_deployed",
             group=GROUP_DEPLOYMENT, group_rank=RANK_DEPLOYMENT, order=10, funnels=(FUNNEL_SERVING,),
             help="Everything below this only matters while you are — the tax "
                  "exclusion, the Savings Deposit Program and the cheapest "
                  "year you will ever have to fill a Roth account."),
    Question(key="srv_deployed_months",
             label="How many months have you been deployed this year?",
             # ASKED: the count drives the Combat Zone Tax Exclusion month by
             # month, and a deployment has no length the app can infer.
             kind=KIND_INTEGER, path="member",
             attr="months_deployed_this_year",
             group=GROUP_DEPLOYMENT, group_rank=RANK_DEPLOYMENT, order=20, funnels=(FUNNEL_SERVING,),
             when=is_deployed, min_value=0, max_value=12,
             help="Any part of a month in the zone counts as a whole month. A "
                  "deployment from 1 January to 1 July is SEVEN qualifying "
                  "months, not six."),
    Question(key="srv_combat_zone",
             label="Are you in a designated combat zone?",
             # ASKED: the designation is a list of places, not a property of
             # the member. Deployed and in the zone are different facts.
             kind=KIND_TOGGLE, path="member", attr="in_combat_zone",
             group=GROUP_DEPLOYMENT, group_rank=RANK_DEPLOYMENT, order=30, funnels=(FUNNEL_SERVING,),
             when=is_deployed,
             help="Drives the Combat Zone Tax Exclusion. Any part of a month "
                  "in the zone counts as a full month. It is also what pays "
                  "hostile fire or imminent danger pay, so the app takes that "
                  "from this answer rather than asking you twice."),
    Question(key="srv_hostile_fire",
             label="Are you drawing hostile fire or imminent danger pay?",
             # ASKED: it is a separate designation from the combat zone above,
             # it is what actually gates the Savings Deposit Program, and a
             # derivation from the zone could not be corrected. See the note
             # above derive_sgli.
             kind=KIND_TOGGLE, path="member", attr="drawing_hostile_fire_pay",
             group=GROUP_DEPLOYMENT, group_rank=RANK_DEPLOYMENT, order=40,
             funnels=(FUNNEL_SERVING,), when=is_deployed,
             help="This is what gates Savings Deposit Program eligibility, not "
                  "deployment and not the combat zone on its own — they are "
                  "different designations and they do not cover quite the same "
                  "places. It is the line on your LES that says HFP or IDP."),
    Question(key="srv_sdp_balance", label="What is your SDP balance?",
             # ASKED: a balance in an account. No balance is derivable.
             kind=KIND_MONEY, path="member", attr="sdp_balance",
             group=GROUP_DEPLOYMENT, group_rank=RANK_DEPLOYMENT, order=50, funnels=(FUNNEL_SERVING,),
             when=sdp_in_play, step=500.0, max_value=50_000.0,
             help="The Savings Deposit Program pays 10% guaranteed on up to "
                  "10,000 dollars, compounded monthly, and keeps paying for 90 "
                  "days after you redeploy. Nothing else available to you "
                  "returns that with certainty."),

    # -- Leaving the service ----------------------------------------------
    Question(key="srv_separation_date",
             label="When do you plan to separate or retire?",
             # ASKED: a decision, and for this funnel THE decision. Blank is a
             # real answer — it is what makes the app compare staying against
             # going instead of assuming either.
             kind=KIND_TEXT, path="member", attr="planned_separation_date",
             group=GROUP_SEPARATION, group_rank=RANK_SEPARATION, order=10, funnels=(FUNNEL_SERVING,),
             placeholder="2031-06-30",
             help="Enter it as YYYY-MM-DD. Your ETS or retirement date. "
                  "Terminal leave does not move it — it is the last stretch "
                  "of it. Leave it blank if you have not picked one; this "
                  "funnel exists because that is "
                  "still a decision, and the app will compare staying against "
                  "going rather than assume either."),

    # ======================================================================
    # The figures we worked out. NOT ASKED: every one of these renders on the
    # review card at the end of intake, seeded with what the app computed and
    # captioned with where it came from.
    # ======================================================================
    Question(key="srv_yos", label="How many years have you served?",
             kind=KIND_NUMBER, path="member", attr="years_of_service",
             group=GROUP_REVIEW, group_rank=RANK_REVIEW, order=10, funnels=(FUNNEL_SERVING,),
             min_value=0.0, max_value=45.0, step=0.5,
             derive=derive_years_of_service, fills_in=True,
             derived_from="your DIEMS date, counted to today",
             help="Total years for pay purposes. Correct it if you have broken "
                  "service, or a Pay Entry Base Date adjusted for time not "
                  "served — the app counts straight from your DIEMS date and "
                  "cannot see either."),
    Question(key="srv_dor", label="What is your Date of Rank?",
             kind=KIND_TEXT, path="member", attr="date_of_rank",
             group=GROUP_REVIEW, group_rank=RANK_REVIEW, order=20, funnels=(FUNNEL_SERVING,),
             placeholder="2023-06-01",
             derive=derive_date_of_rank, fills_in=False,
             derived_from="an assumed two years in grade",
             help="Enter it as YYYY-MM-DD. Left blank, the app assumes two "
                  "years in grade — which is all the Social Security earnings "
                  "estimate uses it for, splitting your career into the grade "
                  "you hold now and the one before it. A real Date of Rank "
                  "sharpens that estimate and stays right as the years pass."),
    # THE CONFIRMATION PAUL ASKED FOR. The app can say what a member of this
    # grade, at this longevity, at this ZIP code SHOULD be paid; it cannot see
    # the deductions column of an LES. So these two are seeded with the app's
    # own arithmetic, and a figure entered here wins over it --
    # `engine/intake/pay_check.py` holds the rule and the explanation.
    Question(key="srv_gross",
             label="What does your LES say your gross pay is, per month?",
             kind=KIND_MONEY, path="member", attr="gross_pay_monthly_confirmed",
             group=GROUP_REVIEW, group_rank=RANK_REVIEW, order=70,
             funnels=(FUNNEL_SERVING,), step=50.0, min_value=0.0,
             derive=derive_gross, fills_in=False,
             derived_from="basic pay, BAS, BAH and your special pays added up",
             help="The entitlements total on your LES, before anything is "
                  "taken out. Leave it at zero to accept the figure above. "
                  "Enter your own and the app uses it instead — and tells you "
                  "how far apart the two are, because a gap usually has a name."),
    Question(key="srv_net",
             label="What does your LES say your net pay is, per month?",
             kind=KIND_MONEY, path="member", attr="net_pay_monthly_confirmed",
             group=GROUP_REVIEW, group_rank=RANK_REVIEW, order=80,
             funnels=(FUNNEL_SERVING,), step=50.0, min_value=0.0,
             derive=derive_net, fills_in=False,
             derived_from="your gross, less the TSP, SGLI, FICA and the tax "
                          "the app can estimate",
             help="What actually reaches your account. This is the figure most "
                  "worth entering: the app estimates withholding from the "
                  "brackets and a standard deduction, and it cannot see an "
                  "allotment, a debt collection or a garnishment at all. Leave "
                  "it at zero to accept the estimate."),
    Question(key="srv_sgli", label="How much SGLI coverage do you carry?",
             kind=KIND_MONEY, path="member", attr="sgli_coverage",
             group=GROUP_REVIEW, group_rank=RANK_REVIEW, order=60, funnels=(FUNNEL_SERVING,),
             min_value=0.0, max_value=LI.SGLI_MAX, step=50_000.0,
             derive=derive_sgli, fills_in=True,
             derived_from="automatic enrolment at the maximum",
             help="Sold in increments of 50,000 dollars to a maximum of "
                  "half a million, at a "
                  "flat rate that is the same at 22 as it is at 52 — which is "
                  "why it is worth deciding what you will replace it with "
                  "before you separate rather than after. It continues free "
                  "for 120 days after you go and then stops. Correct it here "
                  "if you reduced or declined the cover."),
)


# --------------------------------------------------------------------------
# Settled facts: worked out, written into the plan, never a widget
# --------------------------------------------------------------------------

DERIVED: tuple[Derived, ...] = (
    Derived(key="srv_d_has_dependents",
            label="BAH dependency rate",
            path="member", attr="has_dependents",
            compute=derive_has_dependents,
            because="it follows the spouse and dependants on your household, "
                    "and BAH is paid at one rate or the other",
            funnels=(FUNNEL_SERVING,)),
)


# --------------------------------------------------------------------------
# The confirmation step: what the app worked your pay out to be
# --------------------------------------------------------------------------
# The optional half of a funnel module's contract. `engine/intake` looks for
# these two names and the intake page renders whatever they return, so the
# page never learns what a pay packet is.

def statement(h: Household) -> list[tuple[str, str]]:
    """The pay packet, line by line, read-only. See `pay_check.statement`."""
    return PC.statement(h)


def findings(h: Household) -> list[tuple[str, str, str]]:
    """What to say when a confirmed figure and the tables disagree."""
    return PC.findings(h)
