"""
Tests for the estate and gifting engine, and the page that shows it.

The load-bearing claims here are that a funded account with no current
beneficiary designation is a CRISIS rather than a note, that the difference
between leaving a traditional balance and leaving a Roth balance is exactly
the heir's marginal rate, and that the gifting schedule the page prints
actually reaches the number the user asked for.
"""

import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from engine import storage
from engine.estate import planning as EP
from engine.profile import Household, ServiceMember, ACTIVE, RETIRED
from ui.panel import PROFILE_KEY, VERSION_KEY, DIRTY_KEY

PAGE = ROOT / "pages" / "20_Estate_and_Gifting.py"
SAMPLES = [ROOT / "samples" / "retired_o5_26yrs.mpfplan.json",
           ROOT / "samples" / "e5_6yrs_brs.mpfplan.json"]

CURRENT_YEAR = 2026


def _household(**kw) -> Household:
    """A household with one funded account and nothing else, unless asked."""
    m = ServiceMember(birth_year=1980, sex="Male", component=ACTIVE,
                      tsp_traditional_balance=kw.pop("tsp_traditional", 0.0),
                      tsp_roth_balance=kw.pop("tsp_roth", 0.0),
                      ira_traditional_balance=kw.pop("ira_traditional", 0.0),
                      ira_roth_balance=kw.pop("ira_roth", 0.0),
                      sgli_coverage=kw.pop("sgli", 0.0))
    h = Household(member=m)
    for k, v in kw.items():
        if hasattr(h.estate, k):
            setattr(h.estate, k, v)
        else:
            setattr(h, k, v)
    return h


def _sample(path) -> Household:
    return storage.from_upload_bytes(path.read_bytes())


# ==========================================================================
# Beneficiary designations
# ==========================================================================

def test_a_funded_account_with_no_designation_is_a_bad_finding():
    h = _household(tsp_traditional=250_000.0)
    out = EP.beneficiary_checklist(h)
    bad = [f for f in out if f.severity == "bad"]
    assert bad, "a funded TSP with no current designation must be severity bad"
    assert "Thrift Savings Plan" in bad[0].headline
    assert bad[0].dollars == pytest.approx(250_000.0)
    # It renders as the (severity, headline, detail) triple render_findings wants.
    sev, headline, detail = bad[0]
    assert sev == "bad" and headline and detail


@pytest.mark.parametrize("field,attr,label", [
    ("tsp_traditional", "tsp_beneficiary_current", "Thrift Savings Plan"),
    ("sgli", "sgli_beneficiary_current", "SGLI"),
    ("ira_roth", "ira_beneficiary_current", "IRA"),
])
def test_every_designated_account_is_checked_separately(field, attr, label):
    h = _household(**{field: 100_000.0})
    bad = [f for f in EP.beneficiary_checklist(h) if f.severity == "bad"]
    assert [f for f in bad if label in f.headline], f"{label} not flagged"

    setattr(h.estate, attr, True)
    out = EP.beneficiary_checklist(h)
    assert not [f for f in out if f.severity == "bad" and label in f.headline]
    assert [f for f in out if f.severity == "good" and label in f.headline]


def test_an_unfunded_account_is_not_flagged():
    """Nothing in it, nothing at stake. A retiree has no SGLI at all."""
    h = _household(tsp_traditional=50_000.0, component=RETIRED)
    h.member.component = RETIRED
    out = EP.beneficiary_checklist(h)
    assert not [f for f in out if "SGLI" in f.headline]
    assert not [f for f in out if "IRA:" in f.headline]


def test_the_checklist_is_ordered_by_dollars():
    h = _household(tsp_traditional=700_000.0, ira_traditional=10_000.0,
                   sgli=500_000.0)
    out = EP.beneficiary_checklist(h)
    dollars = [f.dollars for f in out]
    assert dollars == sorted(dollars, reverse=True)


def test_the_statutory_order_of_precedence_is_named_when_nothing_is_on_file():
    h = _household(tsp_traditional=100_000.0)
    detail = " ".join(f.detail for f in EP.beneficiary_checklist(h))
    assert "order of precedence" in detail
    assert EP.TSP_ORDER_OF_PRECEDENCE[0] == "Your spouse"
    assert EP.SGLI_ORDER_OF_PRECEDENCE[0] == "Your spouse"


# ==========================================================================
# What an heir receives
# ==========================================================================

def test_heir_tax_on_traditional_is_the_balance_times_the_rate():
    assert EP.heir_tax_on_traditional(400_000.0, 0.24) == pytest.approx(96_000.0)
    assert EP.heir_tax_on_traditional(0.0, 0.24) == 0.0
    assert EP.heir_tax_on_traditional(-5.0, 0.24) == 0.0
    # A rate outside [0, 1] cannot produce a nonsense answer.
    assert EP.heir_tax_on_traditional(1_000.0, 2.0) == pytest.approx(1_000.0)


@pytest.mark.parametrize("balance", [50_000.0, 700_000.0])
@pytest.mark.parametrize("rate", [0.12, 0.24, 0.37])
def test_the_roth_versus_traditional_gap_is_the_balance_times_the_heir_rate(
        balance, rate):
    """The whole estate argument for Roth conversions, in one identity."""
    trad = _household(tsp_traditional=balance)
    roth = _household(tsp_roth=balance)

    c_trad = EP.inheritance_comparison(trad, rate)
    c_roth = EP.inheritance_comparison(roth, rate)

    assert c_roth.roth_after_tax - c_trad.traditional_after_tax == \
        pytest.approx(balance * rate)
    assert c_trad.heir_tax_on_traditional == pytest.approx(balance * rate)
    assert c_roth.heir_tax_on_traditional == 0.0
    assert c_trad.gap_if_converted == pytest.approx(balance * rate)


def test_a_spouse_rolls_it_over_and_pays_no_ten_year_tax():
    h = _household(tsp_traditional=400_000.0)
    spouse = EP.inheritance_comparison(h, 0.24, spouse_inherits=True)
    assert spouse.heir_tax_on_traditional == 0.0
    assert spouse.traditional_after_tax == pytest.approx(400_000.0)
    assert "roll an inherited IRA" in " ".join(spouse.notes)


def test_taxable_gets_a_step_up_and_insurance_is_tax_free():
    h = _household(sgli=500_000.0)
    h.taxable_brokerage = 250_000.0
    c = EP.inheritance_comparison(h, 0.24)
    assert c.taxable_after_tax == pytest.approx(250_000.0)
    assert c.insurance_after_tax == pytest.approx(500_000.0)
    joined = " ".join(c.notes)
    assert "step-up" in joined and "gift" in joined.lower()


def test_the_tsp_non_spouse_payout_trap_is_stated():
    h = _household(tsp_traditional=100_000.0)
    joined = " ".join(EP.inheritance_comparison(h, 0.24).notes)
    assert "beneficiary participant account" in joined
    assert "inherited IRA" in joined


# ==========================================================================
# Gifting
# ==========================================================================

def _gift_household(target, n_children=2, start=2026, gift=0.0,
                    real_return=4.0, married=False) -> Household:
    h = _household(target_legacy_per_child=target, n_children=n_children,
                   gifting_start_year=start, annual_gift_per_child=gift)
    h.has_spouse = married
    h.assumptions.real_return_pct = real_return
    return h


def test_the_gifting_plan_reaches_the_target_at_the_assumed_return():
    h = _gift_household(500_000.0)
    p = EP.gifting_plan(h, current_year=CURRENT_YEAR)

    assert p.years > 0 and p.required_annual_gift_per_child > 0
    assert p.rows[-1].required_value_per_child == pytest.approx(500_000.0, rel=1e-9)
    assert p.rows[-1].year == p.end_year

    # The closed form the schedule is solved from, checked independently.
    r = h.assumptions.real_return_pct / 100.0
    factor = sum((1.0 + r) ** k for k in range(p.years))
    assert p.required_annual_gift_per_child == pytest.approx(500_000.0 / factor)


def test_gifting_the_required_amount_is_what_reaches_the_target():
    h = _gift_household(750_000.0)
    required = EP.gifting_plan(h, current_year=CURRENT_YEAR).required_annual_gift_per_child
    h.estate.annual_gift_per_child = required
    p = EP.gifting_plan(h, current_year=CURRENT_YEAR)
    assert p.planned_value_per_child == pytest.approx(750_000.0, rel=1e-9)
    assert p.reaches_target
    assert p.shortfall_per_child == pytest.approx(0.0, abs=1.0)


def test_a_zero_real_return_needs_the_target_split_evenly():
    h = _gift_household(310_000.0, real_return=0.0)
    p = EP.gifting_plan(h, current_year=CURRENT_YEAR)
    assert p.required_annual_gift_per_child == pytest.approx(310_000.0 / p.years)


def test_the_annual_exclusion_cap_is_flagged_when_the_gift_exceeds_it():
    """A big target over a short window forces the gift above the exclusion."""
    h = _gift_household(3_000_000.0)
    p = EP.gifting_plan(h, current_year=CURRENT_YEAR)

    assert p.required_annual_gift_per_child > p.exclusion_per_child
    assert p.cap_binds
    assert len(p.capped_years) == p.years
    assert all(r.over_exclusion for r in p.rows)
    assert p.excess_per_child_per_year == pytest.approx(
        p.required_annual_gift_per_child - p.exclusion_per_child)
    assert p.reportable_gifts
    joined = " ".join(p.notes)
    assert "Form 709" in joined and "REPORTING, not tax" in joined


def test_a_modest_target_stays_inside_the_exclusion():
    h = _gift_household(300_000.0)
    p = EP.gifting_plan(h, current_year=CURRENT_YEAR)
    assert p.required_annual_gift_per_child < p.exclusion_per_child
    assert not p.cap_binds and not p.capped_years
    assert not any(r.over_exclusion for r in p.rows)


def test_a_married_couple_gets_two_exclusions():
    assert EP.annual_exclusion(False) == EP.ANNUAL_GIFT_EXCLUSION
    assert EP.annual_exclusion(True) == 2 * EP.ANNUAL_GIFT_EXCLUSION
    single = EP.gifting_plan(_gift_household(1_000_000.0), current_year=CURRENT_YEAR)
    couple = EP.gifting_plan(_gift_household(1_000_000.0, married=True),
                             current_year=CURRENT_YEAR)
    assert couple.exclusion_per_child == 2 * single.exclusion_per_child


def test_no_children_produces_an_empty_plan_and_says_why():
    p = EP.gifting_plan(_gift_household(500_000.0, n_children=0),
                        current_year=CURRENT_YEAR)
    assert p.rows == [] and p.required_annual_gift_total == 0.0
    assert "per RECIPIENT" in " ".join(p.notes)


def test_a_start_year_past_the_horizon_is_refused_not_crashed():
    p = EP.gifting_plan(_gift_household(500_000.0, start=2099),
                        current_year=CURRENT_YEAR)
    assert p.years == 0 and p.rows == []
    assert "no gifting window" in " ".join(p.notes)


def test_superfunding_is_five_years_of_exclusion():
    assert EP.superfund_529() == 5 * EP.ANNUAL_GIFT_EXCLUSION
    assert EP.superfund_529(married=True) == 10 * EP.ANNUAL_GIFT_EXCLUSION


def test_a_roth_for_a_child_is_capped_by_their_earned_income():
    assert EP.roth_ira_for_a_child(4_000.0, 7_500.0) == 4_000.0
    assert EP.roth_ira_for_a_child(50_000.0, 7_500.0) == 7_500.0
    assert EP.roth_ira_for_a_child(0.0, 7_500.0) == 0.0


# ==========================================================================
# Estate tax
# ==========================================================================

def test_estate_tax_is_zero_for_a_household_below_the_exemption():
    h = _household(tsp_traditional=800_000.0, sgli=500_000.0)
    h.cash_savings = 60_000.0
    h.home_value = 420_000.0
    h.mortgage_balance = 280_000.0
    t = EP.estate_tax_check(h)

    assert t.taxable_estate < EP.FEDERAL_ESTATE_EXEMPTION
    assert t.federal_tax == 0.0
    assert not t.owes_federal_estate_tax
    assert t.headroom == pytest.approx(EP.FEDERAL_ESTATE_EXEMPTION - t.taxable_estate)
    assert "not your problem" in " ".join(t.notes)


def test_the_gross_estate_includes_the_whole_house_and_the_life_insurance():
    h = _household(sgli=500_000.0)
    h.home_value = 400_000.0
    h.mortgage_balance = 300_000.0
    t = EP.estate_tax_check(h)
    assert t.gross_estate == pytest.approx(900_000.0)   # not the $100k of equity
    assert t.debts == pytest.approx(300_000.0)
    assert t.taxable_estate == pytest.approx(600_000.0)


def test_estate_tax_applies_above_the_exemption_at_the_top_rate():
    over = 2_000_000.0
    assert EP.federal_estate_tax(EP.FEDERAL_ESTATE_EXEMPTION + over) == \
        pytest.approx(over * EP.ESTATE_TAX_TOP_RATE)
    # Portability: a married couple shelters twice as much.
    assert EP.federal_estate_tax(EP.FEDERAL_ESTATE_EXEMPTION + over,
                                 married=True) == 0.0
    # Lifetime taxable gifts consume the same unified exemption.
    assert EP.federal_estate_tax(EP.FEDERAL_ESTATE_EXEMPTION,
                                 lifetime_gifts_reported=1_000_000.0) == \
        pytest.approx(1_000_000.0 * EP.ESTATE_TAX_TOP_RATE)


def test_the_state_note_names_the_states_that_actually_tax_an_estate():
    assert "ESTATE tax" in EP.state_death_tax_note("Oregon")
    assert "INHERITANCE tax" in EP.state_death_tax_note("Pennsylvania")
    assert "community property" in EP.state_death_tax_note("Texas")
    assert "neither" in EP.state_death_tax_note("Michigan")
    assert EP.state_death_tax_note("") == ""
    # Maryland is the state that levies both.
    both = EP.state_death_tax_note("Maryland")
    assert "ESTATE tax" in both and "INHERITANCE tax" in both


def test_every_hard_coded_figure_carries_a_verify_note():
    """A statutory number added without its provenance fails here."""
    for name in ("FEDERAL_ESTATE_EXEMPTION", "ESTATE_TAX_TOP_RATE",
                 "ANNUAL_GIFT_EXCLUSION",
                 "NON_CITIZEN_SPOUSE_ANNUAL_EXCLUSION", "SUPERFUND_YEARS",
                 "SECURE_DRAIN_YEARS", "STATE_ESTATE_TAX"):
        assert name in EP.VERIFY, f"{name} has no VERIFY note"
        note = EP.VERIFY[name]
        assert note.strip(), f"{name}: the VERIFY note is empty"
        assert "onfidence" in note, f"{name}: the note states no confidence"
    assert EP.FIGURE_YEAR == 2026
    # The TCJA sunset question is the thing every stale article gets wrong.
    assert "sunset" in EP.VERIFY["FEDERAL_ESTATE_EXEMPTION"].lower()


# ==========================================================================
# Everything together
# ==========================================================================

def test_findings_are_ordered_by_dollars_at_stake():
    h = _household(tsp_traditional=700_000.0, ira_traditional=180_000.0,
                   sgli=500_000.0)
    out = EP.findings(h, 0.24)
    dollars = [f.dollars for f in out]
    assert dollars == sorted(dollars, reverse=True)
    assert out[0].dollars > 0


def test_a_will_and_a_power_of_attorney_are_both_asked_about():
    h = _household(tsp_traditional=10_000.0)
    text = " ".join(f.headline + " " + f.detail for f in EP.findings(h, 0.24))
    assert "no will" in text and "power of attorney" in text
    assert "10 U.S.C. 1044" in text
    assert "who raises your children" in text

    h.estate.has_will = True
    text = " ".join(f.headline for f in EP.findings(h, 0.24, has_poa=True))
    assert "You have a will." in text and "power of attorney" not in text


def test_the_survivors_page_is_pointed_at_rather_than_restated():
    h = _household(tsp_traditional=10_000.0)
    h.member.sbp_elected = True
    out = EP.findings(h, 0.24)
    assert "Survivors, SBP and the VA page" in " ".join(f.detail for f in out)
    assert "not part of your estate" in " ".join(f.headline for f in out)


# ==========================================================================
# The samples
# ==========================================================================

def test_the_retiree_sample_produces_a_gifting_plan():
    h = _sample(SAMPLES[0])
    h.estate.n_children = 2
    h.estate.target_legacy_per_child = 1_000_000.0
    h.estate.gifting_start_year = 2026

    p = EP.gifting_plan(h, current_year=CURRENT_YEAR)

    assert p.n_children == 2
    assert p.start_year == 2026 and p.end_year > 2050
    assert p.years == p.end_year - 2026 + 1
    assert len(p.rows) == p.years
    assert 5_000 < p.required_annual_gift_per_child < 30_000
    assert p.required_annual_gift_total == pytest.approx(
        2 * p.required_annual_gift_per_child)
    assert p.rows[-1].required_value_per_child == pytest.approx(1_000_000.0, rel=1e-9)
    # $700k of traditional TSP is the thing this page exists to talk about.
    assert p.heir_tax_at_death > 0
    assert p.bequest_per_child_after_tax > 0


@pytest.mark.parametrize("path", SAMPLES, ids=[p.name for p in SAMPLES])
def test_both_samples_run_the_whole_engine(path):
    h = _sample(path)
    h.estate.n_children = 2
    h.estate.target_legacy_per_child = 500_000.0
    assert EP.beneficiary_checklist(h)
    assert EP.inheritance_comparison(h, 0.24).total_after_tax >= 0
    assert EP.estate_tax_check(h).federal_tax == 0.0
    assert EP.gifting_plan(h, current_year=CURRENT_YEAR).rows
    assert EP.findings(h, 0.24)


# ==========================================================================
# The page
# ==========================================================================

def _render(household: Household | None = None):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(PAGE), default_timeout=90)
    if household is not None:
        # Exactly what ui.panel.get_household reads, and the version wkey
        # namespaces every widget against.
        at.session_state[PROFILE_KEY] = household
        at.session_state[VERSION_KEY] = 0
        at.session_state[DIRTY_KEY] = False
    at.run()
    assert not at.exception, at.exception
    return at


def test_the_page_renders_from_a_blank_plan():
    at = _render()
    assert "Who gets what" in at.title[0].value
    body = " ".join(md.value for md in at.markdown)
    assert "beneficiary" in body.lower()


@pytest.mark.parametrize("path", SAMPLES, ids=[p.name for p in SAMPLES])
def test_the_page_renders_against_both_sample_plans(path):
    at = _render(_sample(path))
    assert not at.exception, at.exception
    assert at.session_state[PROFILE_KEY].profile_name.startswith("Sample")


@pytest.mark.parametrize("path", SAMPLES, ids=[p.name for p in SAMPLES])
def test_the_page_builds_a_gifting_plan_on_a_sample(path):
    h = _sample(path)
    h.estate.n_children = 2
    h.estate.target_legacy_per_child = 1_000_000.0
    at = _render(h)
    body = " ".join(md.value for md in at.markdown)
    assert "annual exclusion" in body.lower()
    assert at.dataframe, "the gifting table and the wrapper table both render"


def test_the_page_writes_the_answers_back_into_the_plan():
    at = _render(_household(tsp_traditional=250_000.0))
    at.toggle(key="est_will__v0").set_value(True).run()
    assert not at.exception, at.exception
    h = at.session_state[PROFILE_KEY]
    assert h.estate.has_will is True
    assert at.session_state[DIRTY_KEY] is True

    at.number_input(key="est_kids__v0").set_value(3).run()
    assert not at.exception, at.exception
    assert at.session_state[PROFILE_KEY].estate.n_children == 3

    at.number_input(key="est_target__v0").set_value(400_000.0).run()
    assert not at.exception, at.exception
    assert at.session_state[PROFILE_KEY].estate.target_legacy_per_child == \
        pytest.approx(400_000.0)


def test_the_page_flags_a_stale_designation_loudly():
    at = _render(_household(tsp_traditional=700_000.0))
    errors = " ".join(e.value for e in at.error)
    assert "form you have not confirmed" in errors

    h = _household(tsp_traditional=700_000.0)
    h.estate.tsp_beneficiary_current = True
    at = _render(h)
    assert "designated" in " ".join(s.value for s in at.success)
