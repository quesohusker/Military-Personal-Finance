#!/usr/bin/env python3
"""
Install the authoritative SSA period life table.

The app ships an approximation, because the machine it was built on could not
reach ssa.gov. This installs the real thing, which then takes precedence.

    1. Open https://www.ssa.gov/oact/STATS/table4c6.html
    2. Save the page (or copy the table into a text file)
    3. python scripts/import_life_table.py --file <that file>

The table has two blocks, male then female. Each row is:

    exact age | death probability | number of lives | LIFE EXPECTANCY

and it is the fourth column of each block that this reads.

REFUSAL TO INSTALL. A table whose columns are off by one parses perfectly and
produces plausible, wrong answers for every user, so the parsed result is put
through engine.mortality.check() before anything is written: remaining years
must fall as age rises, expected age at death must rise as age rises, and
female life expectancy must exceed male at every shared age. If any of those
fails, nothing is installed and the reason is printed.
"""
import argparse
import json
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from engine import mortality as M  # noqa: E402

ROW = re.compile(
    r"^\s*(\d{1,3})\s+"          # exact age
    r"([\d.]+)\s+"               # death probability
    r"([\d,]+)\s+"               # number of lives
    r"([\d.]+)\s+"               # life expectancy   <- male
    r"([\d.]+)\s+"               # death probability
    r"([\d,]+)\s+"               # number of lives
    r"([\d.]+)\s*$"              # life expectancy   <- female
)


def parse(text: str) -> tuple[dict, dict]:
    """
    SSA publishes male and female side by side on one row.

    Rows that do not match the full seven-column shape are skipped rather than
    guessed at — a partial match is exactly how a column shift gets in.
    """
    male, female = {}, {}
    for line in text.splitlines():
        line = re.sub(r"<[^>]+>", " ", line)          # strip any HTML
        line = line.replace(" ", " ")
        m = ROW.match(line)
        if not m:
            continue
        age = int(m.group(1))
        male[age] = float(m.group(4))
        female[age] = float(m.group(7))
    return male, female


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True,
                    help="the saved SSA table (HTML or plain text)")
    ap.add_argument("--source", default="SSA period life table",
                    help="what to show as the source in the app")
    args = ap.parse_args()

    text = pathlib.Path(args.file).read_text(encoding="utf-8", errors="replace")
    male, female = parse(text)
    print(f"parsed {len(male)} male rows, {len(female)} female rows")
    if not male or not female:
        print("Nothing parsed. Check that the file contains the rate table, "
              "with all seven columns per row.")
        return 1

    try:
        M.check(male, female)
    except M.LifeTableError as e:
        print(f"REFUSED, nothing written: {e}")
        return 1

    M.DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    M.DATA_PATH.write_text(json.dumps(
        {"source": args.source, "male": male, "female": female}, indent=2),
        encoding="utf-8")

    t = M.load()
    print(f"installed {M.DATA_PATH}")
    print(f"authoritative: {t.authoritative}  source: {t.source}")
    for age in (30, 45, 60, 65, 75):
        print(f"  age {age}: expected age at death "
              f"{M.life_expectancy(age, M.SEX_MALE, t)} male / "
              f"{M.life_expectancy(age, M.SEX_FEMALE, t)} female")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
