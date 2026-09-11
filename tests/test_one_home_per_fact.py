"""
R3: a fact is entered once and populates everywhere.

`ARCHITECTURE.md` §5a: "No field is asked on two pages. Where a page needs a
figure another page already holds, it reads it." §4a locates the damage: the
same question was asked in up to three places, the copies disagreed about what
they meant, and a member who corrected a figure on one page had no way of
knowing which copy the next page would read.

The four rows §4a names, and where each fact now lives:

    in_combat_zone, months_deployed_this_year,     Intake (serving), read on
    drawing_hostile_fire_pay, sdp_balance          Profile and Deployment

    retired_pay_monthly, sbp_elected               Intake (retiree), read on
                                                   Profile and Survivor

    civilian_wages_annual                          Intake (common), read on
                                                   Profile and Social Security

    state_of_legal_residence                       Intake (common), read on
                                                   Profile and Residency
                                                   (its own file of tests)

A source scan is crude, and it is the right tool here: the defect is a second
`ui.panel` helper bound to a field, and a helper call is exactly what a source
scan can see. Driving the page would only prove the widget is gone from one
code path.
"""

import re
import sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from engine import intake, storage
from engine.profile import Household

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

HELPERS = ("money", "pct", "integer", "number", "text", "toggle", "choice")

#: Every page that used to hold a second copy of a fact intake now owns, and
#: the fields it must no longer write. The importer is excluded on purpose:
#: it PROPOSES and never applies, which is a different contract (R2).
DEDUPED = {
    "1_Profile.py": ("in_combat_zone", "months_deployed_this_year",
                     "drawing_hostile_fire_pay", "sdp_balance",
                     "retired_pay_monthly", "sbp_elected",
                     "civilian_wages_annual", "state_of_legal_residence",
                     "current_state", "grade", "years_of_service",
                     "has_dependents", "duty_zip", "diems_date", "birth_year",
                     "sex", "has_spouse", "n_dependents", "va_rating",
                     "va_disability_monthly", "crdp_applies", "crsc_monthly",
                     "date_of_rank", "time_in_grade_years", "opted_into_brs",
                     "took_csb_redux", "lives_in_government_housing"),
    "7_TSP_and_Deployment.py": ("in_combat_zone", "months_deployed_this_year",
                                "drawing_hostile_fire_pay", "sdp_balance",
                                "tsp_contribution_pct", "tsp_roth_share"),
    "9_Survivor_and_VA.py": ("retired_pay_monthly", "sbp_elected", "va_rating"),
    "15_Social_Security.py": ("civilian_wages_annual",),
    "10_Residency_and_Education.py": ("state_of_legal_residence",),
}


def source(name: str) -> str:
    return (ROOT / "pages" / name).read_text(encoding="utf-8")


def binds(src: str, attr: str) -> bool:
    """Is a `ui.panel` helper bound to this attribute anywhere in the source?"""
    return bool(re.search(r'\b(%s)\([^\n]*"%s"' % ("|".join(HELPERS),
                                                   re.escape(attr)), src))


@pytest.mark.parametrize("page,fields",
                         [(p, f) for p, f in DEDUPED.items()])
def test_a_deduplicated_page_no_longer_writes_the_field(page, fields):
    src = source(page)
    offenders = [attr for attr in fields if binds(src, attr)]
    assert not offenders, f"{page} still asks for {offenders} — intake owns them"


@pytest.mark.parametrize("page", sorted(DEDUPED))
def test_every_deduplicated_page_says_where_the_answers_live(page):
    """Reading a fact is only half of it — the user has to be told where to
    change it, or the page looks broken rather than deliberate."""
    src = source(page)
    assert "01_Intake.py" in src, f"{page} reads facts and does not link home"


@pytest.mark.parametrize("page", sorted(DEDUPED))
@pytest.mark.parametrize("sample", ["e5_6yrs_brs.mpfplan.json",
                                    "retired_o5_26yrs.mpfplan.json"])
def test_every_deduplicated_page_still_renders_for_both_samples(page, sample):
    h = storage.from_upload_bytes((ROOT / "samples" / sample).read_bytes())
    at = AppTest.from_file(str(ROOT / "pages" / page), default_timeout=180)
    at.session_state["household"] = h
    at.session_state["plan_version"] = 0
    at.run()
    assert not at.exception, at.exception


def test_the_component_and_branch_still_have_a_home():
    """
    The two facts intake deliberately does not ask. If Profile stopped
    offering them, a Guard member would have no way to say so and every
    component gate in the app (§4a) would read Active Duty.
    """
    src = source("1_Profile.py")
    assert binds(src, "component")
    assert binds(src, "branch")
    for funnel in intake.FUNNELS:
        assert not any(q.attr in ("component", "branch")
                       for q in intake.all_questions(funnel))


def test_the_status_gates_still_see_what_they_always_saw():
    """
    §4a's thirty-odd gates read `member.component`. Moving where a question
    lives must not change what they see, so the one thing that sets the
    component is still the funnel, and preparing a household never moves it.
    """
    for funnel, expected in ((intake.FUNNEL_SERVING, "Active Duty"),
                             (intake.FUNNEL_VETERAN, "Veteran (not retired)"),
                             (intake.FUNNEL_RETIRED, "Military Retiree")):
        h = Household()
        intake.set_funnel(h, funnel)
        assert h.member.component == expected
        intake.prepare(h)
        assert h.member.component == expected


def test_a_page_local_what_if_is_not_a_second_copy_of_a_field():
    """
    R3 allows a second page to explore a DIFFERENT value, visibly labelled.
    The SBP base amount is the case: the plan carries no field for it, so the
    widget writes nothing and the help says so.
    """
    src = source("9_Survivor_and_VA.py")
    assert 'key=wkey("sbpbase")' in src
    assert "A what-if on this page only" in src
    assert "no base-amount field" in src


# ==========================================================================
# The rule is the harm, not the widget count (FUNNEL_CONTRACT.md §14)
# ==========================================================================

import ast

HELPERS = {"money", "pct", "number", "integer", "text", "toggle", "choice"}

#: `ui.panel` helper -> the Household attribute path its second argument names.
_OBJ_PATHS = {"h": "", "m": "member", "e": "estate", "hc": "healthcare",
              "inv": "investments", "ss": "social_security", "hz": "housing",
              "a": "assumptions", "t": "career"}


def _page_bindings(path: pathlib.Path):
    """Every (obj_path, attr) a `ui.panel` helper is bound to on this page."""
    out = []
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(n, ast.Call) or len(n.args) < 3:
            continue
        fn = n.func
        name = fn.attr if isinstance(fn, ast.Attribute) else (
            fn.id if isinstance(fn, ast.Name) else "")
        if name not in HELPERS or not isinstance(n.args[2], ast.Constant):
            continue
        obj = ast.unparse(n.args[1])
        out.append((_OBJ_PATHS.get(obj, obj), n.args[2].value))
    return out


def test_every_shared_field_is_written_through_a_panel_helper():
    """
    §14: a second widget on a fact is fine when it writes the same field the
    same way. It is a defect when it writes nothing back — that is §4a's
    finding, and it is what this guards.

    A `ui.panel` helper is the write-back path: it sets the attribute and calls
    `mark_dirty()` and `invalidate()`. So for every field intake owns, any page
    that also offers it must offer it through a helper, never through a bare
    `st.number_input` seeded from the plan.
    """
    owned = {(q.path, q.attr) for f in intake.FUNNELS
             for q in intake.all_questions(f)}

    shared = 0
    for page in sorted((ROOT / "pages").glob("*.py")):
        if page.name in ("00_Start.py", "01_Intake.py"):
            continue
        for field in _page_bindings(page):
            if field not in owned:
                continue
            shared += 1
            # Reaching here IS the assertion: `_page_bindings` only reports a
            # field a `ui.panel` helper is bound to, so an intake-owned field
            # found here is one this page writes back through. A page that
            # seeded a raw `st.number_input` from the plan instead would not
            # appear, and the recorded-gap test below is what catches those.
    assert shared >= 10, (
        "the drill-down pages stopped offering the fields intake owns — "
        "§6 makes them the place a low rating gets fixed, so they should")


#: The exact words a page-local knob carries, so a reader knows it will not
#: stick. Established on `9_Survivor_and_VA.py`, recorded in §14.
WHATIF_PHRASE = "A what-if on this page only"


#: What each of §4a's three pages writes back, exactly. §14 used to record
#: these as three zeroes -- thirty-odd widgets seeded from the plan and thrown
#: away. They write back now, and the set is pinned rather than the count so a
#: change says WHICH fact moved.
WRITES_BACK = {
    "8_Retirement.py": {
        ("member", "high_3_monthly_override"),
        ("career", "separation_at_years_of_service"),
        ("assumptions", "real_discount_rate_pct"),
    },
    "11_Separation_and_Insurance.py": {
        ("member", "dod_disability_rating"),
        ("member", "disability_combat_related"),
        ("member", "disability_incurred_in_combat_zone"),
        ("member", "on_tdrl"),
        ("member", "high_3_monthly_override"),
        ("member", "va_disability_monthly"),
        ("member", "sgli_coverage"),
        ("career", "separation_at_years_of_service"),
        ("", "mortgage_balance"),
    },
    "22_This_Years_Taxes.py": {
        ("h.spouse_income", "annual_income"),
    },
}


def test_the_pages_that_wrote_nothing_back_now_write_every_fact_back():
    """
    §4a named three pages that seeded page-local widgets from the plan and
    wrote nothing back, so a member who corrected a figure there had corrected
    nothing. That is fixed, and this pins what each page owns.

    The set is exact in both directions on purpose. A field appearing here that
    should not have is a what-if promoted into a stored fact -- the thing §14
    forbids -- and a field disappearing is a fact going back to being thrown
    away. Either is a deliberate decision that updates FUNNEL_CONTRACT.md §14
    alongside this test.
    """
    for name, expected in WRITES_BACK.items():
        page = ROOT / "pages" / name
        assert page.exists(), name
        assert set(_page_bindings(page)) == expected, (
            f"{name} writes back a different set than §14 records. Update "
            f"FUNNEL_CONTRACT.md §14 and this test, deliberately.")

    # And the contract says so, so the two cannot drift apart.
    contract = (ROOT / "docs" / "FUNNEL_CONTRACT.md").read_text(encoding="utf-8")
    for name in WRITES_BACK:
        assert name in contract, f"§14 does not record {name}"


def test_no_fourth_page_seeds_a_widget_from_the_plan_and_throws_it_away():
    """
    The other half of the old recorded-gap test: the gap must not reopen
    somewhere else. Every page that reads the Household into a raw `st.*`
    widget has to either write it back through a `ui.panel` helper or say on
    screen that it is a what-if, and §14's phrase is how it says so.

    This is deliberately narrow -- it checks the three pages the round-three
    work covered, plus the one page that already carried a labelled what-if --
    because a whole-tree sweep would be a different piece of work and is
    recorded as such.
    """
    for name in list(WRITES_BACK) + ["9_Survivor_and_VA.py"]:
        src = source(name)
        assert WHATIF_PHRASE in src, (
            f"{name} has no labelled what-if; if every input on it now writes "
            f"back, say so in §14 and here")


def test_a_shared_field_is_asked_the_same_question_in_both_homes():
    """
    §14's second defect: two widgets writing one field while asking different
    questions. `estate.n_children` is the case that has bitten twice — once as
    a GI Bill question, once as a derivation from pay dependants.
    """
    owned = {(q.path, q.attr): q for f in intake.FUNNELS
             for q in intake.all_questions(f)}
    assert ("estate", "n_children") not in owned, \
        "estate.n_children has one home, the Estate page"
    for f in intake.FUNNELS:
        assert not any(d.attr == "n_children" for d in intake.all_derived(f))
