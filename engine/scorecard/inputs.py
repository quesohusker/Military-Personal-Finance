"""
Everything expensive the scorecard reads, behind one small surface.

The scorecard is an aggregator (docs/ARCHITECTURE.md §4b) and computes almost
nothing itself. What it needs is:

    * an engine `Profile`, built by `retirement/roth_bridge.to_roth_profile()`
    * a deterministic `ProjectionResult` from `run_projection(convert=False)`
    * optionally an `MCSummary` from `run_monte_carlo()`

The first two are cheap -- a projection is a single pass over sixty years and
lands in single-digit milliseconds -- so `Engines.for_household()` runs them
eagerly. The third is NOT: three hundred paths run two projections each and
take a few seconds, which is far too long for a page that is meant to be the
front door. So Monte Carlo is never run here unless it is asked for by name,
and the page holds it in `st.session_state["mc_summary"]` keyed on
`Profile.to_json()` -- the same key and the same reserved slot the Roth page
uses, so `ui.panel.invalidate()` clears both.

NOTHING IN THIS MODULE RAISES. A scorecard that crashes on a half-entered plan
is worse than one that says "not established": the whole point of C-5 is to
have somewhere honest to put a failure. Every engine call is guarded and the
reason is carried on `Engines.note` for the component to quote.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.profile import Household


@dataclass
class Engines:
    """The computed inputs, plus why any of them is missing."""
    profile: object | None = None
    projection: object | None = None
    mc: object | None = None

    profile_error: str = ""
    projection_error: str = ""

    #: True when the projection exists but does not describe this household's
    #: future -- the serving case. `Profile` has no concept of serving at all
    #: (§4b): no grade, no DIEMS, no promotions, and no pension starting. The
    #: projection still RUNS for a serving member, which is the trap: it runs
    #: and returns a confident answer that omits the largest asset they will
    #: ever own. Components that lean on it must refuse to rate rather than
    #: quote it.
    covers_future: bool = True
    coverage_note: str = ""

    @property
    def has_projection(self) -> bool:
        return self.projection is not None and bool(
            getattr(self.projection, "rows", ()))

    @property
    def has_mc(self) -> bool:
        return self.mc is not None and int(getattr(self.mc, "n_paths", 0)) > 0

    @property
    def usable_projection(self) -> bool:
        """A projection that is both present AND about this person's future."""
        return self.has_projection and self.covers_future

    @property
    def key(self) -> str:
        """The cache key for the expensive work: the engine profile itself."""
        try:
            return self.profile.to_json()
        except Exception:
            return ""


SERVING_NOTE = (
    "The projection does not cover your serving years yet. It has no concept "
    "of being in uniform — no grade, no promotions, no separation date and no "
    "pension starting — so for someone still serving it leaves out the largest "
    "guaranteed asset you will ever own. Rating this from it would invent a "
    "number, so it is left at C-5 until the projection reaches back over your "
    "service."
)


def build_profile(h: Household):
    """
    The engine `Profile` for this household, on the bridge's own defaults --
    with one correction.

    THE TARGET RETIREMENT AGE. Intake asks for it (`funnel.py`, the common
    question set) and, at the time of writing, NOTHING IN THE APP READS IT:
    `roth_bridge.default_inputs()` sets `work_through_year` from a fixed
    `WAGES_STOP_AGE` for everybody. For a scorecard that claims to assess
    readiness to RETIRE, running every plan to the same assumed stop age
    would answer a question nobody asked. So the answer is applied here, on
    the scorecard's own copy of the inputs, clamped into the same bounds the
    bridge clamps everything else into.

    It is applied here and not in the bridge because the bridge is shared with
    the Roth Conversions page, which offers `work_through_year` as an input the
    user can already see and change; silently overriding it there would fight
    with their own widget. This is reported as a gap rather than fixed in
    place -- see the handover notes.
    """
    from engine.retirement import roth_bridge as RB

    ri = RB.default_inputs(h)
    target = int(getattr(h, "target_retirement_age", 0) or 0)
    if target > 0 and h.member is not None:
        age_now = h.member.age(ri.start_year)
        stop = ri.start_year + max(0, target - age_now)
        ri.work_through_year = max(ri.start_year,
                                   min(stop, ri.start_year + RB.MAX_HORIZON_YEARS))
    return RB.to_roth_profile(h, ri)


def run_baseline(p):
    """
    The do-nothing future: no conversions, current settings, one pass.

    `convert=False` is the right baseline for readiness. `MCSummary.win_rate()`
    and the Roth page's paired run answer whether CONVERTING wins; the
    scorecard is asking whether the plan holds, which is a question about the
    plan as it stands (§4, "the machinery is built and pointed at the wrong
    target").
    """
    from engine.retirement.projection import run_projection
    return run_projection(p, convert=False, label="Readiness baseline")


def run_longevity(p, progress=None):
    """Monte Carlo. Seconds, not milliseconds — never call this eagerly."""
    from engine.retirement.montecarlo import run_monte_carlo
    return run_monte_carlo(p, progress=progress)


def success_rate(mc) -> float:
    """
    Share of paths that never ran short. `(shortfall == 0).mean()`.

    §4: this is one line, and it is not reported anywhere in the app today
    because `MCSummary` was built to answer the Roth question instead. The
    no-conversion array is the one to read, for the same reason `run_baseline`
    passes `convert=False`.
    """
    if mc is None:
        return 0.0
    arr = getattr(mc, "shortfall_no_convert", None)
    if arr is None or getattr(arr, "size", 0) == 0:
        return 0.0
    return float((arr <= 1.0).mean())


def covers_future(h: Household) -> tuple[bool, str]:
    """
    Does the projection describe this household's future, or only part of it?

    One rule, and it is the §4b fault line: a serving member's future is
    mostly the part `Profile` cannot express. Everyone else -- veteran,
    retiree, civilian -- is already the shape the projection was written for.
    """
    if h is None or h.member is None:
        return False, "There is no plan to project."
    if h.member.is_serving:
        return False, SERVING_NOTE
    return True, ""


def for_household(h: Household, *, mc=None, with_projection: bool = True) -> Engines:
    """
    Build the inputs. Cheap by default; Monte Carlo only if handed in.

    Pass `mc=` a summary the page already has cached. Nothing here runs it.
    """
    e = Engines(mc=mc)
    e.covers_future, e.coverage_note = covers_future(h)

    if h is None:
        e.profile_error = "There is no plan to project."
        return e

    try:
        e.profile = build_profile(h)
    except Exception as exc:                              # pragma: no cover
        e.profile_error = f"The plan could not be turned into an engine profile: {exc}"
        return e

    if not with_projection:
        return e

    try:
        e.projection = run_baseline(e.profile)
    except Exception as exc:                              # pragma: no cover
        e.projection_error = f"The projection did not run: {exc}"

    return e
