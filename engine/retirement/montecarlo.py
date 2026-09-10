"""
Monte Carlo driver.

The important design choice here is PAIRING: both futures are run on the same
random return sequence. The question is not "how much money will I have" -- it
is "does converting beat not converting". Running the two futures on different
random draws buries that difference in sampling noise. Paired paths let a few
hundred runs answer it cleanly.
"""

from __future__ import annotations
from dataclasses import dataclass, field

import numpy as np

from engine.roth_profile import Profile
from engine.retirement.projection import run_projection, ProjectionResult


@dataclass
class MCSummary:
    n_paths: int = 0
    years: int = 0

    # The settings this run was produced under. Recorded so a summary is
    # self-describing -- anything reporting on it (the LLM briefing, for one)
    # can state the volatility assumption instead of guessing at it.
    return_stdev: float = 0.0
    inflation_stdev: float = 0.0

    # Distribution of legacy value (after heir taxes), per future
    legacy_no_convert: np.ndarray = field(default_factory=lambda: np.array([]))
    legacy_convert: np.ndarray = field(default_factory=lambda: np.array([]))

    # Distribution of lifetime tax, per future
    tax_no_convert: np.ndarray = field(default_factory=lambda: np.array([]))
    tax_convert: np.ndarray = field(default_factory=lambda: np.array([]))

    # Paired differences (convert minus no-convert)
    legacy_delta: np.ndarray = field(default_factory=lambda: np.array([]))
    tax_delta: np.ndarray = field(default_factory=lambda: np.array([]))

    shortfall_no_convert: np.ndarray = field(default_factory=lambda: np.array([]))
    shortfall_convert: np.ndarray = field(default_factory=lambda: np.array([]))

    def win_rate(self) -> float:
        """Share of paths where converting leaves more after-tax value to heirs."""
        if self.legacy_delta.size == 0:
            return 0.0
        return float((self.legacy_delta > 0).mean())

    def tax_win_rate(self) -> float:
        if self.tax_delta.size == 0:
            return 0.0
        return float((self.tax_delta < 0).mean())

    def ruin_rate(self, convert: bool) -> float:
        arr = self.shortfall_convert if convert else self.shortfall_no_convert
        if arr.size == 0:
            return 0.0
        return float((arr > 1.0).mean())

    def percentiles(self, arr: np.ndarray, qs=(5, 25, 50, 75, 95)) -> dict:
        if arr.size == 0:
            return {q: 0.0 for q in qs}
        return {q: float(np.percentile(arr, q)) for q in qs}


def _make_paths(mc, n_years: int, rng: np.random.Generator):
    """
    Return shocks are drawn as deviations from the profile's expected real
    return, so the mean path reproduces the deterministic projection exactly.
    """
    shocks = rng.normal(0.0, mc.return_stdev, size=(mc.n_paths, n_years))
    return shocks


def run_monte_carlo(p: Profile, progress=None) -> MCSummary:
    mc = p.monte_carlo
    rng = np.random.default_rng(mc.random_seed)

    n_years = p.final_year() - p.assumptions.start_year + 1
    shocks = _make_paths(mc, n_years, rng)

    if mc.inflation_stdev > 0:
        infl = rng.normal(p.assumptions.inflation, mc.inflation_stdev,
                          size=(mc.n_paths, n_years))
        infl = np.clip(infl, -0.02, 0.15)
    else:
        infl = None

    out = MCSummary(n_paths=mc.n_paths, years=n_years,
                    return_stdev=mc.return_stdev,
                    inflation_stdev=mc.inflation_stdev)
    leg_n, leg_c, tax_n, tax_c, sf_n, sf_c = [], [], [], [], [], []

    for i in range(mc.n_paths):
        path = shocks[i]
        ipath = infl[i] if infl is not None else None

        a = run_projection(p, convert=False, return_path=path, inflation_path=ipath)
        b = run_projection(p, convert=True, return_path=path, inflation_path=ipath)

        leg_n.append(a.heir_value_total)
        leg_c.append(b.heir_value_total)
        tax_n.append(a.lifetime_total_tax)
        tax_c.append(b.lifetime_total_tax)
        sf_n.append(a.total_shortfall)
        sf_c.append(b.total_shortfall)

        if progress is not None and (i % max(1, mc.n_paths // 50) == 0):
            progress((i + 1) / mc.n_paths)

    out.legacy_no_convert = np.array(leg_n)
    out.legacy_convert = np.array(leg_c)
    out.tax_no_convert = np.array(tax_n)
    out.tax_convert = np.array(tax_c)
    out.legacy_delta = out.legacy_convert - out.legacy_no_convert
    out.tax_delta = out.tax_convert - out.tax_no_convert
    out.shortfall_no_convert = np.array(sf_n)
    out.shortfall_convert = np.array(sf_c)

    if progress is not None:
        progress(1.0)
    return out
