#!/usr/bin/env python3
"""
Import a DFAS basic pay table into data/pay/basepay_YYYY.json.

    python scripts/import_basepay.py --year 2026 --file 2026_AD_Pay.pdf
    python scripts/import_basepay.py --year 2026 --file pay.txt --text
    python scripts/import_basepay.py --check

DFAS publishes the table as a PDF (and an XLSX behind it). There is no
machine-readable feed, so this parses the published document once a year.

THE ALIGNMENT TRAP: rows are RIGHT-aligned, not left. A grade that cannot exist
at low longevity simply has no cell there -- W-5 starts at "Over 20", E-9 at
"Over 10", O-3E at "Over 4". W-5's row carries 11 values, not 22. Left-aligning
those would put a W-5's twenty-year rate in the "2 or less" column and
understate the pay of every senior member in the app.
"""

from __future__ import annotations
import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.pay import basepay as BP  # noqa: E402
from engine.pay import grades as G  # noqa: E402

MONEY = re.compile(r"\$\s*([\d,]+\.\d{2})")

# Row labels as they appear in the published table, mapped to our grade codes.
LABEL_TO_CODE = {g.label: g.code for g in G.GRADES}
LABEL_TO_CODE.update({
    "O-1E": "O01E", "O-2E": "O02E", "O-3E": "O03E",
    "O1E": "O01E", "O2E": "O02E", "O3E": "O03E",
})

ROW_START = re.compile(r"^\s*(O-\d{1,2}E?|O\dE|W-\d|E-\d)\s")


def extract_text(path: Path, is_text: bool) -> str:
    if is_text or path.suffix.lower() in (".txt", ".text"):
        return path.read_text(encoding="utf-8", errors="replace")
    try:
        import pdfplumber
    except ImportError:
        raise SystemExit(
            "Reading a PDF needs pdfplumber:\n    pip install pdfplumber\n"
            "Or copy the table text into a .txt file and pass --text.")
    with pdfplumber.open(str(path)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def parse(text: str) -> tuple[dict, float]:
    """
    Returns (rates, e1_under_4_months).

    rates maps grade code -> {yos column as str: monthly amount}.
    """
    columns = G.YOS_COLUMNS                      # 22 longevity columns
    rates: dict[str, dict[str, float]] = {}
    e1_short = 0.0

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        # "E1 <4mos $2,225.70" -- the reduced rate for a member's first months.
        if "<4" in line.replace(" ", "") and "E1" in line.replace("-", ""):
            found = MONEY.findall(line)
            if found:
                e1_short = float(found[0].replace(",", ""))
            continue

        m = ROW_START.match(line)
        if not m:
            continue
        label = m.group(1).replace("O1E", "O-1E").replace("O2E", "O-2E").replace("O3E", "O-3E")
        code = LABEL_TO_CODE.get(label)
        if not code:
            continue

        values = [float(v.replace(",", "")) for v in MONEY.findall(line)]
        if not values:
            continue
        if len(values) > len(columns):
            raise SystemExit(
                f"{label}: {len(values)} values but only {len(columns)} longevity "
                f"columns exist. The table layout has changed -- inspect it "
                f"before trusting any figure.")

        # RIGHT-align: the last value is always the "Over 40" column.
        offset = len(columns) - len(values)
        row = {}
        for i, v in enumerate(values):
            row[str(columns[offset + i])] = v
        rates[code] = row

    return rates, e1_short


def report(table: BP.BasePayTable, e1_short: float) -> None:
    print(f"\n  Year:   {table.year}")
    print(f"  Grades: {table.n_grades}")
    if e1_short:
        print(f"  E-1 with under 4 months of service: ${e1_short:,.2f}/mo")

    print("\n  Spot checks:")
    for grade, yos in (("E-1", 0), ("E-5", 6), ("E-7", 14), ("O-3", 4),
                       ("O-5", 22), ("W-5", 22), ("O-3E", 10)):
        r = BP.lookup(grade, yos, table)
        if r.found:
            flag = "  (top of scale)" if r.at_top_of_grade else ""
            print(f"    {grade:5} at {yos:>2} yrs -> ${r.monthly:>10,.2f}/mo"
                  f"   ${r.annual:>11,.0f}/yr{flag}")
        else:
            print(f"    {grade:5} at {yos:>2} yrs -> {r.note}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=str, default="")
    ap.add_argument("--year", type=int, default=dt.date.today().year)
    ap.add_argument("--text", action="store_true", help="Input is plain text.")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if args.check:
        years = BP.available_years()
        if not years:
            print("No basic pay table installed.")
            return 1
        for y in years:
            t = BP.load(y)
            print(f"Basic pay {y}: {t.n_grades} grades, "
                  f"retrieved {t.retrieved or 'unknown'}")
        return 0

    if not args.file:
        print("Give --file pointing at the DFAS pay table.", file=sys.stderr)
        return 1
    path = Path(args.file).expanduser()
    if not path.exists():
        print(f"No such file: {path}", file=sys.stderr)
        return 1

    print(f"Importing basic pay for {args.year} from {path.name}")
    rates, e1_short = parse(extract_text(path, args.text))
    if not rates:
        print("No pay rows recognised. If this is a PDF whose text does not "
              "extract, copy the table into a .txt file and pass --text.",
              file=sys.stderr)
        return 1

    table = BP.BasePayTable(year=args.year, rates=rates,
                            source=f"DFAS pay table ({path.name})",
                            retrieved=dt.date.today().isoformat())
    if e1_short:
        table.rates.setdefault("E01_UNDER_4_MONTHS", {"0": e1_short})

    missing = {g.code for g in G.GRADES} - set(table.rates)
    if missing:
        print(f"\n  Missing grades: {', '.join(sorted(missing))}")

    problems = BP.sanity_check(table)
    if problems:
        print("\n  SANITY CHECKS FAILED:")
        for p in problems:
            print(f"    - {p}")
        if not args.force:
            print("\n  Refusing to install.")
            return 2
        print("\n  --force given; installing anyway.")

    out = BP.save(table)
    report(table, e1_short)
    print(f"\n  Installed to {out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
