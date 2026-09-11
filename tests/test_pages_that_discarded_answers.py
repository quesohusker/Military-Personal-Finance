"""
The three pages that asked for figures and then threw them away.

`ARCHITECTURE.md` §4a, and `FUNNEL_CONTRACT.md` §14 round three: Pension,
Medical Separation and Taxes carried thirty-odd inputs between them, every one
seeded from the plan and written nowhere. A member who corrected a figure on
any of them had corrected nothing -- gone on the next rerun, absent from the
downloaded plan, invisible to the scorecard.

The fix is not "persist everything". Two different things were sitting on those
pages wearing the same clothes:

  * **A fact about the member** -- their real high-3, the rating a board gave
    them, the VA compensation that actually arrives. One home, written through
    a `ui.panel` helper with `mark_dirty()` and `invalidate()`, like every
    other input in the app. `test_one_home_per_fact.py` pins which.

  * **A what-if** -- "what if I took the 50% lump sum?", "what if I filed
    separately?", "what if I spent seven months in the zone?". Persisting one
    of those would be wrong: it is a scenario, not a claim about the member.
    It stays page-local, and it has to SAY SO, because the failure was never
    that the value was discarded -- it was that nothing on screen said it would
    be.

This file guards the second half. Every raw `st.*` input widget left on those
three pages carries §14's phrase in its help, and the new fields the first half
needed survive a save and a load.
"""

import ast
import sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from engine import storage
from engine.profile import Household, ServiceMember, ACTIVE, RETIRED

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

PAGES = ("8_Retirement.py", "11_Separation_and_Insurance.py",
         "22_This_Years_Taxes.py")

SAMPLES = ("e5_6yrs_brs.mpfplan.json", "retired_o5_26yrs.mpfplan.json")

#: §14's words, established on `9_Survivor_and_VA.py`.
WHATIF_PHRASE = "A what-if on this page only"

#: Everything in `streamlit` that takes an answer from the user. `st.caption`,
#: `st.markdown` and friends are not on it -- they say things, they do not ask.
WIDGETS = {"number_input", "text_input", "text_area", "selectbox", "slider",
           "select_slider", "radio", "toggle", "checkbox", "multiselect",
           "date_input", "time_input", "color_picker", "file_uploader",
           "data_editor", "camera_input"}


def _raw_widgets(name: str):
    """Every bare `st.<widget>(...)` call left on a page, with its `help=`."""
    tree = ast.parse((ROOT / "pages" / name).read_text(encoding="utf-8"))
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
            continue
        if n.func.attr not in WIDGETS:
            continue
        if not (isinstance(n.func.value, ast.Name) and n.func.value.id == "st"):
            continue
        helps = [k.value for k in n.keywords if k.arg == "help"]
        label = (n.args[0].value if n.args and isinstance(n.args[0], ast.Constant)
                 else ast.unparse(n.args[0]) if n.args else "?")
        out.append((n.func.attr, label,
                    ast.unparse(helps[0]) if helps else ""))
    return out


@pytest.mark.parametrize("page", PAGES)
def test_every_page_local_knob_says_on_screen_that_it_is_one(page):
    """
    The defect §14 names is a SILENT discard. A knob that is honest about being
    a knob is not a defect -- `9_Survivor_and_VA.py` has carried one the whole
    time -- so the rule is that every raw widget left standing carries the
    phrase.
    """
    unlabelled = [(kind, label) for kind, label, helptext in _raw_widgets(page)
                  if WHATIF_PHRASE not in helptext and "WHATIF" not in helptext]
    assert not unlabelled, (
        f"{page} still has widgets that are seeded, discarded and silent about "
        f"it: {unlabelled}. Either write the answer back through a ui.panel "
        f"helper, or say it is a what-if.")


@pytest.mark.parametrize("page", PAGES)
def test_the_what_if_wording_is_visible_and_not_only_in_a_tooltip(page):
    """
    `help=` is a tooltip, and a tooltip is not a label. Each card holding a
    what-if also carries a caption saying so, so the reader is told without
    hovering.
    """
    src = (ROOT / "pages" / page).read_text(encoding="utf-8")
    assert "WHATIF_CARD" in src, f"{page} labels knobs only in tooltips"
    assert "nothing on this card is saved to your plan" in src.lower()


@pytest.mark.parametrize("page", PAGES)
def test_a_page_never_asks_the_same_question_twice(page):
    """
    `11_Separation_and_Insurance.py` asked "How old will you be when you
    separate?" twice, in two cards, with two keys -- two answers to one
    question, and the insurance half quietly used the second. R3 inside a
    single page.
    """
    labels = [label for _, label, _ in _raw_widgets(page)]
    dupes = {l for l in labels if isinstance(l, str) and labels.count(l) > 1}
    assert not dupes, f"{page} asks {dupes} more than once"


# ==========================================================================
# The fields that had to be added, and what reads them
# ==========================================================================

NEW_FIELDS = ("high_3_monthly_override", "dod_disability_rating",
              "disability_combat_related",
              "disability_incurred_in_combat_zone", "on_tdrl")


def test_the_new_fields_round_trip_through_storage():
    h = Household()
    m = h.member
    m.high_3_monthly_override = 7_412.50
    m.dod_disability_rating = 30
    m.disability_combat_related = True
    m.disability_incurred_in_combat_zone = True
    m.on_tdrl = True

    back = storage.from_upload_bytes(storage.to_download_bytes(h))
    assert back.member.high_3_monthly_override == pytest.approx(7_412.50)
    assert back.member.dod_disability_rating == 30
    assert back.member.disability_combat_related is True
    assert back.member.disability_incurred_in_combat_zone is True
    assert back.member.on_tdrl is True


@pytest.mark.parametrize("field", NEW_FIELDS)
def test_a_plan_saved_before_these_fields_existed_still_loads(field):
    """
    §10: there is no versioned migration in this codebase, and tolerating a
    missing key IS the mechanism. Every plan written before this work carries
    none of these keys and must load at the declared default.
    """
    payload = Household().to_dict()
    payload["member"].pop(field)
    back = Household.from_dict(payload)
    assert getattr(back.member, field) == getattr(ServiceMember(), field)


@pytest.mark.parametrize("sample", SAMPLES)
def test_both_sample_plans_still_load(sample):
    h = storage.from_upload_bytes((ROOT / "samples" / sample).read_bytes())
    assert isinstance(h, Household)
    for field in NEW_FIELDS:
        assert getattr(h.member, field) == getattr(ServiceMember(), field)


def test_the_high_three_override_follows_the_house_convention():
    """
    The same rule as `taxable.resolve_basic_monthly()`: what the member typed
    wins, the published table is the fallback, and 0.0 means "use the table".
    Both pages read it through `high_3_monthly()` rather than raw, which is
    what stops the two disagreeing.
    """
    m = ServiceMember()
    assert m.high_3_monthly(5_000.0) == pytest.approx(5_000.0)
    m.high_3_monthly_override = 6_250.0
    assert m.high_3_monthly(5_000.0) == pytest.approx(6_250.0)
    m.high_3_monthly_override = 0.0
    assert m.high_3_monthly(0.0) == pytest.approx(0.0)

    for page in ("8_Retirement.py", "11_Separation_and_Insurance.py"):
        src = (ROOT / "pages" / page).read_text(encoding="utf-8")
        assert "m.high_3_monthly(" in src, f"{page} reads the override raw"


def test_the_dod_rating_is_not_the_va_rating():
    """
    The help text on the page says the two routinely differ, and the model has
    to agree with it or the page is lying. A board that rates a member 30% for
    the unfitting condition says nothing about the VA's schedular rating.
    """
    m = ServiceMember()
    m.dod_disability_rating = 30
    assert m.va_rating == 0


def test_the_brs_question_is_derived_from_diems_not_from_the_opt_in_flag():
    """
    The Medical Separation page used to ask "Are you in the Blended Retirement
    System?" seeded from `opted_into_brs`, which is only the 2018 opt-in
    election. Anyone with a DIEMS date of 2018 or later is in BRS without ever
    opting in, so the widget opened on "no". The DIEMS date decides, and
    nothing else does.

    The flag feeds the Chapter 61 disability RETIRED PAY multiplier, not the
    severance — `disability_separation.py` uses a flat 2.0 for severance and
    never reads `is_brs`. See FUNNEL_CONTRACT.md §14 for why the error is
    currently worth nothing and will be worth real money from about 2038;
    `test_the_brs_mis_seed_is_inert_today_and_bites_later` below pins both.
    """
    from engine.profile import SYS_BRS
    m = ServiceMember(diems_date="2020-01-01", opted_into_brs=False)
    assert m.retirement_system == SYS_BRS

    src = (ROOT / "pages" / "11_Separation_and_Insurance.py").read_text(
        encoding="utf-8")
    assert "m.retirement_system == SYS_BRS" in src
    assert 'wkey("dsbrs")' not in src


# ==========================================================================
# The pages still run
# ==========================================================================

@pytest.mark.parametrize("page", PAGES)
@pytest.mark.parametrize("sample", SAMPLES)
def test_the_page_still_renders_for_both_samples(page, sample):
    h = storage.from_upload_bytes((ROOT / "samples" / sample).read_bytes())
    at = AppTest.from_file(str(ROOT / "pages" / page), default_timeout=180)
    at.session_state["household"] = h
    at.session_state["plan_version"] = 0
    at.run()
    assert not at.exception, at.exception


@pytest.mark.parametrize("page", PAGES)
def test_the_page_still_renders_for_an_empty_plan(page):
    at = AppTest.from_file(str(ROOT / "pages" / page), default_timeout=180)
    at.session_state["household"] = Household()
    at.session_state["plan_version"] = 0
    at.run()
    assert not at.exception, at.exception


def test_the_brs_mis_seed_is_inert_today_and_bites_later():
    """
    The size of the error the BRS fix closes, pinned so the claim cannot drift
    a third time. It was first described as a severance error at 2.5% against
    2.0%; severance never reads the flag at all.

    `is_brs` feeds the Chapter 61 retired-pay multiplier, and Chapter 61 pays
    the GREATER of that and the DoD rating. A post-2018 member — the only
    mis-seeded population — has at most nine years of service, needs a 30%
    rating to qualify at that length, and 30% beats 8 x 2.5%. So the rating
    binds, both seeds agree, and the difference is zero. At twenty years it is
    not.
    """
    from engine.benefits import disability_separation as DS

    assert DS.SEVERANCE_MULTIPLIER == 2.0, "severance is a flat multiple"

    short = dict(dod_rating=30, years_of_service=8.0, high_three_monthly=5000.0,
                 age_at_separation=30, life_expectancy=85)
    assert (DS.evaluate(is_brs=False, **short).retired_pay_monthly
            == DS.evaluate(is_brs=True, **short).retired_pay_monthly), \
        "at eight years the rating binds, so the mis-seed costs nothing today"
    assert (DS.evaluate(is_brs=False, **short).severance_gross
            == DS.evaluate(is_brs=True, **short).severance_gross)

    long = dict(short, years_of_service=20.0)
    legacy = DS.evaluate(is_brs=False, **long)
    brs = DS.evaluate(is_brs=True, **long)
    assert legacy.multiplier_used > brs.multiplier_used, \
        "at twenty years length of service binds and the seed decides money"
    assert legacy.lifetime_present_value > brs.lifetime_present_value


# ==========================================================================
# The tidy-up must not overwrite a real answer
# ==========================================================================
# Both pages adopt the member's own longevity when `career.separation_at_
# years_of_service` is still at its declared 20.0 default and they have served
# longer. That is right for a plan nobody has answered, and `career.entered` is
# what tells the two apart -- the flag added in round two for exactly this.
#
# Both pages READ the flag. Neither SET it, so a member who has served 21 years
# and genuinely means to go at 20 typed 20, had it stored, and had 21 put back
# on the next render. Silently, because the tidy-up is not an edit.

@pytest.mark.parametrize("page,key", [
    ("8_Retirement.py", "retyos__v0"),
    ("11_Separation_and_Insurance.py", "dsyos__v0"),
])
def test_a_separation_point_typed_on_either_page_survives_the_next_render(page, key):
    from streamlit.testing.v1 import AppTest
    from engine.career import timeline as TL

    def plan():
        h = Household(member=ServiceMember(component=ACTIVE, grade="E-7",
                                           years_of_service=21.0,
                                           birth_year=1980,
                                           diems_date="2005-01-01"))
        h.career = TL.CareerTimeline()          # untouched: entered False, 20.0
        return h

    h = plan()
    at = AppTest.from_file(str(ROOT / "pages" / page), default_timeout=300)
    at.session_state["household"] = h
    at.session_state["plan_version"] = 0
    at.run()
    assert not at.exception, at.exception
    # The tidy-up fired, because nobody has answered.
    assert h.career.separation_at_years_of_service == 21.0
    assert h.career.entered is False

    # Now the member answers, meaning it.
    at.number_input(key=key).set_value(20.0).run()
    after = at.session_state["household"]
    assert after.career.entered is True, "typing an answer must mark it entered"

    # And it survives a revisit.
    again = AppTest.from_file(str(ROOT / "pages" / page), default_timeout=300)
    again.session_state["household"] = after
    again.session_state["plan_version"] = 0
    again.run()
    assert after.career.separation_at_years_of_service == 20.0, \
        "the tidy-up overwrote a real answer"


def test_the_tidy_up_still_fixes_a_plan_nobody_has_answered():
    """The behaviour the guard exists for, kept: a 26-year member is not
    priced against a twenty-year pension just because nobody opened Career."""
    from streamlit.testing.v1 import AppTest
    from engine.career import timeline as TL

    h = Household(member=ServiceMember(component=RETIRED, grade="O-5",
                                       years_of_service=26.0, birth_year=1975,
                                       diems_date="1999-05-15"))
    h.career = TL.CareerTimeline()
    at = AppTest.from_file(str(ROOT / "pages" / "8_Retirement.py"),
                           default_timeout=300)
    at.session_state["household"] = h
    at.session_state["plan_version"] = 0
    at.run()
    assert not at.exception, at.exception
    assert h.career.separation_at_years_of_service == 26.0


# ==========================================================================
# A side-effect fires on an edit, never on a render
# ==========================================================================

def test_opening_the_taxes_page_does_not_re_employ_a_spouse():
    """
    `income/spouse.py` returns nothing unless `employed` is set, so a wage
    typed on Taxes with the flag off would be read back as zero. Setting the
    flag is right; setting it merely because the page was OPENED is not.

    A spouse who stopped working is marked not employed on the Career page
    while last year's figure is still on the plan. Re-employing them on render
    resurrects dead income into every projection that reads spouse.py.
    """
    from streamlit.testing.v1 import AppTest
    from engine.income.spouse import SpouseIncome

    h = Household(member=ServiceMember(component=ACTIVE, grade="E-6",
                                       birth_year=1990))
    h.has_spouse = True
    h.spouse = ServiceMember(birth_year=1991)
    h.spouse_income = SpouseIncome(employed=False, annual_income=45_000.0)

    at = AppTest.from_file(str(ROOT / "pages" / "22_This_Years_Taxes.py"),
                           default_timeout=300)
    at.session_state["household"] = h
    at.session_state["plan_version"] = 0
    at.run()
    assert not at.exception, at.exception
    assert at.session_state["household"].spouse_income.employed is False


def test_typing_a_spouse_wage_on_taxes_still_marks_them_employed():
    """The other half: without the flag the figure would be discarded."""
    from streamlit.testing.v1 import AppTest
    from engine.income.spouse import SpouseIncome

    h = Household(member=ServiceMember(component=ACTIVE, grade="E-6",
                                       birth_year=1990))
    h.has_spouse = True
    h.spouse = ServiceMember(birth_year=1991)
    h.spouse_income = SpouseIncome(employed=False, annual_income=0.0)

    at = AppTest.from_file(str(ROOT / "pages" / "22_This_Years_Taxes.py"),
                           default_timeout=300)
    at.session_state["household"] = h
    at.session_state["plan_version"] = 0
    at.run()
    at.number_input(key="cy_spousewage__v0").set_value(52_000.0).run()

    after = at.session_state["household"]
    assert after.spouse_income.annual_income == 52_000.0
    assert after.spouse_income.employed is True


# ==========================================================================
# A shared field asks the question the field holds (FUNNEL_CONTRACT.md §14)
# ==========================================================================

def test_the_insurance_worksheet_asks_for_the_mortgage_balance_it_writes():
    """
    §14's second defect condition, third occurrence. The card is a sizing
    worksheet and everything on it is page-local EXCEPT the mortgage, which
    writes `h.mortgage_balance` and is read by Accounts, Housing and net worth.

    Asking "what would it clear?" there invited a member modelling partial
    cover to rewrite their balance sheet. The field is shared, so the label
    asks the shared question and the worksheet's use of it moves to the help.
    """
    src = (ROOT / "pages" / "11_Separation_and_Insurance.py").read_text(
        encoding="utf-8")
    assert 'money("What is your mortgage balance?"' in src
    assert 'money("What mortgage balance would it clear?"' not in src
    # And the caption the member actually reads says the exception BEFORE the
    # blanket denial, so skimming the first clause cannot mislead.
    from streamlit.testing.v1 import AppTest

    h = Household(member=ServiceMember(component=ACTIVE, grade="E-6",
                                       birth_year=1990, years_of_service=8.0))
    at = AppTest.from_file(str(ROOT / "pages" / "11_Separation_and_Insurance.py"),
                           default_timeout=300)
    at.session_state["household"] = h
    at.session_state["plan_version"] = 0
    at.run()
    assert not at.exception, at.exception

    caption = next(c.value for c in at.caption
                   if "sizing worksheet" in (c.value or ""))
    assert caption.index("saved to your plan") < caption.index("what-if"), \
        "the blanket denial comes first and a skimmer is misled"
