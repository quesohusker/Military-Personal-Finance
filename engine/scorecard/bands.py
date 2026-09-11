"""
The readiness vocabulary: C-1 to C-5, and the arithmetic that produces one.

WHY BANDS AND NOT A 0-100 SCORE (docs/ARCHITECTURE.md §3, §8). A score invites
false precision, and -- more importantly -- a number cannot say "you have not
told me yet" or "this does not apply to you" without lying about it. A C-rating
can, because C-5 already means *not ready, undergoing reset*, and the military
reader already knows that a C-5 unit is not a failing unit; it is a unit whose
readiness has not been established. That is exactly the honest home for a blank
field and for a projection that does not reach far enough yet.

There are three arithmetic pieces here and nothing else:

    band_for_ratio()     a measured ratio -> a band, against declared cuts
    band_from_findings() severity counts from an existing engine -> a band
    roll_up()            weighted ratings -> one rating, renormalised

`roll_up` is `engine/coach/prime_directive.evaluate()`'s mechanism, unchanged:
each item carries a weight and an applicability gate, and the total is divided
by the APPLICABLE weight rather than by all of it. That is what lets a veteran
rated on five components and a retiree rated on eight produce numbers that mean
the same thing.
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------
# The five bands
# --------------------------------------------------------------------------

C1 = 1
C2 = 2
C3 = 3
C4 = 4
C5 = 5

RATINGS: tuple[int, ...] = (C1, C2, C3, C4, C5)

CODE: dict[int, str] = {C1: "C-1", C2: "C-2", C3: "C-3", C4: "C-4", C5: "C-5"}

LABEL: dict[int, str] = {
    C1: "Fully ready",
    C2: "Ready, minor shortfalls",
    C3: "Ready, significant shortfalls",
    C4: "Not ready — requires resources",
    C5: "Not ready — undergoing reset",
}

#: One line saying what the band means for a retirement plan rather than for a
#: battalion. The page shows this under the code; the code alone is jargon to a
#: spouse reading over a shoulder.
GLOSS: dict[int, str] = {
    C1: "Nothing here needs attention.",
    C2: "Sound, with something worth tidying.",
    C3: "It works, but a real gap is carried inside it.",
    C4: "This does not hold up. It needs a decision or money.",
    C5: "Not established — either nothing is entered, or it cannot be computed yet.",
}

#: State encoded as SHAPE, not colour (four cells, filled left to right), so
#: the scorecard still reads at a glance in greyscale or to a colour-blind eye.
BAR: dict[int, str] = {
    C1: "████", C2: "███░", C3: "██░░", C4: "█░░░", C5: "░░░░",
}

#: A second, redundant encoding. Distinct glyphs, not four shades of one dot.
ICON: dict[int, str] = {C1: "✅", C2: "🟦", C3: "⚠️", C4: "🚨", C5: "⬜"}


def code(rating: int) -> str:
    return CODE.get(int(rating), CODE[C5])


def label(rating: int) -> str:
    return LABEL.get(int(rating), LABEL[C5])


def gloss(rating: int) -> str:
    return GLOSS.get(int(rating), GLOSS[C5])


def bar(rating: int) -> str:
    return BAR.get(int(rating), BAR[C5])


def icon(rating: int) -> str:
    return ICON.get(int(rating), ICON[C5])


def clamp(rating: int) -> int:
    return max(C1, min(C5, int(rating)))


def demote(rating: int, steps: int = 1) -> int:
    """Move a rating toward C-5. Used when a second signal makes it worse."""
    return clamp(int(rating) + max(0, int(steps)))


def promote(rating: int, steps: int = 1) -> int:
    return clamp(int(rating) - max(0, int(steps)))


def worst(*ratings: int) -> int:
    """The limiting rating. A plan is no readier than the thing holding it back."""
    vals = [clamp(r) for r in ratings if r]
    return max(vals) if vals else C5


# --------------------------------------------------------------------------
# Rating <-> readiness
# --------------------------------------------------------------------------
# A band is an ordinal, so it cannot be averaged directly. `readiness` is the
# 0..1 quantity the roll-up sums: C-1 is 1.0, C-5 is 0.0, evenly spaced.

def readiness(rating: int) -> float:
    return (5.0 - clamp(rating)) / 4.0


#: Band cuts on the 0..1 readiness scale, placed at the MIDPOINTS between the
#: component values (1.0, 0.75, 0.5, 0.25, 0.0). Midpoints rather than round
#: numbers so that a scorecard of straight C-3s rolls up to C-3 -- with cuts at
#: 0.9/0.75/0.55/0.35 it would roll up to C-4, which is the kind of quiet
#: distortion that makes an aggregate untrustworthy.
READINESS_CUTS: tuple[float, float, float, float] = (0.875, 0.625, 0.375, 0.125)


def band_for_readiness(x: float) -> int:
    """Invert `readiness`: a 0..1 figure back to the band it sits in."""
    return band_for_ratio(x, READINESS_CUTS)


# --------------------------------------------------------------------------
# A measured ratio -> a band
# --------------------------------------------------------------------------

def band_for_ratio(value: float, cuts) -> int:
    """
    Band a HIGHER-IS-BETTER figure against four descending cuts.

    `cuts` is (c1_min, c2_min, c3_min, c4_min); anything below the last is C-5.
    Declaring the cuts at the call site is deliberate: every threshold in this
    package is visible next to the thing it bands, because a threshold buried
    in a helper is a threshold nobody audits.
    """
    c1, c2, c3, c4 = (float(c) for c in cuts)
    v = float(value)
    if v >= c1:
        return C1
    if v >= c2:
        return C2
    if v >= c3:
        return C3
    if v >= c4:
        return C4
    return C5


def band_for_cost(value: float, cuts) -> int:
    """
    Band a LOWER-IS-BETTER figure against four ascending cuts.

    `cuts` is (c1_max, c2_max, c3_max, c4_max); anything above the last is C-5.
    """
    c1, c2, c3, c4 = (float(c) for c in cuts)
    v = float(value)
    if v <= c1:
        return C1
    if v <= c2:
        return C2
    if v <= c3:
        return C3
    if v <= c4:
        return C4
    return C5


# --------------------------------------------------------------------------
# Existing findings -> a band
# --------------------------------------------------------------------------
# §4b: sixteen modules already emit (severity, headline, detail). The scorecard
# is an aggregator, so wherever an engine has already made the judgement, the
# band is read off its severities rather than recomputed from the same inputs
# with a second, disagreeing rule.

SEVERITIES = ("bad", "warn", "info", "good")


def count_severities(findings) -> dict[str, int]:
    """Tally (severity, headline, detail) triples -- or estate.planning.Finding,
    which iterates as one."""
    out = {s: 0 for s in SEVERITIES}
    for f in findings or ():
        sev = getattr(f, "severity", None)
        if sev is None:
            try:
                sev = f[0]
            except Exception:
                continue
        if sev in out:
            out[sev] += 1
    return out


def band_from_findings(findings) -> int:
    """
    The ladder, stated once:

        bad >= 2   -> C-5
        bad == 1   -> C-4
        warn >= 3  -> C-3
        warn >= 1  -> C-2
        otherwise  -> C-1

    A single 'bad' is C-4 ("requires resources") because that is what a 'bad'
    finding is in every module that emits one: something that costs real money
    or leaves a family unprotected. Two of them is a reset.
    """
    n = count_severities(findings)
    if n["bad"] >= 2:
        return C5
    if n["bad"] >= 1:
        return C4
    if n["warn"] >= 3:
        return C3
    if n["warn"] >= 1:
        return C2
    return C1


# --------------------------------------------------------------------------
# The roll-up
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class RollUp:
    rating: int = C5
    readiness: float = 0.0
    score: float = 0.0            # 0..100, the prime_directive scale
    applicable_weight: float = 0.0
    total_weight: float = 0.0
    n_applicable: int = 0
    n_total: int = 0

    @property
    def coverage(self) -> float:
        """Share of the scorecard's weight that could be rated at all."""
        if self.total_weight <= 0:
            return 0.0
        return self.applicable_weight / self.total_weight


def roll_up(items) -> RollUp:
    """
    Weighted mean readiness over APPLICABLE weight only, then banded.

    `items` is anything with `.applies`, `.weight` and `.rating` -- the same
    contract `prime_directive.evaluate()` uses over its `Step`s. A component
    that does not apply is excluded from both the numerator and the
    denominator; it is never scored zero, because scoring an inapplicable
    component zero is the single easiest way to make three funnels produce
    three incomparable numbers.
    """
    items = list(items or ())
    total_weight = sum(float(i.weight) for i in items)
    active = [i for i in items if i.applies]
    applicable_weight = sum(float(i.weight) for i in active)

    if applicable_weight <= 0:
        return RollUp(rating=C5, readiness=0.0, score=0.0,
                      applicable_weight=0.0, total_weight=total_weight,
                      n_applicable=0, n_total=len(items))

    earned = sum(float(i.weight) * readiness(i.rating) for i in active)
    r = earned / applicable_weight
    return RollUp(rating=band_for_readiness(r), readiness=r,
                  score=round(100.0 * r, 1),
                  applicable_weight=applicable_weight,
                  total_weight=total_weight,
                  n_applicable=len(active), n_total=len(items))
