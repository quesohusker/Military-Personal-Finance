"""
The Currently Serving question set.

`docs/ARCHITECTURE.md` §2: this funnel exists because for someone in uniform
almost none of the future is settled yet -- stay to 20 or leave at 12, take the
BRS lump sum or not, deploy, transfer the GI Bill, pick a separation date. The
questions here are the facts those decisions are computed from, and nothing
else: the common set in `engine/funnel.py` already asks birth year, sex,
spouse, dependents, residence, balances, spending and target retirement age,
and none of that is repeated here.

THE DIEMS DATE IS ASKED FIRST AND IT IS ASKED ALONE-ISH ON PURPOSE. It resolves
the retirement system (`ServiceMember.retirement_system`), the retirement
system decides whether a TSP match exists at all (`has_tsp_match`), and the
match reorders the entire financial priority waterfall. Nothing else in the
app decides it, and a wrong DIEMS date makes every downstream recommendation
wrong while looking perfectly reasonable. `HANDOFF.md` calls it the most
load-bearing field in the app; it gets the first card and help text that says
what it is, where to find it, and what it is not.

Two things that are NOT asked here, deliberately:

  * Component and branch. `set_funnel()` already guarantees the component is
    Active, Guard or Reserve for this funnel, and branch changes no number in
    any projection -- it changes a rank title. The profile page still offers
    both.
  * Promotion expectations. `ARCHITECTURE.md` §5 lists them, but there is no
    field on `ServiceMember` to write one into and `engine/profile.py` is not
    ours to change. Grade, years of service and Date of Rank are what the pay
    tables and the Social Security earnings history actually read, so they are
    what is asked. The Career page still models a promotion timeline.

ON GROUP ORDER. These cards render after the common ones, in the order their
`group_rank` declares -- the story of a career, front to back:

    10  About your service          DIEMS, grade, years, Date of Rank
    20  Allowances and where you are stationed
                                    duty ZIP, dependents for pay, quarters
    30  Contributing to the TSP     contribution % and Roth share
    40  Deployment and combat zone  deployed, months, CZTE, HFP, SDP
    50  Insurance while you serve   SGLI
    60  The GI Bill                 use it or transfer it
    70  Leaving the service         planned separation date

This module was first written when `Question` had no `group_rank` and card
order fell back to the card TITLE, alphabetically -- so the titles were chosen
to come out right, and renaming one silently reordered the page. They no longer
carry that load: rename a card freely, and move it by changing its rank.
"""

from __future__ import annotations

from engine.benefits import gi_bill as GI
from engine.benefits import life_insurance as LI
from engine.funnel import (Question, FUNNEL_SERVING, KIND_MONEY, KIND_TOGGLE,
                           KIND_INTEGER, KIND_TEXT, KIND_CHOICE, KIND_PCT,
                           KIND_NUMBER, is_deployed)
from engine.pay import grades as G
from engine.profile import (DIEMS_BRS_START, DIEMS_REDUX_START, Household)

# --------------------------------------------------------------------------
# Cards, and the order they render in. Every question on a card must repeat
# its card's rank -- `validate()` rejects a card that carries two.
# --------------------------------------------------------------------------
GROUP_SERVICE = "About your service"
GROUP_STATION = "Allowances and where you are stationed"
GROUP_TSP = "Contributing to the TSP"
GROUP_DEPLOYMENT = "Deployment and combat zone"
GROUP_INSURANCE = "Insurance while you serve"
GROUP_GI_BILL = "The GI Bill"
GROUP_SEPARATION = "Leaving the service"

RANK_SERVICE = 10
RANK_STATION = 20
RANK_TSP = 30
RANK_DEPLOYMENT = 40
RANK_INSURANCE = 50
RANK_GI_BILL = 60
RANK_SEPARATION = 70


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


def has_no_date_of_rank(h: Household) -> bool:
    """
    Ask for time in grade only when there is no Date of Rank to compute it.

    A DOR is a fact that stays right as the years pass; a typed number of years
    is right on the day it is entered and quietly wrong every time the plan is
    opened afterwards. `ServiceMember.time_in_grade()` prefers the DOR, so this
    field is the fallback for someone who does not know theirs.
    """
    return h.member.dor is None


def sdp_in_play(h: Household) -> bool:
    """
    Hostile fire or imminent danger pay is what opens the SDP -- not deployment.

    A balance already on the plan keeps the question on screen after the
    deployment ends, because the account keeps paying interest for 90 days
    after redeployment and the money still has to be brought home.
    """
    m = h.member
    return bool(m.drawing_hostile_fire_pay) or m.sdp_balance > 0


def can_transfer_gi_bill(h: Household) -> bool:
    """
    Transfer needs six years served, and it must be requested while serving.

    Below the six-year mark there is nothing to decide yet; above it the clock
    on the four-year obligation is running against a separation date.
    """
    return h.member.years_of_service >= GI.TRANSFER_SERVICE_REQUIRED


# --------------------------------------------------------------------------
# The set
# --------------------------------------------------------------------------

QUESTIONS: tuple[Question, ...] = (
    # -- About your service ------------------------------------------------
    # DIEMS is order 10 of the first card for the reason in the docstring.
    Question(key="srv_diems",
             label="What is your DIEMS date?",
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
                  "at all and the whole order of what to fund first changes."),
    Question(key="srv_brs_optin",
             label="Did you opt into BRS in the 2018 window?",
             kind=KIND_TOGGLE, path="member", attr="opted_into_brs",
             group=GROUP_SERVICE, group_rank=RANK_SERVICE, order=20, funnels=(FUNNEL_SERVING,),
             when=diems_before_brs,
             help="Asked because your DIEMS date is before 2018, so BRS was a "
                  "choice you either made or did not make during that year. "
                  "If you opted in you have a match; if you did not, you have "
                  "a larger pension multiplier and no match."),
    Question(key="srv_csb_redux",
             label="Did you take the CSB/REDUX bonus at 15 years?",
             kind=KIND_TOGGLE, path="member", attr="took_csb_redux",
             group=GROUP_SERVICE, group_rank=RANK_SERVICE, order=30, funnels=(FUNNEL_SERVING,),
             when=in_csb_redux_window,
             help="No new elections have been possible since 2017. This is a "
                  "historical fact to record, not a decision to make."),
    Question(key="srv_grade", label="What is your pay grade?",
             kind=KIND_CHOICE, path="member", attr="grade",
             group=GROUP_SERVICE, group_rank=RANK_SERVICE, order=40, funnels=(FUNNEL_SERVING,),
             options=tuple(G.GRADE_LABELS),
             help="O-1E, O-2E and O-3E are for officers with at least four "
                  "years of prior enlisted or warrant service. They are paid "
                  "on a separate, higher line."),
    Question(key="srv_yos", label="How many years have you served?",
             kind=KIND_NUMBER, path="member", attr="years_of_service",
             group=GROUP_SERVICE, group_rank=RANK_SERVICE, order=50, funnels=(FUNNEL_SERVING,),
             min_value=0.0, max_value=45.0, step=0.5,
             help="Total years for pay purposes. It sets your column in the "
                  "basic pay table, your place on the 20-year line and, with "
                  "six years, when a GI Bill transfer becomes possible."),
    Question(key="srv_dor",
             label="What is your Date of Rank?",
             kind=KIND_TEXT, path="member", attr="date_of_rank",
             group=GROUP_SERVICE, group_rank=RANK_SERVICE, order=60, funnels=(FUNNEL_SERVING,),
             placeholder="2023-06-01",
             help="Enter it as YYYY-MM-DD. The day you pinned on your current "
                  "grade. It is on your LES and your ORB or ERB. It is NOT "
                  "your DIEMS date and NOT the "
                  "day you joined — it resets at every promotion. Given it, "
                  "the app works out your time in grade and keeps it right as "
                  "the years pass; leave it blank and it asks you for the "
                  "number instead, which is correct on the day you type it and "
                  "stale every time you open the plan afterwards."),
    Question(key="srv_time_in_grade",
             label="How long in your current grade?",
             kind=KIND_NUMBER, path="member", attr="time_in_grade_years",
             group=GROUP_SERVICE, group_rank=RANK_SERVICE, order=70, funnels=(FUNNEL_SERVING,),
             when=has_no_date_of_rank,
             min_value=0.0, max_value=30.0, step=0.5,
             help="Only asked because there is no Date of Rank above. Enter "
                  "that instead and this looks after itself."),

    # -- Allowances and where you are stationed ---------------------------
    Question(key="srv_duty_zip",
             label="What is your duty station ZIP code?",
             kind=KIND_TEXT, path="member", attr="duty_zip",
             group=GROUP_STATION, group_rank=RANK_STATION, order=10, funnels=(FUNNEL_SERVING,),
             placeholder="28310",
             help="Drives your BAH. Leave blank if you do not know where you "
                  "are going yet — the app will use a national median instead."),
    Question(key="srv_has_dependents",
             label="Do you have dependents for pay purposes?",
             kind=KIND_TOGGLE, path="member", attr="has_dependents",
             group=GROUP_STATION, group_rank=RANK_STATION, order=20, funnels=(FUNNEL_SERVING,),
             help="BAH is binary: with or without dependents. The number of "
                  "dependents does not change the rate."),
    Question(key="srv_gov_housing",
             label="Do you live in government housing?",
             kind=KIND_TOGGLE, path="member",
             attr="lives_in_government_housing",
             group=GROUP_STATION, group_rank=RANK_STATION, order=30, funnels=(FUNNEL_SERVING,),
             help="On-base or privatized housing. BAH is paid to the housing "
                  "partner rather than to you, so your out-of-pocket is zero "
                  "and so is the allowance you keep."),

    # -- Contributing to the TSP ------------------------------------------
    Question(key="srv_tsp_pct",
             label="How much of your basic pay do you contribute?",
             kind=KIND_PCT, path="member", attr="tsp_contribution_pct",
             group=GROUP_TSP, group_rank=RANK_TSP, order=10, funnels=(FUNNEL_SERVING,),
             min_value=0.0, max_value=92.0, step=1.0,
             help="TSP elections are a percentage of BASIC PAY — not of your "
                  "total compensation, and not of BAH or BAS."),
    Question(key="srv_tsp_roth_share",
             label="What share goes to Roth?",
             kind=KIND_PCT, path="member", attr="tsp_roth_share",
             group=GROUP_TSP, group_rank=RANK_TSP, order=20, funnels=(FUNNEL_SERVING,),
             min_value=0.0, max_value=100.0, step=5.0,
             help="Of your own contribution. Service automatic and matching "
                  "contributions always go to the traditional balance however "
                  "you designate yours, so 100% here still leaves you with a "
                  "traditional balance to plan around."),

    # -- Deployment and combat zone ---------------------------------------
    Question(key="srv_deployed", label="Are you deployed right now?",
             kind=KIND_TOGGLE, path="member", attr="is_deployed",
             group=GROUP_DEPLOYMENT, group_rank=RANK_DEPLOYMENT, order=10, funnels=(FUNNEL_SERVING,),
             help="Everything below this only matters while you are — the tax "
                  "exclusion, the Savings Deposit Program and the cheapest "
                  "year you will ever have to fill a Roth account."),
    Question(key="srv_deployed_months",
             label="How many months have you been deployed this year?",
             kind=KIND_INTEGER, path="member",
             attr="months_deployed_this_year",
             group=GROUP_DEPLOYMENT, group_rank=RANK_DEPLOYMENT, order=20, funnels=(FUNNEL_SERVING,),
             when=is_deployed, min_value=0, max_value=12,
             help="Any part of a month in the zone counts as a whole month. A "
                  "deployment from 1 January to 1 July is SEVEN qualifying "
                  "months, not six."),
    Question(key="srv_combat_zone",
             label="Are you in a designated combat zone?",
             kind=KIND_TOGGLE, path="member", attr="in_combat_zone",
             group=GROUP_DEPLOYMENT, group_rank=RANK_DEPLOYMENT, order=30, funnels=(FUNNEL_SERVING,),
             when=is_deployed,
             help="Drives the Combat Zone Tax Exclusion. Any part of a month "
                  "in the zone counts as a full month."),
    Question(key="srv_hostile_fire",
             label="Are you drawing hostile fire or imminent danger pay?",
             kind=KIND_TOGGLE, path="member", attr="drawing_hostile_fire_pay",
             group=GROUP_DEPLOYMENT, group_rank=RANK_DEPLOYMENT, order=40, funnels=(FUNNEL_SERVING,),
             when=is_deployed,
             help="This is what gates Savings Deposit Program eligibility, "
                  "not deployment on its own."),
    Question(key="srv_sdp_balance", label="What is your SDP balance?",
             kind=KIND_MONEY, path="member", attr="sdp_balance",
             group=GROUP_DEPLOYMENT, group_rank=RANK_DEPLOYMENT, order=50, funnels=(FUNNEL_SERVING,),
             when=sdp_in_play, step=500.0, max_value=50_000.0,
             help="The Savings Deposit Program pays 10% guaranteed on up to "
                  "$10,000, compounded monthly, and keeps paying for 90 days "
                  "after you redeploy. Nothing else available to you returns "
                  "that with certainty."),

    # -- Insurance while you serve ----------------------------------------
    Question(key="srv_sgli",
             label="How much SGLI coverage do you carry?",
             kind=KIND_MONEY, path="member", attr="sgli_coverage",
             group=GROUP_INSURANCE, group_rank=RANK_INSURANCE, order=10, funnels=(FUNNEL_SERVING,),
             min_value=0.0, max_value=LI.SGLI_MAX, step=50_000.0,
             help="Sold in increments of 50,000 dollars to a maximum of "
                  "half a million, at a "
                  "flat rate that is the same at 22 as it is at 52 — which is "
                  "why it is worth deciding what you will replace it with "
                  "before you separate rather than after. It continues free "
                  "for 120 days after you go and then stops."),

    # -- Leaving the service ----------------------------------------------
    Question(key="srv_separation_date",
             label="When do you plan to separate or retire?",
             kind=KIND_TEXT, path="member", attr="planned_separation_date",
             group=GROUP_SEPARATION, group_rank=RANK_SEPARATION, order=10, funnels=(FUNNEL_SERVING,),
             placeholder="2031-06-30",
             help="Enter it as YYYY-MM-DD. Your ETS or retirement date. "
                  "Terminal leave does not move it — it is the last stretch "
                  "of it. Leave it blank if you have not picked one; this "
                  "funnel exists because that is "
                  "still a decision, and the app will compare staying against "
                  "going rather than assume either."),

    # -- The GI Bill -------------------------------------------------------
    # THE LABEL IS "how many children do you have", NOT "how many could use
    # the GI Bill", and the difference matters. `estate.n_children` is read by
    # `estate/planning.py` for gifting and bequests and by `roth_bridge.py` as
    # the heir count, and the estate page asks for it in exactly those words.
    # Asking here for the SUBSET young enough to use a transferred benefit
    # would write a smaller number into a field the rest of the app reads as
    # the whole family -- the same field, two meanings, which is the §4a defect
    # intake exists to end. The GI Bill reasoning belongs in the help text, and
    # that is where it is.
    Question(key="srv_gi_bill_children",
             label="How many children do you have?",
             kind=KIND_INTEGER, path="estate", attr="n_children",
             group=GROUP_GI_BILL, group_rank=RANK_GI_BILL, order=10, funnels=(FUNNEL_SERVING,),
             when=can_transfer_gi_bill, min_value=0, max_value=12,
             help="Asked here because you have served long enough to transfer "
                  "the Post-9/11 GI Bill, and how many children you have "
                  "decides whether that is worth more than using it yourself. "
                  "Transferring is a purchase, not a gift: it takes six years "
                  "of service and an agreement to serve four more, and it must "
                  "be requested WHILE YOU ARE STILL SERVING — it cannot be "
                  "started after you separate. A child must also finish using "
                  "it before turning 26, so count them all here and the GI "
                  "Bill page will tell you which ones the clock still suits. "
                  "This is the same count the estate page uses."),
)
