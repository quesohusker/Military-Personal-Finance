"""
Tests for the assumptions page and its engine.

The explanations are checked by introspecting the dataclass, so a field added
to Assumptions without a matching explanation fails here rather than shipping
as an unexplained number.
"""

import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import dataclasses
import pytest

from engine import assumptions as A
from engine.profile import (Assumptions, ServiceMember, ACTIVE,
                            SYS_REDUX, SYS_HIGH3, SYS_BRS, SYS_NONE)
from engine.tax import federal as F
from engine.tax import tables as T
from ui.panel import PROFILE_KEY, DIRTY_KEY, VERSION_KEY

FIELD_NAMES = [f.name for f in dataclasses.fields(Assumptions)]


# ==========================================================================
# Explanations
# ==========================================================================

def test_every_field_of_assumptions_has_an_explanation():
    """A new field on the dataclass must arrive with its explanation."""
    for f in dataclasses.fields(Assumptions):
        e = A.explain(f.name)
        assert e.field == f.name
        for part in (e.question, e.unit, e.what, e.what_not, e.reasoning, e.hint):
            assert part.strip(), f"{f.name}: every explanation part is written"
        assert e.pages, f"{f.name}: says which pages it moves"
        assert e.default == f.default, f"{f.name}: the stated default is the dataclass default"
        assert e.in_range(f.default), f"{f.name}: the default is inside its own range"


def test_no_explanation_for_a_field_that_does_not_exist():
    assert set(A._EXPLANATIONS) == set(FIELD_NAMES)
    assert list(A.FIELDS) == FIELD_NAMES
    with pytest.raises(KeyError):
        A.explain("nominal_return_pct")


def test_the_discount_rate_is_explained_as_not_inflation():
    e = A.explain("real_discount_rate_pct")
    assert "NOT inflation" in e.what_not
    assert "today's dollars" in e.what_not
    assert 0.0 <= e.low < e.default < e.high <= 6.0


def test_questions_are_prompts_not_nouns():
    for e in A.explain_all():
        assert e.question.endswith("?") or e.question.startswith(("Assume", "Plan")), e.question


def test_pages_moved_names_the_pages_with_their_own_inputs():
    rows = A.pages_moved()
    pages = {r["Page"] for r in rows}
    assert {A.PAGE_WORTH, A.PAGE_TWENTY, A.PAGE_SURVIVOR, A.PAGE_MEDICAL} <= pages
    disc = [r for r in rows if r["Assumption"] == A.explain("real_discount_rate_pct").question]
    assert any("'disc'" in r["How the page gets it today"] for r in disc)
    assert all(r["How the page gets it today"].strip() for r in rows)


# ==========================================================================
# Presets
# ==========================================================================

def test_three_presets_with_the_stated_values():
    assert list(A.presets) == ["Conservative", "Baseline", "Optimistic"]
    c, b, o = (A.presets[n].values for n in A.presets)
    assert (c["real_return_pct"], c["real_discount_rate_pct"], c["tax_scenario"]) == (3.0, 2.5, A.TAX_SUNSET)
    assert (b["real_return_pct"], b["real_discount_rate_pct"], b["tax_scenario"]) == (4.0, 3.0, A.TAX_CURRENT)
    assert (o["real_return_pct"], o["real_discount_rate_pct"], o["tax_scenario"]) == (5.0, 3.5, A.TAX_CURRENT)


def test_presets_are_coherent():
    for p in A.presets.values():
        assert p.rationale.strip().endswith(".")
        for k, v in p.values.items():
            assert k in FIELD_NAMES, f"{p.name} sets {k}, which Assumptions does not have"
            assert A.explain(k).in_range(v), f"{p.name}: {k}={v} is outside the stated range"
        # Risky money is expected to earn at least what safe money does.
        assert p.values["real_return_pct"] >= p.values["real_discount_rate_pct"]
        # A preset is an outlook; the COLA is a fact about the retirement system.
        assert "cola_full" not in p.values
        a = Assumptions()
        A.apply_preset(a, p.name)
        noisy = [f for f in A.sanity(a, SYS_HIGH3) if f[0] in ("warn", "bad")]
        assert not noisy, f"{p.name} trips its own sanity check: {noisy}"
    c, b, o = (A.presets[n].values for n in A.presets)
    assert c["real_return_pct"] < b["real_return_pct"] < o["real_return_pct"]
    assert c["real_discount_rate_pct"] < b["real_discount_rate_pct"] < o["real_discount_rate_pct"]
    assert c["planning_margin_years"] > b["planning_margin_years"] > o["planning_margin_years"]


def test_baseline_is_the_dataclass_default():
    a = Assumptions()
    assert A.matching_preset(a) == "Baseline"
    assert A.apply_preset(a, "Baseline") == []


def test_apply_preset_writes_in_place_and_reports_what_changed():
    a = Assumptions()
    changed = A.apply_preset(a, "Conservative")
    assert set(changed) == set(A.presets["Conservative"].values)
    assert a.real_return_pct == 3.0 and a.real_discount_rate_pct == 2.5
    assert a.tax_scenario == A.TAX_SUNSET and a.planning_margin_years == 8
    assert a.cola_full is True
    assert A.matching_preset(a) == "Conservative"
    assert A.apply_preset(a, "Conservative") == []
    a.real_return_pct = 3.25
    assert A.matching_preset(a) is None


# ==========================================================================
# Real <-> nominal
# ==========================================================================

@pytest.mark.parametrize("real,infl", [(4.0, 2.5), (0.0, 3.0), (-1.0, 2.0),
                                       (7.0, 0.0), (3.5, 6.0), (2.5, 2.5)])
def test_real_and_nominal_round_trip(real, infl):
    nominal = A.real_to_nominal(real, infl)
    assert A.nominal_to_real(nominal, infl) == pytest.approx(real)
    assert A.real_to_nominal(A.nominal_to_real(nominal, infl), infl) == pytest.approx(nominal)


def test_the_conversion_is_fisher_not_addition():
    assert A.real_to_nominal(4.0, 2.5) == pytest.approx(6.6)
    assert A.real_to_nominal(4.0, 2.5) > 4.0 + 2.5
    assert A.nominal_to_real(6.5, 2.5) == pytest.approx(3.9024, abs=1e-3)
    assert A.real_to_nominal(0.0, 2.5) == pytest.approx(2.5)
    assert A.nominal_to_real(2.5, 2.5) == pytest.approx(0.0)


def test_nominal_equivalent_exists_only_for_real_rates():
    a = Assumptions()
    assert A.nominal_equivalent("real_return_pct", a) == pytest.approx(6.6)
    assert A.nominal_equivalent("real_discount_rate_pct", a) == pytest.approx(5.575)
    assert A.nominal_equivalent("pay_raise_real_pct", a) == pytest.approx(2.5)
    assert A.nominal_equivalent("inflation_pct", a) is None
    assert A.nominal_equivalent("cola_full", a) is None
    assert A.nominal_equivalent("tax_scenario", a) is None


def test_as_decimals_bridges_to_the_engines():
    d = A.as_decimals(Assumptions())
    assert d == {"inflation": 0.025, "real_return": 0.04,
                 "real_discount_rate": 0.03, "pay_raise_real": 0.0}


# ==========================================================================
# Sanity
# ==========================================================================

def _redux_member() -> ServiceMember:
    m = ServiceMember(component=ACTIVE, diems_date="1990-06-01", took_csb_redux=True)
    assert m.retirement_system == SYS_REDUX
    return m


def test_sanity_flags_a_redux_member_with_full_cola():
    m = _redux_member()
    findings = A.sanity(Assumptions(cola_full=True), m.retirement_system)
    bad = [f for f in findings if f[0] == "bad"]
    assert bad and "REDUX" in bad[0][1] and "CPI minus one" in bad[0][2]
    quiet = A.sanity(Assumptions(cola_full=False), m.retirement_system)
    assert not [f for f in quiet if f[0] == "bad"]


def test_sanity_flags_full_cola_switched_off_for_a_full_cola_system():
    for system in (SYS_HIGH3, SYS_BRS):
        findings = A.sanity(Assumptions(cola_full=False), system)
        assert any(f[0] == "warn" and "Only CSB/REDUX" in f[1] for f in findings)
    # Nobody to check against: no COLA finding either way.
    for system in ("", SYS_NONE):
        assert not [f for f in A.sanity(Assumptions(cola_full=False), system)
                    if "COLA" in f[1]]


def test_sanity_flags_an_aggressive_return():
    findings = A.sanity(Assumptions(real_return_pct=7.0), SYS_HIGH3)
    assert any(f[0] == "warn" and "aggressive" in f[1] for f in findings)
    assert not any("aggressive" in f[1]
                   for f in A.sanity(Assumptions(real_return_pct=6.0), SYS_HIGH3))


def test_sanity_flags_a_return_below_the_discount_rate():
    findings = A.sanity(Assumptions(real_return_pct=2.0, real_discount_rate_pct=3.0))
    assert any("earn less than" in f[1] for f in findings)
    assert not A.sanity(Assumptions(real_return_pct=3.0, real_discount_rate_pct=3.0))


def test_sanity_flags_a_high_discount_rate_and_a_negative_one():
    high = A.sanity(Assumptions(real_return_pct=7.0, real_discount_rate_pct=6.0))
    assert any("like a stock" in f[1] for f in high)
    neg = A.sanity(Assumptions(real_discount_rate_pct=-1.0))
    assert any(f[0] == "bad" and "negative real discount" in f[1].lower() for f in neg)


def test_sanity_flags_a_negative_planning_margin():
    findings = A.sanity(Assumptions(planning_margin_years=-1))
    assert any(f[0] == "bad" and "before the median" in f[1] for f in findings)
    assert not A.sanity(Assumptions(planning_margin_years=0))


def test_sanity_flags_an_unknown_tax_scenario_and_labels_the_stress_test():
    assert any(f[0] == "bad" for f in A.sanity(Assumptions(tax_scenario="Made up")))
    higher = A.sanity(Assumptions(tax_scenario=A.TAX_HIGHER))
    assert any(f[0] == "info" and "stress test" in f[1] for f in higher)


def test_sanity_is_quiet_on_the_defaults():
    assert A.sanity(Assumptions(), SYS_HIGH3) == []
    assert A.sanity(Assumptions()) == []


def test_sanity_findings_are_well_formed():
    a = Assumptions(real_return_pct=9.0, real_discount_rate_pct=-1.0,
                    inflation_pct=-1.0, pay_raise_real_pct=3.0,
                    planning_margin_years=-5, tax_scenario="x")
    findings = A.sanity(a, SYS_REDUX)
    assert len(findings) >= 6
    for sev, headline, detail in findings:
        assert sev in ("good", "info", "warn", "bad")
        assert headline.strip() and detail.strip()


# ==========================================================================
# Tax scenarios
# ==========================================================================

def test_tax_scenarios_use_the_profile_vocabulary():
    assert list(A.tax_scenarios) == A.TAX_SCENARIOS == ["Current law", "TCJA sunset", "Higher"]
    assert Assumptions().tax_scenario in A.tax_scenarios
    assert A.tax_scenario_for(Assumptions(tax_scenario="??")).name == A.TAX_CURRENT


def test_sunset_is_the_2017_schedule_and_is_marked_verify():
    sc = A.tax_scenarios[A.TAX_SUNSET]
    assert sc.verify and sc.note.startswith("VERIFY")
    for status in (T.MFJ, T.SINGLE):
        assert [r for _, r in sc.brackets[status]] == [0.10, 0.15, 0.25, 0.28, 0.33, 0.35, 0.396]
        assert sc.standard_deduction[status] < T.STANDARD_DEDUCTION_2026[status]
    assert sc.personal_exemption > 0
    # The note states the table it assumes.
    assert "39.6% and above" in sc.note and "personal exemption" in sc.note
    assert "10/15/25/28/33/35/39.6" in sc.summary


def test_higher_adds_five_points_to_every_rate_and_calls_itself_a_stress_test():
    sc = A.tax_scenarios[A.TAX_HIGHER]
    assert sc.stress_test and "stress test" in sc.summary.lower()
    assert sc.points_added == A.HIGHER_POINTS == 5.0
    for status in (T.MFJ, T.SINGLE):
        for (b0, r0), (b1, r1) in zip(T.FEDERAL_BRACKETS_2026[status], sc.brackets[status]):
            assert b0 == b1
            assert r1 == pytest.approx(r0 + 0.05)


def test_current_law_is_the_2026_table_with_a_multiplier_of_one():
    sc = A.tax_scenarios[A.TAX_CURRENT]
    assert sc.brackets is T.FEDERAL_BRACKETS_2026
    assert not sc.verify and not sc.stress_test
    for income in (30_000, 80_000, 300_000):
        assert sc.rate_multiplier(income) == 1.0


def test_multipliers_at_a_middle_income():
    """$80,000 taxable, joint: 12% today; 15% under the 2017 schedule; 17% under Higher."""
    assert A.tax_scenarios[A.TAX_SUNSET].rate_multiplier(80_000, T.MFJ) == pytest.approx(0.15 / 0.12)
    assert A.tax_scenarios[A.TAX_HIGHER].rate_multiplier(80_000, T.MFJ) == pytest.approx(0.17 / 0.12)


def test_scenarios_become_engine_tax_policies_the_engine_reproduces():
    assert A.tax_scenarios[A.TAX_CURRENT].to_tax_policy().scenario == F.SCENARIO_CURRENT
    sunset = A.tax_scenarios[A.TAX_SUNSET].to_tax_policy(change_year=2030)
    assert sunset.scenario == F.SCENARIO_PRE_TCJA and sunset.change_year == 2030
    higher = A.tax_scenarios[A.TAX_HIGHER].to_tax_policy(change_year=2030)
    assert higher.scenario == F.SCENARIO_SURCHARGE and higher.surcharge_points == 5.0

    reg = F.regime_for_year(sunset, 2035, T.MFJ, n_people_65plus=0, n_people=2)
    assert reg.ordinary_brackets == list(T.PRE_TCJA_BRACKETS_2026[T.MFJ])
    assert reg.personal_exemption == 2 * T.PRE_TCJA_PERSONAL_EXEMPTION
    reg = F.regime_for_year(higher, 2035, T.MFJ, n_people_65plus=0, n_people=2)
    assert [r for _, r in reg.ordinary_brackets] == pytest.approx(
        [r for _, r in A.tax_scenarios[A.TAX_HIGHER].brackets[T.MFJ]])
    # Before the change year, current law.
    reg = F.regime_for_year(sunset, 2027, T.MFJ, n_people_65plus=0, n_people=2)
    assert reg.ordinary_brackets == list(T.FEDERAL_BRACKETS_2026[T.MFJ])


def test_bracket_rows_are_one_per_band():
    rows = A.bracket_rows(A.tax_scenarios[A.TAX_SUNSET])
    assert len(rows) == 7
    assert rows[0]["Marginal rate"] == "10%" and rows[-1]["Marginal rate"] == "39.6%"
    assert rows[-1]["Married filing jointly, taxable income"] == "and above"
    assert rows[1]["Single, taxable income"] == "up to $48,900"


# ==========================================================================
# The page
# ==========================================================================

PAGE = ROOT / "pages" / "17_Assumptions.py"


def _render():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(PAGE), default_timeout=90)
    at.run()
    assert not at.exception, at.exception
    return at


def test_page_renders_with_a_card_for_every_assumption():
    at = _render()
    assert "What should we assume" in at.title[0].value
    body = " ".join(md.value for md in at.markdown)
    for e in A.explain_all():
        assert e.question in body, e.question
    assert "NOT inflation" in body
    assert at.session_state[PROFILE_KEY].assumptions == Assumptions()


def test_page_inputs_write_straight_into_the_plan():
    at = _render()
    at.number_input(key=f"as_return__v{0}").set_value(7.0).run()
    assert not at.exception, at.exception
    h = at.session_state[PROFILE_KEY]
    assert h.assumptions.real_return_pct == 7.0
    assert at.session_state[DIRTY_KEY] is True
    body = " ".join(md.value for md in at.markdown)
    assert "aggressive" in body


def test_page_applies_a_preset_and_refreshes_its_widgets():
    at = _render()
    at.selectbox(key="as_preset__v0").select("Conservative").run()
    at.button(key="as_apply__v0").click().run()
    assert not at.exception, at.exception
    h = at.session_state[PROFILE_KEY]
    assert A.matching_preset(h.assumptions) == "Conservative"
    assert h.assumptions.tax_scenario == A.TAX_SUNSET
    assert at.session_state[DIRTY_KEY] is True
    # The keys were versioned so every bound widget re-read the plan.
    v = at.session_state[VERSION_KEY]
    assert v == 1
    assert at.number_input(key=f"as_return__v{v}").value == 3.0
    assert at.selectbox(key=f"as_preset__v{v}").value == "Conservative"
