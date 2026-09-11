"""
The readiness scorecard: eight C-ratings and one roll-up.

THE APP'S ANSWER. `docs/ARCHITECTURE.md` §1 states the purpose once -- the app
assesses readiness to retire, and everything in it either feeds the score or
explains it. §3 specifies this package: eight components, each rated C-1 to
C-5, each weighted, each gated on whether it applies, rolling up to a single
rating renormalised over applicable weight.

It is step 2 of the §7 build order and it computes almost nothing new. The
spine already exists (`retirement/projection.run_projection`), the per-path
shortfall already exists (`retirement/montecarlo`), and sixteen modules already
emit findings. This layer points them at readiness instead of at the Roth
question, and reports the answer in a vocabulary every member already reads.

    from engine import scorecard
    card = scorecard.evaluate(h)                 # cheap: projection only
    card = scorecard.evaluate(h, mc=summary)     # with the market test

WHAT IT IS NOT
    * Not a permissions system. A C-4 hides nothing and unlocks nothing. §2's
      rule about the funnel applies here with more force, not less.
    * Not a new analysis engine. If a component wants a number, the number
      comes from a module that already computes it.
    * Not a source of invented figures. Three of the five statuses exist so
      that "I cannot say" has somewhere honest to live.

THE ROLL-UP, and why it is the whole reason the funnels work:

    score = sum(weight * readiness) / sum(weight)   over APPLICABLE only

which is `coach/prime_directive.evaluate()` unchanged. A serving member rated
on three components and a retiree rated on eight produce numbers that mean the
same thing, because the denominator moves with the numerator. Scoring an
inapplicable component zero would make three funnels produce three
incomparable answers -- that is the exact problem this mechanism already
solves, and it is already tested (tests/test_coach_and_career.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.profile import Household
from engine.funnel import funnel_of, label_for, is_chosen, spec, FUNNEL_UNSET
from engine.scorecard import bands as B
from engine.scorecard import inputs as I
from engine.scorecard import components as K
from engine.scorecard.bands import C1, C2, C3, C4, C5, RATINGS
from engine.scorecard.components import (Component, Evidence, BUILDERS, RATED,
                                         NOT_ENTERED, NOT_MODELLED, NOT_RUN,
                                         NOT_APPLICABLE, STATUS_LABEL)
from engine.scorecard.inputs import Engines, success_rate, run_longevity, build_profile

__all__ = [
    "evaluate", "Scorecard", "Component", "Evidence", "Engines",
    "C1", "C2", "C3", "C4", "C5", "RATINGS",
    "RATED", "NOT_ENTERED", "NOT_MODELLED", "NOT_RUN", "NOT_APPLICABLE",
    "STATUS_LABEL", "bands", "inputs", "components",
    "success_rate", "run_longevity", "build_profile", "needs_longevity",
    "needs_front_door", "front_door_reading", "MIN_COVERAGE",
]


# --------------------------------------------------------------------------
# The front door
# --------------------------------------------------------------------------
# The scorecard page must not know that funnels exist -- it renders a
# Scorecard, and tests/test_intake_pages.py enforces that no page outside the
# front door reaches for one (§2: the funnel is not a permissions system, and
# a page that reads it is one gate away from becoming one). So the two things
# a page legitimately needs to know live here instead, stated as questions
# about the PLAN rather than about the funnel.

def needs_front_door(h: Household | None) -> bool:
    """
    True when the one question at the front door has not been answered.

    A page that gets True should send the user to Start rather than render an
    empty card: an unanswered plan produces a scorecard of blanks, and a
    scorecard of blanks is not an answer, it is a reproach.
    """
    return not is_chosen(getattr(h, "funnel", "") if h is not None else "")


def front_door_reading(h: Household | None) -> str:
    """
    What an unanswered plan READS as, from what it already carries.

    Offered as a reading and never as a choice -- `00_Start.py` makes the same
    distinction for the same reason. Empty when there is nothing to read.
    """
    if h is None:
        return ""
    s = spec(funnel_of(h))
    return s.label if s else ""

#: Below this share of the scorecard's weight, there is not enough rated to
#: call an overall readiness at all, and the roll-up is reported as C-5 --
#: "not established" -- rather than as a band.
#:
#: WHY THIS EXISTS. Without it a blank plan rolls up to C-3 on one incidental
#: component, and a serving member rolls up to whatever their emergency fund
#: happens to be. Both are false answers to the question the app exists to
#: answer, and a false answer is worse than "not established" -- §8, exactly:
#: a scorecard makes wrong figures MORE dangerous because it compresses them
#: into a single reassuring letter. The weighted score is still reported, and
#: still means what it says: it is the rating of the part that could be rated.
MIN_COVERAGE = 0.5

#: How the overall rating is framed for each funnel (§2: three funnels, three
#: scorecard framings, one engine). Nothing here changes what is computed.
FRAME = {
    "serving": "Readiness is not one number while you are still in — it is one "
               "per course of action. What is rated below is what the app can "
               "already see from where you stand today.",
    "veteran": "A civilian problem carrying military assets: no pension, and VA "
               "compensation that may be the only indexed income you have.",
    "retiree": "The future is largely locked, so what is rated is sequencing — "
               "when to claim, how much to convert, which account to draw first.",
}


@dataclass
class Scorecard:
    components: list = field(default_factory=list)

    funnel: str = FUNNEL_UNSET
    funnel_label: str = ""
    frame: str = ""

    rating: int = C5
    readiness: float = 0.0
    score: float = 0.0             # 0..100, the prime_directive scale

    n_rated: int = 0
    n_applicable: int = 0
    n_total: int = 0
    applicable_weight: float = 0.0
    total_weight: float = 0.0

    limiting: object | None = None       # the worst applicable component
    blockers: list = field(default_factory=list)   # what could not be rated, and why

    #: False when too little of the scorecard could be rated to call an
    #: overall readiness. `rating` is then C-5 and `score` describes only the
    #: part that WAS rated. See MIN_COVERAGE.
    established: bool = True
    established_note: str = ""

    engines: object | None = None

    # ---- presentation, mirroring Component -------------------------------
    @property
    def audience(self) -> str:
        """The funnel key, under a name a page may use. See needs_front_door."""
        return self.funnel

    @property
    def audience_label(self) -> str:
        return self.funnel_label

    @property
    def code(self) -> str:
        return B.code(self.rating)

    @property
    def band_label(self) -> str:
        return B.label(self.rating)

    @property
    def gloss(self) -> str:
        return B.gloss(self.rating)

    @property
    def bar(self) -> str:
        return B.bar(self.rating)

    @property
    def icon(self) -> str:
        return B.icon(self.rating)

    @property
    def coverage(self) -> float:
        """Share of the scorecard's weight that could be rated at all."""
        if self.total_weight <= 0:
            return 0.0
        return self.applicable_weight / self.total_weight

    def by_key(self, key: str):
        return next((c for c in self.components if c.key == key), None)

    @property
    def active(self) -> list:
        return [c for c in self.components if c.applies]

    @property
    def needs_longevity(self) -> bool:
        """True when running Monte Carlo would actually change the card."""
        c = self.by_key("longevity")
        return c is not None and c.status == NOT_RUN


def needs_longevity(card: Scorecard) -> bool:
    return card.needs_longevity


def evaluate(h: Household, *, mc=None, engines=None) -> Scorecard:
    """
    Rate a household. Never raises, for any household, including a blank one.

    `mc` is an `MCSummary` the caller already has -- typically from
    `st.session_state["mc_summary"]`, keyed on `Profile.to_json()`. Nothing
    here runs Monte Carlo: it takes seconds, and the front door has to open
    immediately. Without it the longevity component reports NOT_RUN and is
    excluded from the roll-up, so the overall rating stays honest rather than
    being quietly penalised for work the user has not asked for.
    """
    if h is None:
        h = Household()

    e = engines if engines is not None else I.for_household(h, mc=mc)

    card = Scorecard(engines=e)
    card.funnel = funnel_of(h)
    card.funnel_label = label_for(card.funnel)
    card.frame = FRAME.get(card.funnel, "")

    built = []
    for build in BUILDERS:
        try:
            built.append(build(h, e))
        except Exception as exc:                              # pragma: no cover
            c = K.Component(key=getattr(build, "__name__", "component"),
                            order=99, title=getattr(build, "__name__", "Component"))
            c.status = K.NOT_MODELLED
            c.rating = C5
            c.headline = "This component could not be computed."
            c.detail = (f"{type(exc).__name__}: {exc}. That is a defect in the "
                        f"app, not in your plan — the rest of the scorecard "
                        f"below is unaffected.")
            built.append(c)

    card.components = sorted(built, key=lambda c: c.order)

    r = B.roll_up(card.components)
    card.rating = r.rating

    card.readiness = r.readiness
    card.score = r.score
    card.n_applicable = r.n_applicable
    card.n_total = r.n_total
    card.applicable_weight = r.applicable_weight
    card.total_weight = r.total_weight
    card.n_rated = sum(1 for c in card.components if c.status == RATED)

    rated = [c for c in card.components if c.status == RATED]
    if rated:
        # The limiting component: worst band first, heaviest weight breaking a
        # tie. A unit is no readier than the thing holding it back, and this is
        # the single most useful line on the page.
        card.limiting = sorted(rated, key=lambda c: (-c.rating, -c.weight))[0]

    card.blockers = [c for c in card.components if c.status != RATED]

    if card.coverage < MIN_COVERAGE:
        card.established = False
        card.rating = C5
        weight = f"{card.coverage * 100:.0f}%"
        card.established_note = (
            f"Only {weight} of the scorecard could be rated, so there is no "
            f"overall readiness to report yet. C-5 here means NOT ESTABLISHED, "
            f"not failing: the components below say which are waiting on an "
            f"answer from you and which are waiting on the app.")
    return card
