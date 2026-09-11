"""
The readiness scorecard.

What is worth testing here is not arithmetic — the engines under it are
already covered by 1,178 tests — but the four promises the scorecard makes
that nothing else in the app can keep for it:

  * the BAND BOUNDARIES are where they are documented to be, on both sides;
  * the ROLL-UP renormalises over applicable weight, so a household rated on
    three components and one rated on eight produce comparable numbers;
  * a component that DOES NOT APPLY is excluded rather than scored zero —
    the single failure that would make three funnels produce three
    incomparable answers;
  * nothing is INVENTED. A blank plan does not crash, a serving member gets
    honest C-5s with reasons rather than fabricated figures, and every rated
    component states the figures it was rated from (§8: a number with no
    visible derivation is worse than no number).
"""

import pathlib

import pytest

from engine import scorecard as SC
from engine.scorecard import bands as B
from engine.scorecard import components as K
from engine.scorecard import inputs as IN
from engine.scorecard.bands import C1, C2, C3, C4, C5
from engine.profile import Household, ServiceMember, ACTIVE, RETIRED, VETERAN
from engine.funnel import (set_funnel, FUNNEL_SERVING, FUNNEL_VETERAN,
                           FUNNEL_RETIRED, FUNNELS)
from engine.debt.payoff import Debt
from engine import storage

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"


def sample(name: str) -> Household:
    return storage.from_upload_bytes((SAMPLES / name).read_bytes())


def retiree() -> Household:
    """The retiree sample with the one question the floor cannot be guessed from."""
    h = sample("retired_o5_26yrs.mpfplan.json")
    h.essential_monthly_expenses = 5_400.0
    set_funnel(h, FUNNEL_RETIRED)
    return h


# ==========================================================================
# Band boundaries
# ==========================================================================

def test_a_higher_is_better_ratio_bands_on_the_documented_cuts():
    cuts = (1.00, 0.80, 0.60, 0.40)
    assert B.band_for_ratio(1.00, cuts) == C1        # exactly on the cut
    assert B.band_for_ratio(0.9999, cuts) == C2      # a hair under it
    assert B.band_for_ratio(0.80, cuts) == C2
    assert B.band_for_ratio(0.7999, cuts) == C3
    assert B.band_for_ratio(0.60, cuts) == C3
    assert B.band_for_ratio(0.5999, cuts) == C4
    assert B.band_for_ratio(0.40, cuts) == C4
    assert B.band_for_ratio(0.3999, cuts) == C5
    assert B.band_for_ratio(0.0, cuts) == C5


def test_a_lower_is_better_figure_bands_the_other_way_up():
    cuts = (0.10, 0.15, 0.20, 0.26)
    assert B.band_for_cost(0.0, cuts) == C1
    assert B.band_for_cost(0.10, cuts) == C1
    assert B.band_for_cost(0.1001, cuts) == C2
    assert B.band_for_cost(0.26, cuts) == C4
    assert B.band_for_cost(0.2601, cuts) == C5


def test_the_readiness_scale_and_its_inverse_agree_at_every_band():
    for r in B.RATINGS:
        assert B.band_for_readiness(B.readiness(r)) == r
    assert B.readiness(C1) == 1.0
    assert B.readiness(C5) == 0.0


def test_a_scorecard_of_straight_c3s_rolls_up_to_c3_not_c4():
    """
    The reason the cuts sit at the midpoints. With round-number cuts a card of
    straight C-3s rolls up to C-4, which is a quiet distortion that would make
    the aggregate untrustworthy.
    """
    items = [K.Component(key=str(i), weight=1.0, status=K.RATED, rating=C3)
             for i in range(8)]
    assert B.roll_up(items).rating == C3


def test_findings_band_on_the_documented_ladder():
    bad = ("bad", "h", "d")
    warn = ("warn", "h", "d")
    good = ("good", "h", "d")
    info = ("info", "h", "d")
    assert B.band_from_findings([good, info]) == C1
    assert B.band_from_findings([warn]) == C2
    assert B.band_from_findings([warn, warn]) == C2
    assert B.band_from_findings([warn, warn, warn]) == C3
    assert B.band_from_findings([bad]) == C4
    assert B.band_from_findings([bad, bad]) == C5
    assert B.band_from_findings([]) == C1


def test_findings_band_reads_the_estate_engines_finding_objects_too():
    """`estate.planning.Finding` is a dataclass, not a tuple. Both must work."""
    from engine.estate.planning import Finding
    assert B.band_from_findings([Finding("bad", "h", "d", 1.0)]) == C4
    assert B.band_from_findings([Finding("good", "h", "d")]) == C1


def test_demote_and_promote_clamp_at_the_ends():
    assert B.demote(C5, 3) == C5
    assert B.promote(C1, 3) == C1
    assert B.demote(C3, 2) == C5
    assert B.worst(C1, C4, C2) == C4


# ==========================================================================
# The renormalising roll-up
# ==========================================================================

def test_the_roll_up_divides_by_applicable_weight_only():
    """
    The whole mechanism, copied from `coach.prime_directive`. A C-1 worth 1.0
    beside an EXCLUDED component worth 99.0 is still a C-1 — if the excluded
    weight reached the denominator it would be C-5.
    """
    items = [
        K.Component(key="rated", weight=1.0, status=K.RATED, rating=C1),
        K.Component(key="gone", weight=99.0, status=K.NOT_APPLICABLE, rating=C5),
    ]
    r = B.roll_up(items)
    assert r.rating == C1
    assert r.score == 100.0
    assert r.applicable_weight == 1.0
    assert r.total_weight == 100.0
    assert r.n_applicable == 1


def test_two_cards_rated_on_different_component_counts_are_comparable():
    """
    Three funnels rate different numbers of components. Straight C-2s must
    produce the same number whether three of them were rated or eight.
    """
    few = [K.Component(key=str(i), weight=1.0, status=K.RATED, rating=C2)
           for i in range(3)]
    many = ([K.Component(key=str(i), weight=1.0, status=K.RATED, rating=C2)
             for i in range(8)]
            + [K.Component(key="x", weight=5.0, status=K.NOT_MODELLED, rating=C5)])
    assert B.roll_up(few).score == B.roll_up(many).score
    assert B.roll_up(few).rating == B.roll_up(many).rating


def test_weight_actually_weights():
    heavy = K.Component(key="heavy", weight=3.0, status=K.RATED, rating=C5)
    light = K.Component(key="light", weight=1.0, status=K.RATED, rating=C1)
    r = B.roll_up([heavy, light])
    assert r.readiness == pytest.approx(0.25)
    assert r.rating == C4


def test_a_card_with_nothing_applicable_is_c5_rather_than_a_divide_by_zero():
    items = [K.Component(key="a", weight=2.0, status=K.NOT_APPLICABLE, rating=C5)]
    r = B.roll_up(items)
    assert r.rating == C5
    assert r.score == 0.0
    assert r.applicable_weight == 0.0


def test_not_entered_counts_but_not_modelled_and_not_applicable_do_not():
    """
    The three ways a rating fails to be established are NOT interchangeable.
    A blank answer is the user's to fix and must drag the card; a projection
    that cannot reach and a component that does not apply are not.
    """
    assert K.Component(status=K.RATED).applies is True
    assert K.Component(status=K.NOT_ENTERED).applies is True
    assert K.Component(status=K.NOT_MODELLED).applies is False
    assert K.Component(status=K.NOT_RUN).applies is False
    assert K.Component(status=K.NOT_APPLICABLE).applies is False


# ==========================================================================
# A component that does not apply is excluded, not scored zero
# ==========================================================================

def test_legacy_is_excluded_when_it_was_never_said_to_be_a_goal():
    h = retiree()
    h.estate.n_children = 0
    h.estate.target_legacy_per_child = 0.0
    h.estate.annual_gift_per_child = 0.0
    card = SC.evaluate(h)
    legacy = card.by_key("legacy")
    assert legacy.status == K.NOT_APPLICABLE
    assert legacy.applies is False
    assert legacy not in card.active
    excluded = sum(c.weight for c in card.components if not c.applies)
    assert legacy.weight <= excluded
    assert card.applicable_weight == card.total_weight - excluded


def test_saying_a_legacy_is_a_goal_brings_the_component_back_in():
    h = retiree()
    h.estate.n_children = 2
    h.estate.target_legacy_per_child = 250_000.0
    card = SC.evaluate(h)
    legacy = card.by_key("legacy")
    assert legacy.status == K.RATED
    assert legacy.applies is True
    assert any("Target met" in e.label for e in legacy.evidence)


def test_dependents_claimed_for_pay_are_not_read_as_legacy_intent():
    """
    Documented decision. `n_dependents` includes a spouse and is a pay and tax
    concept; treating it as legacy intent would score every married member on
    a goal they never stated.
    """
    h = retiree()
    h.n_dependents = 4
    h.estate.n_children = 0
    h.estate.target_legacy_per_child = 0.0
    assert SC.evaluate(h).by_key("legacy").status == K.NOT_APPLICABLE


def test_survivor_does_not_apply_with_nobody_to_leave_an_income_to():
    h = retiree()
    h.has_spouse = False
    h.spouse = None
    h.estate.n_children = 0
    card = SC.evaluate(h)
    assert card.by_key("survivor").status == K.NOT_APPLICABLE
    assert card.by_key("survivor").applies is False


# ==========================================================================
# Nothing is invented
# ==========================================================================

def test_a_blank_household_produces_a_card_without_raising():
    card = SC.evaluate(Household())
    assert len(card.components) == 8
    assert card.rating in B.RATINGS
    assert card.established is False, "nothing is entered; readiness is not established"
    assert card.established_note


def test_no_household_at_all_still_produces_a_card():
    card = SC.evaluate(None)
    assert len(card.components) == 8
    assert card.rating in B.RATINGS


@pytest.mark.parametrize("funnel", list(FUNNELS))
def test_every_funnel_evaluates_without_raising(funnel):
    h = Household(has_spouse=True, monthly_expenses=5_000.0,
                  essential_monthly_expenses=3_500.0, cash_savings=20_000.0)
    set_funnel(h, funnel)
    card = SC.evaluate(h)
    assert len(card.components) == 8
    assert card.funnel == funnel


def test_a_serving_member_gets_honest_c5s_rather_than_invented_numbers():
    """
    §4b: `Profile` has no concept of serving — no grade, no promotions, no
    separation, no pension starting. The projection still RUNS for a serving
    member, which is the trap: it returns a confident answer that omits the
    largest asset they will ever own.
    """
    h = sample("e5_6yrs_brs.mpfplan.json")
    set_funnel(h, FUNNEL_SERVING)
    h.essential_monthly_expenses = 3_200.0
    card = SC.evaluate(h)

    for key in ("floor", "funded", "longevity", "tax", "survivor"):
        c = card.by_key(key)
        assert c.status == K.NOT_MODELLED, f"{key} is {c.status}"
        assert c.rating == C5
        assert c.applies is False, f"{key} must not drag the roll-up"
        assert c.detail, f"{key} must say WHY it cannot be rated"

    # ... and the ones that need no projection are rated anyway.
    assert card.by_key("healthcare").status == K.RATED
    assert card.by_key("liquidity").status == K.RATED

    # The overall rating refuses to be called on that little.
    assert card.established is False
    assert card.coverage < SC.MIN_COVERAGE


def test_the_serving_note_is_carried_not_paraphrased():
    h = sample("e5_6yrs_brs.mpfplan.json")
    e = IN.for_household(h)
    assert e.covers_future is False
    assert e.coverage_note == IN.SERVING_NOTE
    assert SC.evaluate(h).by_key("funded").detail == IN.SERVING_NOTE


def test_the_floor_refuses_to_guess_the_essential_split():
    """
    §8: users understate the essential figure, and a floor rated against the
    app's own fallback is a confident wrong answer. The instruction is to say
    so and rate C-5, not to guess.

    Tested on a household where the split genuinely decides the band. The
    retiree sample no longer serves — its guaranteed income covers total
    spending nearly twice over, so the band is settled by arithmetic before the
    question is asked. See the test below.
    """
    h = sample("retired_o5_26yrs.mpfplan.json")
    assert h.essential_monthly_expenses == 0
    h.monthly_expenses = 26_000.0          # floor covers well under all of it
    c = SC.evaluate(h).by_key("floor")
    assert c.status == K.NOT_ENTERED
    assert c.rating == C5
    assert c.applies is True, "the user can fix this, so it counts"
    assert any("not answered" in e.value for e in c.evidence)

    # And with the answer supplied it rates, on the answer.
    h.essential_monthly_expenses = 9_000.0
    c2 = SC.evaluate(h).by_key("floor")
    assert c2.status == K.RATED
    assert c2.rating == C1

    h.essential_monthly_expenses = 0.0
    h.monthly_expenses = 9_000.0
    h.essential_monthly_expenses = 5_400.0
    c3 = SC.evaluate(h).by_key("floor")
    assert c3.status == K.RATED
    assert c3.rating == C1


def test_the_floor_rates_without_the_split_when_the_split_cannot_change_it():
    """
    Refusing to guess is not the same as refusing to state a certainty.

    `essential_monthly()` clamps essentials to total spending, so essentials
    are never more than the total. If guaranteed income covers the WHOLE total,
    the ratio is at least 1.0 by arithmetic, whatever the split turns out to
    be — and reporting the app's most important component as "not established"
    for the household §3 says it exists to recognise would be a wrong answer,
    not a careful one.
    """
    h = sample("retired_o5_26yrs.mpfplan.json")
    assert h.essential_monthly_expenses == 0, "still unanswered"

    c = SC.evaluate(h).by_key("floor")
    assert c.status == K.RATED
    assert c.rating == C1
    # The derivation is stated, and states that it does not depend on the split.
    assert any("at least" in e.value for e in c.evidence)
    assert any("whatever the split" in (e.note or "") for e in c.evidence)
    # And it still says why answering the question is worth doing anyway.
    assert "survivor" in c.detail.lower()


def test_only_the_certain_band_is_awarded_without_the_split():
    """
    Below full coverage the split really does decide the band, so it stays
    NOT_ENTERED. A floor covering half of total spending is C-4 if essentials
    are the whole total and C-1 if they are half of it — that is a guess, and
    the component does not make it.
    """
    h = retiree()
    h.essential_monthly_expenses = 0.0
    floor = 17_133.0                       # roughly this sample's indexed income
    h.monthly_expenses = floor * 2.0       # covered about half
    c = SC.evaluate(h).by_key("floor")
    assert c.status == K.NOT_ENTERED
    assert c.rating == C5


def test_every_rated_component_states_at_least_two_figures():
    """§8: a number with no visible derivation is worse than no number."""
    h = retiree()
    h.estate.n_children = 2
    h.estate.target_legacy_per_child = 100_000.0
    card = SC.evaluate(h)
    rated = [c for c in card.components if c.status == K.RATED]
    assert len(rated) >= 6, "six of eight should work for a retiree"
    for c in rated:
        assert len(c.evidence) >= 2, f"{c.key} rated with {len(c.evidence)} figures"
        assert c.headline and c.detail, f"{c.key} has no explanation"


def test_every_component_points_at_a_page_that_exists():
    """§6: a component reading C-3 drills into the page that explains it."""
    card = SC.evaluate(retiree())
    for c in card.components:
        for path in [c.page] + [p for p, _, _ in c.also]:
            assert (ROOT / path).exists(), f"{c.key} -> {path}"


def test_the_scorecard_never_gates_anything():
    """
    §2 with more force, not less: the scorecard is not a permissions system.
    A card of straight C-5s and a card of straight C-1s expose exactly the
    same eight components and the same links.
    """
    low = SC.evaluate(Household())
    high = SC.evaluate(retiree())
    assert [c.key for c in low.components] == [c.key for c in high.components]
    assert [c.page for c in low.components] == [c.page for c in high.components]


# ==========================================================================
# The eight, as a set
# ==========================================================================

def test_there_are_exactly_the_eight_components_architecture_names():
    keys = [c.key for c in SC.evaluate(Household()).components]
    assert keys == ["floor", "funded", "longevity", "tax", "healthcare",
                    "survivor", "liquidity", "legacy"]


def test_the_income_floor_carries_the_most_weight():
    card = SC.evaluate(retiree())
    weights = {c.key: c.weight for c in card.components}
    assert weights["floor"] == max(weights.values())


def test_a_rated_veteran_with_no_pension_still_gets_a_partial_floor():
    """
    §4b's nuance: `pension_as_bond()` sums retired pay + VA + CRSC, so the
    floor is not retiree-only. A veteran with a rating and no pension has one.
    """
    h = Household(has_spouse=False, monthly_expenses=4_000.0,
                  essential_monthly_expenses=3_000.0)
    h.member = ServiceMember(birth_year=1980, component=VETERAN,
                             va_disability_monthly=2_000.0, va_rating=80)
    set_funnel(h, FUNNEL_VETERAN)
    c = SC.evaluate(h).by_key("floor")
    assert c.status == K.RATED
    assert any("untaxed" in e.label.lower() for e in c.evidence)
    assert c.rating <= C3


# ==========================================================================
# Liquidity and debt, which needs no projection at all
# ==========================================================================

def test_high_rate_debt_costs_bands_and_names_the_worst_one():
    h = Household(monthly_expenses=4_000.0, cash_savings=24_000.0)
    h.member = ServiceMember(birth_year=1980, component=RETIRED,
                             retired_pay_monthly=4_000.0)
    clean = SC.evaluate(h).by_key("liquidity")
    assert clean.rating == C1

    h.debts = [Debt("Visa", 30_000.0, 0.2249, 600.0, "Credit card")]
    dirty = SC.evaluate(h).by_key("liquidity")
    assert dirty.rating > clean.rating
    assert any("Visa" in (e.note or "") for e in dirty.evidence)


def test_the_reserve_target_follows_prime_directive_three_in_six_out():
    serving = Household(monthly_expenses=4_000.0, cash_savings=12_000.0)
    serving.member = ServiceMember(birth_year=1995, component=ACTIVE)
    assert SC.evaluate(serving).by_key("liquidity").rating == C1

    out = Household(monthly_expenses=4_000.0, cash_savings=12_000.0)
    out.member = ServiceMember(birth_year=1980, component=VETERAN)
    assert SC.evaluate(out).by_key("liquidity").rating > C1


# ==========================================================================
# The Monte Carlo component: excluded until it is run, never guessed
# ==========================================================================

def test_longevity_is_excluded_until_the_market_test_is_run():
    card = SC.evaluate(retiree())
    c = card.by_key("longevity")
    assert c.status == K.NOT_RUN
    assert c.applies is False
    assert card.needs_longevity is True


def test_the_success_rate_is_the_share_of_paths_that_never_ran_short():
    np = pytest.importorskip("numpy")

    class FakeMC:
        n_paths = 4
        shortfall_no_convert = np.array([0.0, 0.0, 5_000.0, 0.0])
        shortfall_convert = np.array([0.0, 0.0, 0.0, 0.0])

        def percentiles(self, arr, qs=(50, 95)):
            return {q: float(np.percentile(arr, q)) for q in qs}

    assert IN.success_rate(FakeMC()) == 0.75
    assert IN.success_rate(None) == 0.0

    card = SC.evaluate(retiree(), mc=FakeMC())
    c = card.by_key("longevity")
    assert c.status == K.RATED
    assert c.rating == C3            # 0.75 sits in the 0.70-to-0.85 band
    assert card.needs_longevity is False


# ==========================================================================
# Both sample plans
# ==========================================================================

@pytest.mark.parametrize("name", ["e5_6yrs_brs.mpfplan.json",
                                  "retired_o5_26yrs.mpfplan.json"])
def test_both_sample_plans_produce_a_rating_without_raising(name):
    h = sample(name)
    card = SC.evaluate(h)
    assert len(card.components) == 8
    assert card.rating in B.RATINGS
    assert card.funnel in FUNNELS
    for c in card.components:
        assert c.headline, f"{c.key} has no headline"
        assert c.code.startswith("C-")
        assert c.bar and c.icon


def test_the_retiree_sample_rates_six_of_eight_once_it_is_answered():
    """§7's step-2 expectation: six of eight work immediately for a retiree."""
    h = retiree()
    h.estate.n_children = 2
    h.estate.target_legacy_per_child = 100_000.0
    card = SC.evaluate(h)
    rated = [c.key for c in card.components if c.status == K.RATED]
    assert len(rated) >= 6, rated
    assert "longevity" not in rated       # the only one that needs the slow run
    assert card.established is True


# ==========================================================================
# The page
# ==========================================================================

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
PAGE = "pages/02_Scorecard.py"


def _run(h: Household):
    at = AppTest.from_file(str(ROOT / PAGE), default_timeout=300)
    at.session_state["household"] = h
    at.session_state["plan_version"] = 0
    return at.run()


def test_the_page_renders_for_a_retiree():
    at = _run(retiree())
    assert not at.exception, at.exception
    text = " ".join(str(m.value) for m in at.markdown)
    assert "C-" in text


@pytest.mark.parametrize("funnel", list(FUNNELS))
def test_the_page_renders_for_every_funnel(funnel):
    h = Household(has_spouse=True, monthly_expenses=5_000.0,
                  essential_monthly_expenses=3_500.0, cash_savings=20_000.0)
    set_funnel(h, funnel)
    at = _run(h)
    assert not at.exception, at.exception


def test_the_page_sends_an_unasked_plan_to_the_front_door():
    at = _run(Household())
    assert not at.exception, at.exception
    assert at.info, "an unasked plan should be pointed at Start, not shown a blank card"


def test_the_page_is_registered_in_the_start_group_after_intake():
    router = (ROOT / "Military_Finance.py").read_text()
    assert PAGE in router
    start = router.index('"Start": [')
    after = router.index("]", start)
    block = router[start:after]
    assert block.index("01_Intake") < block.index("02_Scorecard")
    # And the rest of the menu is untouched: 25 pages were registered before
    # this one, and every audience group is still there.
    assert router.count('_page("pages/') == 26
    for group in ("General", "Currently Serving", "Veteran", "Retiree"):
        assert f'"{group}": [' in router


# ==========================================================================
# The target retirement age, which nothing else in the app reads
# ==========================================================================

def test_the_target_retirement_age_actually_moves_the_projection():
    """
    Intake asks for it and, before this package, nothing read it — every plan
    ran to the same assumed wage-stop age. A scorecard that claims to assess
    readiness to RETIRE has to honour the answer.
    """
    h = retiree()
    h.member.civilian_wages_annual = 95_000.0

    h.target_retirement_age = 55
    early = SC.inputs.build_profile(h)
    h.target_retirement_age = 72
    late = SC.inputs.build_profile(h)

    assert early.primary.work_through_year < late.primary.work_through_year

    h.target_retirement_age = 55
    early_card = SC.evaluate(h)
    h.target_retirement_age = 72
    late_card = SC.evaluate(h)
    assert (early_card.by_key("tax").evidence[0].value
            != late_card.by_key("tax").evidence[0].value)


def test_the_funded_component_says_when_no_retirement_age_was_entered():
    h = retiree()
    h.member.civilian_wages_annual = 95_000.0
    h.target_retirement_age = 0
    notes = " ".join(e.note or "" for e in SC.evaluate(h).by_key("funded").evidence)
    assert "No target retirement age" in notes


# ==========================================================================
# The assumption hunt
# ==========================================================================
# Added at review. §4b says a serving member's future is the part the app
# cannot model, and §8 says a rating must state the figures it came from. The
# dangerous combination is a component that CAN run for a serving member but
# only by assuming something they have not decided. Healthcare is the one.

def test_healthcare_does_not_award_a_clean_band_on_a_twenty_year_assumption():
    """
    `benefits/healthcare.default_leave_service_age()` assumes twenty years, so
    an E-5 at six years is modelled as retiring with TRICARE For Life for life
    and the findings come back clean. Read straight off, that is C-1 —
    "nothing in the cover has a gap in it" — for a member whose single largest
    open decision is whether to stay. Separating at twelve does not reduce this
    cover, it removes it.
    """
    h = sample("e5_6yrs_brs.mpfplan.json")
    assert h.member.is_serving and h.member.years_of_service < 20
    c = SC.evaluate(h).by_key("healthcare")

    assert c.status == K.RATED
    assert c.rating >= C2, "a band resting on an unreached 20 years is not C-1"
    # §8: the assumption is a figure the rating came from, so it is on screen.
    assert any("assumes you serve to" in e.label.lower() for e in c.evidence)
    said = (c.headline + " " + c.detail).lower()
    assert "twenty" in said, "it names the assumption in words, not just a figure"
    assert "6 years" in said, "it says how many years they have actually served"


def test_healthcare_rates_a_retiree_without_the_assumption_penalty():
    """The assumption only exists for someone still serving."""
    h = retiree()
    c = SC.evaluate(h).by_key("healthcare")
    assert c.status == K.RATED
    assert not any("assumes you serve to" in e.label.lower() for e in c.evidence)


def test_no_component_rates_a_serving_member_off_the_retiree_projection():
    """
    §4b: `Profile` has no concept of serving, so the projection runs for a
    serving member and returns a confident answer that omits the largest asset
    they will ever own. Every component that reads it must refuse.
    """
    h = sample("e5_6yrs_brs.mpfplan.json")
    card = SC.evaluate(h)
    for key in ("funded", "longevity", "tax"):
        c = card.by_key(key)
        assert c.status == K.NOT_MODELLED, f"{key} rated off an unusable projection"
        assert c.applies is False, f"{key} must not count in the roll-up"


def test_a_serving_members_card_says_what_it_could_not_establish():
    h = sample("e5_6yrs_brs.mpfplan.json")
    card = SC.evaluate(h)
    assert card.established is False
    assert "not established" in card.established_note.lower()
    # and every blocker explains itself rather than showing a bare C-5
    for c in card.blockers:
        assert c.headline.strip(), f"{c.key} is unrated with no reason given"
        assert c.detail.strip(), f"{c.key} is unrated with no explanation"


def test_every_rated_component_on_both_samples_shows_its_derivation():
    """§8, swept across both samples rather than one constructed household."""
    for name in ("e5_6yrs_brs.mpfplan.json", "retired_o5_26yrs.mpfplan.json"):
        card = SC.evaluate(sample(name))
        for c in card.components:
            if c.status != K.RATED:
                continue
            assert len(c.evidence) >= 2, f"{name}/{c.key}: {len(c.evidence)} figures"
            assert c.headline.strip(), f"{name}/{c.key}: no headline"


def test_the_scorecard_gates_nothing():
    """
    §2 with more force, not less: a C-4 hides nothing and unlocks nothing.
    The page must not import the funnel, and no component may carry anything
    that reads as a permission.
    """
    page = (ROOT / "pages" / "02_Scorecard.py").read_text(encoding="utf-8")
    assert "funnel" not in page, "the scorecard page must not read the funnel"
    card = SC.evaluate(retiree())
    for c in card.components:
        assert c.page, f"{c.key} has no way out"
        for attr in ("locked", "hidden", "disabled", "unlocks", "requires"):
            assert not hasattr(c, attr), f"Component.{attr} is a permission"
