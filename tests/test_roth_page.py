"""
Tests for the Roth conversion page and the Household -> engine adapter.

The conversion engine has its own, much larger, input object, and everything
the app knows has to be carried across engine/retirement/roth_bridge.py to
reach it. Two classes of mistake live in that crossing and neither shows up as
an exception:

  * a unit. Household.Assumptions carries percentages, roth_profile.Assumptions
    carries decimals, so a rate that crosses unconverted is off by a hundred;
  * a vocabulary. The plan-wide tax scenarios, the retirement systems and the
    state names are all named twice, and a second definition that drifts models
    a different future from the one the rest of the app describes.

So the adapter is asserted against the retiree sample's real figures rather
than against itself, and the page is rendered headlessly against both samples
-- the retiree, who has a large traditional balance and a real conversion
decision, and the active-duty E-5, who has neither.
"""

import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import re
import pytest

from engine import assumptions as A
from engine import roth_profile as RP
from engine import storage
from engine.profile import Household
from engine.retirement import roth_bridge as RB
from engine.retirement.roth_analysis import compare, sweep_tax_scenarios
from engine.roth_profile import ConversionPlan, validate
from engine.briefing import build_briefing, BriefingOptions
from engine.tax import state as ST
from engine.tax import tables as T
from ui.panel import PROFILE_KEY, VERSION_KEY, DIRTY_KEY

PAGE = ROOT / "pages" / "14_Roth_Conversions.py"
SOURCE = PAGE.read_text(encoding="utf-8")

RETIREE = "retired_o5_26yrs.mpfplan.json"
ACTIVE = "e5_6yrs_brs.mpfplan.json"

# Pinned so the figures do not move under the tests when the calendar does.
YEAR = 2026


def load(name: str) -> Household:
    """A plan file, read exactly the way the sidebar's uploader reads one."""
    return storage.from_upload_bytes((ROOT / "samples" / name).read_bytes())


def retiree_profile():
    return RB.to_roth_profile(load(RETIREE), start_year=YEAR)


# ==========================================================================
# The adapter: a retiree
# ==========================================================================

def test_the_adapter_maps_the_retiree_household_onto_the_engine():
    h = load(RETIREE)
    p = RB.to_roth_profile(h, start_year=YEAR)

    assert p.profile_name == h.profile_name
    assert p.filing_status == T.MFJ and p.has_spouse is True
    assert p.state == "Michigan"

    # The retirement system is named differently on each side of the bridge.
    assert h.member.retirement_system == "High-3"
    assert p.military.system == RP.SYS_HIGH3 == "High-3 (Legacy)"

    assert p.military.retired_pay_monthly == pytest.approx(8_056.62)
    assert p.military.years_of_service == 26.0
    assert p.military.retirement_year == 2025          # DIEMS 1999 + 26 years
    assert p.military.va_disability_monthly == 4_050.0
    assert p.military.va_rating == 100 and p.military.va_permanent_and_total
    assert p.military.crdp_applies is True
    assert p.military.sbp_elected is True
    assert p.military.cola_real_drift == 0.0           # High-3 on a full COLA
    assert p.military.has_tricare is True
    assert p.military.tricare_annual_cost == RP.MilitaryRetirement().tricare_annual_cost

    assert p.primary.birth_year == 1975
    assert p.primary.traditional_balance == 880_000.0  # 700k TSP + 180k IRA
    assert p.primary.roth_balance == 145_000.0         # 100k TSP + 45k IRA
    assert p.primary.annual_wages == 95_000.0          # a retiree's second career
    assert p.primary.traditional_contribution == 0.0   # no longer serving
    assert p.primary.roth_contribution == 0.0
    assert p.primary.death_age == 87                   # life expectancy + 5

    # No spouse record on the file, so the spouse is the member's contemporary
    # and carries the spouse income from the Career page.
    assert p.spouse.birth_year == 1975
    assert p.spouse.annual_wages == 52_000.0
    assert p.spouse.traditional_contribution == pytest.approx(52_000 * (0.06 + 0.03))
    assert p.spouse.traditional_balance == 0.0

    assert p.taxable.balance == 250_000.0
    assert p.taxable.cash_balance == 60_000.0
    assert p.taxable.cost_basis == p.taxable.balance   # no embedded gain assumed

    # Percentages become decimals here, and only here.
    assert p.assumptions.inflation == pytest.approx(0.025)
    assert p.assumptions.real_return_traditional == pytest.approx(0.04)
    assert p.assumptions.real_return_roth == pytest.approx(0.04)
    assert p.assumptions.discount_rate == pytest.approx(0.03)
    assert p.assumptions.start_year == YEAR
    assert p.assumptions.annual_spending == 108_000.0  # $9,000 a month, no extras

    assert p.conversion.enabled is True
    assert p.conversion.strategy == ConversionPlan.STRATEGY_BRACKET
    assert p.conversion.start_year == YEAR
    assert p.conversion.end_year == 2049               # the year before the first RMD
    assert p.conversion.pay_tax_from_taxable is True   # there is a taxable account

    assert p.heirs.n_beneficiaries == 2                # from n_dependents
    assert p.heirs.heir_state_rate == pytest.approx(ST.get_rule("Michigan").rate)
    assert p.survivorship.dic_applies is True          # 100% permanent and total
    assert p.survivorship.sbp_dic_offset is False      # repealed in 2023
    assert p.monte_carlo.n_paths == RB.DEFAULT_MC_PATHS

    assert validate(p) == []


def test_the_retiree_defaults_are_derived_from_the_plan_not_invented():
    d = RB.default_inputs(load(RETIREE), YEAR)
    assert d.start_year == YEAR
    assert d.wages_annual == 95_000.0
    assert d.work_through_year == 2040                 # age 65
    assert d.death_age == 87                          # life expectancy + 5
    assert d.spouse_birth_year == 1975
    assert d.conversion_start_year == YEAR
    assert d.conversion_end_year == 2049
    assert d.pay_tax_from_taxable is True
    assert d.dic_applies is True
    assert d.n_beneficiaries == 2
    assert d.mc_paths <= RB.MAX_MC_PATHS


def test_describe_reports_what_the_engine_was_actually_given():
    rows = dict(RB.describe(retiree_profile()))
    assert rows["Filing status"] == T.MFJ
    assert rows["Retirement system"] == RP.SYS_HIGH3
    assert "$96,679/yr" in rows["Retired pay, gross"]   # 8,056.62 x 12
    assert "SBP elected" in rows["Retired pay, gross"]
    assert rows["Traditional (TSP + IRA)"] == "$880,000"
    assert rows["Roth (TSP + IRA)"] == "$145,000"
    assert "Michigan" in rows["State of legal residence"]
    assert "exempt" in rows["State of legal residence"]  # military pension


# ==========================================================================
# The adapter: someone still serving, whose pension has not started
# ==========================================================================

def test_an_active_duty_household_with_no_retired_pay_still_yields_valid_inputs():
    h = load(ACTIVE)
    assert h.member.retired_pay_monthly == 0.0

    d = RB.default_inputs(h, YEAR)
    assert isinstance(d, RB.RothInputs)
    assert d.wages_annual == pytest.approx(49_320.0)   # basic pay; the special
                                                       # pay on this file is not
                                                       # taxable, and BAH is never
    assert d.death_age > YEAR - h.member.birth_year    # not already in the past
    assert d.conversion_start_year <= d.conversion_end_year
    assert d.conversion_end_year == 2073               # the year before the first RMD
    assert d.spouse_traditional_balance == 0.0
    assert d.to_dict()["strategy"] == ConversionPlan.STRATEGY_BRACKET

    p = RB.to_roth_profile(h, d)
    # This used to be 0: the engine had no way to say "a pension that has not
    # started yet", so a serving member was given none at all. ARCHITECTURE §7
    # step 4 ends that refusal. The figure is priced off the career timeline --
    # 40% of a $4,421.70 high-3 at twenty years under BRS -- and it is paid
    # from the year AFTER separation, never a year before.
    assert p.military.retired_pay_monthly == pytest.approx(1_768.68, abs=0.01)
    assert p.military.pension_start_year == 2041       # separates at 20 in 2040
    assert p.military.system == RP.SYS_BRS
    assert p.military.va_disability_monthly == 0.0
    assert p.state == "Texas"
    assert p.primary.traditional_balance == 9_000.0
    assert p.primary.roth_balance == 18_500.0          # 14k TSP + 4.5k IRA
    # An all-Roth election: the member's own money is Roth, the service's is not.
    assert p.primary.roth_contribution == pytest.approx(49_320 * 0.03)
    assert p.primary.traditional_contribution == pytest.approx(49_320 * 0.04)
    assert validate(p) == []

    c = compare(p)
    assert c.base.rows and c.conv.rows


def test_an_empty_household_still_produces_a_runnable_profile():
    """What the page gets before anyone has loaded or typed anything."""
    p = RB.to_roth_profile(Household(), start_year=YEAR)
    assert p.primary.traditional_balance == 0.0
    c = compare(p)
    assert c.base.rows and c.conv.rows

    # validate() is where the page gets the warnings it shows, and it reads the
    # opening balance only -- a default household is serving under BRS, so the
    # service's contributions build a traditional balance to convert even
    # though there is not a dollar in one today. The page's own guard asks
    # about the conversions as well, which is why it does not claim the two
    # futures are identical here.
    assert any("No traditional balance" in i for i in validate(p))
    assert c.conv.lifetime_conversions > 0


# ==========================================================================
# The analysis, end to end
# ==========================================================================

def test_the_analysis_returns_both_futures_and_the_no_convert_path_keeps_more_pre_tax():
    p = retiree_profile()
    c = compare(p)
    base, conv = c.base, c.conv

    assert base.rows and conv.rows
    assert len(base.rows) == len(conv.rows)
    assert base.rows[0].year == YEAR
    assert conv.lifetime_conversions > 0

    # The whole point of the comparison: leaving it alone leaves more in the
    # pre-tax account at death, and pays more of it out as RMDs on the way.
    assert base.ending_traditional > conv.ending_traditional
    assert base.lifetime_rmds > conv.lifetime_rmds
    assert base.heir_tax_paid > conv.heir_tax_paid

    assert c.tax_saved == pytest.approx(base.lifetime_total_tax - conv.lifetime_total_tax)
    assert c.legacy_gain == pytest.approx(conv.heir_value_total - base.heir_value_total)
    assert c.converting_wins is (c.legacy_gain > 0)
    assert c.findings and all(f.severity in ("good", "warn", "bad", "info")
                              for f in c.findings)


def test_the_retiree_sample_answer_is_stable():
    """
    The figures the page puts on screen for the retiree sample. Pinned so a
    change in the adapter or the engine has to be looked at rather than
    absorbed.
    """
    c = compare(retiree_profile())
    base, conv = c.base, c.conv

    # Re-pinned when the published SSA life table replaced the built-in
    # approximation: it puts this member's death at 87 rather than 86, and one
    # extra year moved the case for converting by half. Longer life means more
    # RMD years, so leaving the balance alone costs more -- the conversion
    # advantage grew from $28,954 to $43,482 on that single year.
    # Re-pinned again when the published IRMAA tiers replaced the derived
    # ones: a Part B premium a dime different in three tiers, compounded
    # over 30 years of two people, moves lifetime tax by about $1,000.
    assert base.lifetime_total_tax == pytest.approx(2_136_682.63, rel=1e-6)
    assert conv.lifetime_total_tax == pytest.approx(2_147_058.82, rel=1e-6)
    assert base.heir_value_total == pytest.approx(11_400_863.36, rel=1e-6)
    assert conv.heir_value_total == pytest.approx(11_444_034.89, rel=1e-6)
    assert base.ending_traditional == pytest.approx(1_964_667.09, rel=1e-6)
    assert conv.ending_traditional == pytest.approx(524_182.89, rel=1e-6)
    assert base.lifetime_rmds == pytest.approx(1_546_478.90, rel=1e-6)
    assert conv.lifetime_rmds == pytest.approx(412_608.22, rel=1e-6)
    assert conv.lifetime_conversions == pytest.approx(1_398_635.30, rel=1e-6)

    # Converting costs this household MORE tax in life and still wins, because
    # what it saves is the tax the heirs would have paid.
    assert c.tax_saved < 0
    assert c.legacy_gain > 0


# ==========================================================================
# Future tax law
# ==========================================================================

def test_each_tax_scenario_produces_a_different_lifetime_tax():
    sweep = sweep_tax_scenarios(retiree_profile(), RB.scenario_policies())
    assert [r["scenario"] for r in sweep] == RB.TAX_SCENARIOS

    for key in ("tax_no_convert", "tax_convert"):
        taxes = [round(r[key], 2) for r in sweep]
        assert len(set(taxes)) == len(RB.TAX_SCENARIOS), (key, taxes)

    current = sweep[0]
    assert current["scenario"] == RB.TAX_CURRENT
    for r in sweep[1:]:
        # Both futures pay more when rates rise; the question is which pays
        # more MORE, and that is what legacy_gain answers.
        assert r["tax_no_convert"] > current["tax_no_convert"]
        assert r["tax_convert"] > current["tax_convert"]


def test_the_plan_wide_scenario_reaches_the_engine_with_the_app_wide_meaning():
    h = load(RETIREE)
    for name in RB.TAX_SCENARIOS:
        h.assumptions.tax_scenario = name
        p = RB.to_roth_profile(h, start_year=YEAR)
        assert p.tax_policy.scenario == A.tax_scenarios[name].federal_scenario

    # "Higher" has to mean the same number of points here as it does on the
    # Assumptions page, which is where the user was shown the bracket table.
    assert RB.TAX_SCENARIOS == A.TAX_SCENARIOS
    assert RB.DEFAULT_SURCHARGE_POINTS == A.HIGHER_POINTS
    h.assumptions.tax_scenario = RB.TAX_HIGHER
    assert RB.to_roth_profile(h, start_year=YEAR).tax_policy.surcharge_points \
        == A.HIGHER_POINTS

    # An unknown name is current law, not a crash.
    h.assumptions.tax_scenario = "whatever Congress does"
    assert RB.to_roth_profile(h, start_year=YEAR).tax_policy.scenario \
        == A.tax_scenarios[A.TAX_CURRENT].federal_scenario


def test_the_page_dials_override_the_scenario_defaults():
    policy = RB.tax_policy_for(RB.TAX_HIGHER, change_year=2031, surcharge_points=8.0)
    assert policy.change_year == 2031 and policy.surcharge_points == 8.0
    # The surcharge dial means nothing under a schedule that is not a surcharge.
    assert RB.tax_policy_for(RB.TAX_SUNSET, 2031, 8.0).surcharge_points == 0.0


# ==========================================================================
# The state resolver
# ==========================================================================

@pytest.mark.parametrize("typed, resolved, known", [
    ("Michigan", "Michigan", True),          # a full name
    ("  Texas  ", "Texas", True),            # a full name, typed carelessly
    ("california", "California", True),      # a full name, lower case
    ("MI", "Michigan", True),                # an abbreviation
    ("mi", "Michigan", True),                # an abbreviation, lower case
    ("Freedonia", "Freedonia", False),       # not a state
    ("Micigan", "Micigan", False),           # a typo, which is not a state either
    ("", "", False),                         # nothing entered
])
def test_the_state_resolver(typed, resolved, known):
    assert RB.resolve_state(typed) == resolved
    assert RB.state_is_known(RB.resolve_state(typed)) is known


def test_an_unresolved_state_is_taxed_as_nothing_which_is_why_it_is_flagged():
    # This is the trap the resolver exists to contain: the engine's table
    # answers a no-income-tax rule for anything it does not recognise, so a
    # typo would otherwise become a tax-free conversion in silence.
    assert ST.get_rule("Freedonia").rate == 0.0
    assert not RB.state_is_known("Freedonia")

    h = load(RETIREE)
    h.state_of_legal_residence = "Freedonia"
    p = RB.to_roth_profile(h, start_year=YEAR)
    assert p.state == "Freedonia"
    assert "not in the state table" in dict(RB.describe(p))["State of legal residence"]


def test_every_abbreviation_resolves_to_a_state_the_engine_knows():
    unknown = {ab: name for ab, name in RB.STATE_ABBREVIATIONS.items()
               if not RB.state_is_known(name)}
    assert unknown == {}


# ==========================================================================
# The page
# ==========================================================================

def render(sample: str | None = None, household: Household | None = None,
           version: int = 0):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(PAGE), default_timeout=180)
    if sample is not None or household is not None:
        at.session_state[PROFILE_KEY] = household or load(sample)
        at.session_state[VERSION_KEY] = version
    at.run()
    assert not at.exception, at.exception
    return at


@pytest.mark.parametrize("sample", [RETIREE, ACTIVE])
def test_the_page_renders_against_both_samples(sample):
    at = render(sample)
    assert "Roth Conversions" in at.title[0].value

    labels = [m.label for m in at.metric]
    for expected in ("Lifetime tax — don't convert", "Lifetime tax — convert",
                     "To heirs after tax — don't convert",
                     "To heirs after tax — convert", "Total converted"):
        assert expected in labels, expected

    # One headline verdict, and the findings underneath it.
    assert len(at.success) + len(at.error) >= 1
    body = " ".join(md.value for md in at.markdown)
    assert "Roth Conversions" not in body            # that is the title, not a card
    assert any(icon in body for icon in ("✅", "⚠️", "🚨", "💡"))


def test_the_page_renders_with_no_plan_loaded():
    """A user who opens the page before loading or typing anything."""
    at = render()
    assert isinstance(at.session_state[PROFILE_KEY], Household)


@pytest.mark.parametrize("version", [0, 7])
def test_every_widget_key_is_namespaced_to_the_loaded_plan(version):
    at = render(RETIREE, version=version)
    widgets = (list(at.number_input) + list(at.selectbox) + list(at.slider)
               + list(at.select_slider) + list(at.toggle) + list(at.button)
               + list(at.get("download_button")))
    assert len(widgets) >= 20
    for w in widgets:
        assert w.key, f"{w.type} has no key"
        assert w.key.endswith(f"__v{version}"), w.key


# A question, not a field name: "What year would you start converting?" rather
# than "Conversion start year". These are the openers the page's questions use.
QUESTION_OPENERS = {"what", "which", "how", "when", "would", "will", "is", "are",
                    "do", "does", "should", "can", "in", "leave", "round", "append"}


def test_every_input_asks_a_question_rather_than_naming_a_field():
    labels = set()
    for strategy in RB.STRATEGIES:                 # the conditional widgets too
        at = render(RETIREE)
        at.selectbox(key="rc_strategy__v0").set_value(strategy).run()
        assert not at.exception, at.exception
        labels.update(w.label for w in
                      (list(at.number_input) + list(at.selectbox) + list(at.slider)
                       + list(at.select_slider) + list(at.toggle)))

    assert len(labels) >= 25
    for label in labels:
        assert "?" in label, label
        assert label.split()[0].lower() in QUESTION_OPENERS, label


@pytest.mark.parametrize("sample", [RETIREE, ACTIVE])
def test_prose_carrying_a_dollar_figure_is_escaped_for_markdown(sample):
    at = render(sample)
    prose = [a.value for a in (list(at.success) + list(at.error)
                               + list(at.warning) + list(at.info))]
    prose += [md.value for md in at.markdown]
    assert any(r"\$" in t for t in prose), "no escaped money found at all"
    for t in prose:
        assert not re.search(r"(?<!\\)\$", t), t


def test_the_plan_wide_tax_scenario_is_written_back_into_the_household():
    at = render(RETIREE)
    at.selectbox(key="rc_taxscen__v0").set_value(RB.TAX_SUNSET).run()
    assert not at.exception, at.exception
    assert at.session_state[PROFILE_KEY].assumptions.tax_scenario == RB.TAX_SUNSET
    assert at.session_state[DIRTY_KEY] is True
    # The change year only appears once there is a change to date.
    assert "rc_chyear__v0" in [n.key for n in at.number_input]


@pytest.mark.parametrize("strategy", RB.STRATEGIES)
def test_every_conversion_strategy_renders(strategy):
    at = render(RETIREE)
    at.selectbox(key="rc_strategy__v0").set_value(strategy).run()
    assert not at.exception, at.exception


def test_a_generous_planning_margin_does_not_take_the_page_down():
    """
    Regression. The Assumptions page lets the planning margin run to thirty
    years; on top of an older member's life expectancy that produced a death
    age past the age input's ceiling, and Streamlit refuses an out-of-range
    value rather than clamping it.
    """
    for margin in (-10, 0, 5, 15, 30):
        h = load(RETIREE)
        h.member.birth_year = 1930
        h.assumptions.planning_margin_years = margin
        d = RB.default_inputs(h, YEAR)
        assert d.death_age <= RB.MAX_PLANNING_AGE
        assert d.spouse_death_age <= RB.MAX_PLANNING_AGE
        render(household=h)


def test_the_monte_carlo_waits_to_be_asked_and_is_capped():
    at = render(RETIREE)
    assert "mc_summary" not in at.session_state
    assert any("Run the Monte Carlo" in i.value for i in at.info)

    paths = at.slider(key="rc_paths__v0")
    assert paths.max == RB.MAX_MC_PATHS
    assert RB.MAX_MC_PATHS <= 500

    at.slider(key="rc_paths__v0").set_value(50).run()
    at.button(key="rc_runmc__v0").click().run()
    assert not at.exception, at.exception

    stored = at.session_state["mc_summary"]
    assert stored["summary"].n_paths == 50
    assert stored["summary"].legacy_delta.size == 50
    labels = [m.label for m in at.metric]
    assert "Converting leaves heirs more in" in labels

    # Change an input and the stored run is marked stale rather than reused.
    at.number_input(key="rc_cend__v0").set_value(2040).run()
    assert not at.exception, at.exception
    assert any("earlier inputs" in w.value for w in at.warning)


def test_the_path_cap_is_enforced_on_the_profile_not_only_on_the_slider():
    p = RB.to_roth_profile(load(RETIREE),
                           RB.RothInputs(start_year=YEAR, mc_paths=100_000))
    assert p.monte_carlo.n_paths == RB.MAX_MC_PATHS


def test_the_page_offers_the_briefing_as_a_download():
    at = render(RETIREE)
    buttons = list(at.get("download_button"))
    assert len(buttons) == 1
    assert "briefing" in buttons[0].label.lower()
    assert buttons[0].key == "rc_download__v0"

    md = build_briefing(retiree_profile(), compare(retiree_profile()),
                        BriefingOptions(anonymize=True))
    assert md.lstrip().startswith("#")
    for expected in ("Roth", "conversion", "RMD"):
        assert expected in md, expected


def test_the_page_keeps_to_the_house_style():
    assert "st.set_page_config" not in SOURCE       # the router owns that
    assert "st.columns" not in SOURCE               # two_pane and metric_row instead
    assert "format=None" not in SOURCE              # invalid in Altair 6
    assert SOURCE.count("two_pane()") == 1
    assert "page_header(" in SOURCE
    assert "render_findings(" in SOURCE
    assert SOURCE.count("metric_row(") >= 3
    assert SOURCE.count("input_card(") >= 5
    assert "Ask an LLM about this" in SOURCE
    assert "st.download_button(" in SOURCE


def test_the_questions_are_on_the_left_and_the_answers_are_on_the_right():
    left = SOURCE.index("with inputs:")
    right = SOURCE.index("with results:")
    assert left < right
    assert all(left < i < right
               for i in (m.start() for m in re.finditer(r"with input_card\(", SOURCE)))
    assert all(i > right
               for i in (m.start() for m in re.finditer(r"with section\(", SOURCE)))
    # One widget per row inside a card: no column split anywhere on the page.
    assert "st.columns" not in SOURCE
