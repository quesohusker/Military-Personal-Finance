#!/usr/bin/env python3
"""
Install the authoritative SSA period life table.

The app ships an approximation, because the machine it was built on could not
reach ssa.gov. This installs the real thing, which then takes precedence.

    1. Open https://www.ssa.gov/oact/STATS/table4c6.html
    2. File > Save As > Page Source. ssa.gov refuses every automated
       request, so a browser is the only way to get the page at all.
    3. python scripts/import_life_table.py --file <that file>

Reads the saved HTML table directly -- one <tr> per age, seven <td> cells --
and falls back to a whitespace layout if the page is pasted as plain text.

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

# Plain-text layout: seven whitespace-separated columns on one line.
ROW_TEXT = re.compile(
    r"^\s*(\d{1,3})\s+"          # exact age
    r"([\d.]+)\s+"               # male death probability
    r"([\d,]+)\s+"               # male number of lives
    r"([\d.]+)\s+"               # male LIFE EXPECTANCY
    r"([\d.]+)\s+"               # female death probability
    r"([\d,]+)\s+"               # female number of lives
    r"([\d.]+)\s*$"              # female LIFE EXPECTANCY
)

# HTML layout: one <tr> per age, seven <td> cells in the same order. This is
# what a browser Save As produces, and it is the only way to get the page at
# all -- ssa.gov refuses every automated request.
ROW_HTML = re.compile(r"(?is)<tr[^>]*>(.*?)</tr>")
CELL = re.compile(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>")


def _num(cell: str) -> str:
    """Cell text with tags, entities and thousands separators removed."""
    cell = re.sub(r"(?is)<[^>]+>", " ", cell)
    cell = cell.replace("&nbsp;", " ").replace("\xa0", " ")
    return cell.replace(",", "").strip()


def parse(text: str) -> tuple[dict, dict]:
    """
    Read the table, from HTML or from plain text.

    Rows that do not match the full seven-column shape are skipped rather
    than guessed at -- a partial match is exactly how a column shift gets in,
    and a shifted table produces plausible, wrong answers for every user.
    """
    male, female = {}, {}

    for row in ROW_HTML.findall(text):
        cells = [_num(c) for c in CELL.findall(row)]
        if len(cells) != 7:
            continue
        try:
            age = int(cells[0])
            m_exp, f_exp = float(cells[3]), float(cells[6])
            float(cells[1]); float(cells[4])       # the probabilities must
            float(cells[2]); float(cells[5])       # parse, or it is a header
        except ValueError:
            continue
        if 0 <= age <= 125:
            male[age], female[age] = m_exp, f_exp

    if male:
        return male, female

    for line in text.splitlines():
        line = re.sub(r"<[^>]+>", " ", line).replace("\xa0", " ")
        m = ROW_TEXT.match(re.sub(r"[ \t]+", " ", line))
        if not m:
            continue
        age = int(m.group(1))
        if 0 <= age <= 125:
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
