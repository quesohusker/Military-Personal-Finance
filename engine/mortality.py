"""
Actuarial life expectancy, so the app stops guessing on the user's behalf.

Five pages asked "how long do you expect to live?" and offered 85, 90, 90 and
82 as the answer. Those were not estimates of anything -- they were four
different round numbers, and the choice between them moves the value of a
pension, of SBP, and of a disability retirement by six figures.

WHAT THIS RETURNS. Given your age now, the SSA period life table gives the
average number of further years lived by people of that age. Expected age at
death is therefore `age + e(age)`, and it RISES as you get older: having
reached 70 you are expected to see 85, while a 30-year-old is expected to see
about 79. That is not a paradox, it is survivorship -- the deaths that would
have pulled the average down have already happened to other people.

A MEDIAN IS NOT A PLAN. Living to your life expectancy is roughly a coin
flip; about half of people outlive it. For anything that INSURES longevity --
SBP above all -- planning to the average understates the benefit, because the
whole value of that insurance sits in the half of the distribution where you
or your survivor lives a long time. `planning_age()` exists for that.

PROVENANCE. The published SSA period life table is installed at
data/mortality/life_table.json and is what load() returns; is_authoritative()
says so, and the pages report it. The built-in table below is the fallback for
a checkout without that file. It was written from recollection and, now that
there is something to check it against, it ran two years SHORT of the real
figure at every age under 60 and converged above 75 -- close enough to beat a
round number, wrong enough to matter over a 30-year projection. Reinstall with

    python scripts/import_life_table.py --file <downloaded SSA table>

from https://www.ssa.gov/oact/STATS/table4c6.html, and it takes precedence.
`is_authoritative()` tells you which one is in use, and the pages say so.
"""

from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "mortality" / "life_table.json"

SEX_MALE = "Male"
SEX_FEMALE = "Female"
SEX_UNSPECIFIED = ""
SEXES = [SEX_UNSPECIFIED, SEX_MALE, SEX_FEMALE]

BUILTIN_SOURCE = ("SSA period life table (built-in approximation -- runs "
                  "about two years short under age 60)")

# Remaining years of life at exact age. Anchors every five years from 20;
# values between anchors are interpolated linearly, which is accurate to well
# under a year across this range.
_BUILTIN_MALE = {
    0: 73.5, 20: 54.9, 25: 50.4, 30: 45.9, 35: 41.4, 40: 36.9, 45: 32.6,
    50: 28.4, 55: 24.4, 60: 20.6, 65: 17.0, 70: 13.7, 75: 10.7, 80: 8.0,
    85: 5.8, 90: 4.1, 95: 2.9, 100: 2.1, 105: 1.5, 110: 1.1,
}
_BUILTIN_FEMALE = {
    0: 79.3, 20: 60.3, 25: 55.5, 30: 50.8, 35: 46.0, 40: 41.3, 45: 36.7,
    50: 32.3, 55: 28.0, 60: 23.9, 65: 19.8, 70: 15.9, 75: 12.3, 80: 9.2,
    85: 6.7, 90: 4.7, 95: 3.3, 100: 2.3, 105: 1.6, 110: 1.2,
}

# Years to add to the median when planning for longevity rather than
# describing it. Roughly the gap from the median to the ~80th percentile of
# remaining lifetime at retirement ages.
LONGEVITY_MARGIN_YEARS = 5


@dataclass
class LifeTable:
    male: dict
    female: dict
    source: str
    authoritative: bool = False

    def remaining(self, age: int, sex: str = SEX_UNSPECIFIED) -> float:
        if sex == SEX_MALE:
            return _interpolate(self.male, age)
        if sex == SEX_FEMALE:
            return _interpolate(self.female, age)
        # Unspecified: the midpoint of the two, which is close to the
        # population average and avoids asking a question nobody wants asked.
        return (_interpolate(self.male, age) + _interpolate(self.female, age)) / 2.0


def _interpolate(table: dict, age: int) -> float:
    ages = sorted(table)
    a = max(ages[0], min(int(age), ages[-1]))
    if a in table:
        return table[a]
    lo = max(x for x in ages if x < a)
    hi = min(x for x in ages if x > a)
    span = hi - lo
    return table[lo] + (table[hi] - table[lo]) * (a - lo) / span


class LifeTableError(ValueError):
    """A table that fails these checks is refused rather than installed."""


def check(male: dict, female: dict) -> None:
    """
    Shape checks, so a mis-parsed column cannot install silently.

    A table shifted by one row parses perfectly and produces plausible,
    wrong answers for every user of the app.
    """
    for name, t in (("male", male), ("female", female)):
        if len(t) < 5:
            raise LifeTableError(f"{name} table has only {len(t)} rows")
        ages = sorted(t)
        vals = [t[a] for a in ages]
        if vals != sorted(vals, reverse=True):
            raise LifeTableError(
                f"{name}: remaining years must fall as age rises")
        if not 60 <= t[ages[0]] <= 95:
            raise LifeTableError(
                f"{name}: life expectancy at the youngest age is "
                f"{t[ages[0]]:.1f}, which is not credible")
        # Expected age at death must RISE with age, or the table is inverted.
        deaths = [a + t[a] for a in ages]
        if deaths != sorted(deaths):
            raise LifeTableError(
                f"{name}: expected age at death falls as age rises")
    for a in sorted(set(male) & set(female)):
        if female[a] < male[a]:
            raise LifeTableError(
                f"female life expectancy at {a} is below male, which is "
                f"backwards for every published table")


def load() -> LifeTable:
    """The installed table if there is one, otherwise the built-in estimate."""
    if DATA_PATH.exists():
        try:
            raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
            male = {int(k): float(v) for k, v in raw["male"].items()}
            female = {int(k): float(v) for k, v in raw["female"].items()}
            check(male, female)
            return LifeTable(male, female,
                             raw.get("source", "installed life table"), True)
        except (OSError, ValueError, KeyError, TypeError):
            pass  # fall through to the built-in rather than crashing a page
    return LifeTable(dict(_BUILTIN_MALE), dict(_BUILTIN_FEMALE),
                     BUILTIN_SOURCE, False)


def is_authoritative() -> bool:
    return load().authoritative


def life_expectancy(age: int, sex: str = SEX_UNSPECIFIED,
                    table: LifeTable | None = None) -> int:
    """Expected age at death for someone alive at `age`, rounded to a year."""
    t = table or load()
    return int(round(age + t.remaining(age, sex)))


def planning_age(age: int, sex: str = SEX_UNSPECIFIED,
                 table: LifeTable | None = None,
                 margin: int = LONGEVITY_MARGIN_YEARS) -> int:
    """
    The age to PLAN to, which is not the age you are expected to reach.

    Half of people outlive their life expectancy. Running out of money is not
    symmetric with dying with money left over, so anything that has to last a
    lifetime is planned past the median, not to it.
    """
    return life_expectancy(age, sex, table) + margin


def explain(age: int, sex: str = SEX_UNSPECIFIED) -> str:
    """One sentence for a caption, naming the source and its standing."""
    t = load()
    exp = life_expectancy(age, sex, t)
    who = {SEX_MALE: "a man", SEX_FEMALE: "a woman"}.get(sex, "someone")
    return (f"{t.source}: {who} aged {age} is expected to reach about {exp}. "
            f"Roughly half of people outlive that, so plan past it rather than "
            f"to it."
            + ("" if t.authoritative else
               "  This is a built-in approximation, not the published SSA "
               "file — see scripts/import_life_table.py to install the real "
               "one."))
