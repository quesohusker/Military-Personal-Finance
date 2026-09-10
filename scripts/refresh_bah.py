#!/usr/bin/env python3
"""
Download and install the current BAH rate tables from the Defense Travel
Management Office.

    python scripts/refresh_bah.py              # current year
    python scripts/refresh_bah.py --year 2026
    python scripts/refresh_bah.py --check      # report what is installed

DTMO publishes every MHA, every pay grade, and the ZIP-to-MHA crosswalk as one
small ASCII archive. Rates change effective 1 January, so this is an annual
job -- run it in January and the app is current for the year.

Nothing here is scraped. It is a plain file download of a public-domain US
Government work.
"""

from __future__ import annotations
import argparse
import datetime as dt
import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.pay import bah  # noqa: E402
from engine.pay import grades as G  # noqa: E402


def _pick(names: list[str], *fragments: str) -> str | None:
    """Find the archive member whose name contains all fragments."""
    for n in names:
        low = n.lower()
        if all(f in low for f in fragments):
            return n
    return None


def fetch(year: int) -> bytes:
    import urllib.request
    url = bah.BAH_SOURCE_URL.format(year=year)
    print(f"  Downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "military-personal-finance/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def build(year: int, blob: bytes) -> bah.BAHData:
    zf = zipfile.ZipFile(io.BytesIO(blob))
    names = [n for n in zf.namelist() if not n.endswith("/")]
    print(f"  Archive contains: {', '.join(names)}")

    def read(member: str) -> str:
        return zf.read(member).decode("utf-8", errors="replace")

    zip_member = _pick(names, "zipmha")
    with_member = _pick(names, "bahw") if not _pick(names, "bahwo") else None
    # bahw and bahwo both contain "bahw"; disambiguate explicitly.
    with_member = next((n for n in names
                        if "bahw" in n.lower() and "bahwo" not in n.lower()), None)
    without_member = next((n for n in names if "bahwo" in n.lower()), None)
    names_member = _pick(names, "mhanames") or _pick(names, "mha", "name")

    missing = [label for label, m in
               (("ZIP-to-MHA", zip_member), ("with-dependents rates", with_member),
                ("without-dependents rates", without_member))
               if m is None]
    if missing:
        raise SystemExit(
            f"Archive is missing: {', '.join(missing)}.\n"
            f"Members found: {names}\n"
            f"The DTMO archive layout may have changed. Inspect the zip before "
            f"editing the parser.")

    data = bah.BAHData(
        year=year,
        source=bah.BAH_SOURCE_URL.format(year=year),
        retrieved=dt.date.today().isoformat(),
        zip_to_mha=bah.parse_zip_mha(read(zip_member)),
        with_dependents=bah.parse_rates(read(with_member)),
        without_dependents=bah.parse_rates(read(without_member)),
        mha_names=bah.parse_mha_names(read(names_member)) if names_member else {},
    )
    return data


def sanity_check(data: bah.BAHData) -> list[str]:
    """
    Cheap checks that catch a misparse before it reaches a user. A rate table
    that parses cleanly but is shifted by one column looks entirely plausible,
    so verify the SHAPE of the numbers, not just that they are numbers.
    """
    problems = []

    if data.n_zips < 30_000:
        problems.append(f"Only {data.n_zips:,} ZIP codes; expected roughly 40,000.")
    if not (250 <= data.n_mhas <= 500):
        problems.append(f"{data.n_mhas} MHAs; expected roughly 300-350.")

    all_rates = [r for row in data.with_dependents.values() for r in row.values() if r > 0]
    if all_rates:
        lo, hi = min(all_rates), max(all_rates)
        if lo < 300 or hi > 10_000:
            problems.append(f"Rates span ${lo:,.0f}-${hi:,.0f}/mo, which is outside "
                            f"the plausible range. Suspect a column misalignment.")

    # Within an MHA, senior grades should out-earn junior ones. If E-1 beats
    # O-6 the columns are shifted.
    inversions = 0
    for mha, row in list(data.with_dependents.items())[:200]:
        e1, o6 = row.get("E01", 0), row.get("O06", 0)
        if e1 and o6 and e1 > o6:
            inversions += 1
    if inversions:
        problems.append(f"E-1 out-earns O-6 in {inversions} MHAs. The rate columns "
                        f"are almost certainly misaligned -- do not ship this.")

    # With-dependents should be at least as high as without.
    bad = 0
    for mha, row in list(data.with_dependents.items())[:200]:
        wo = data.without_dependents.get(mha, {})
        for code, rate in row.items():
            if wo.get(code, 0) > rate + 0.01:
                bad += 1
    if bad > 5:
        problems.append(f"Without-dependents exceeds with-dependents in {bad} cells. "
                        f"The two rate files may be swapped.")

    return problems


def report(data: bah.BAHData) -> None:
    print(f"\n  Year:      {data.year}")
    print(f"  ZIP codes: {data.n_zips:,}")
    print(f"  MHAs:      {data.n_mhas}")
    samples = [("78234", "E-5", True), ("22060", "O-3", False), ("96818", "E-7", True)]
    print("\n  Spot checks:")
    for z, grade, deps in samples:
        r = bah.lookup(z, grade, deps, data)
        if r.found:
            print(f"    {z}  {grade:5} {'with' if deps else 'without':7} deps  "
                  f"${r.monthly:,.0f}/mo   {r.mha_name}")
        else:
            print(f"    {z}  {grade:5} -> {r.note}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, default=dt.date.today().year)
    ap.add_argument("--check", action="store_true",
                    help="Report installed data without downloading.")
    ap.add_argument("--force", action="store_true",
                    help="Install even if the sanity checks fail. Do not use this "
                         "unless you have inspected the data yourself.")
    args = ap.parse_args()

    if args.check:
        years = bah.available_years()
        if not years:
            print("No BAH data installed. Run this script without --check.")
            return 1
        for y in years:
            d = bah.load(y)
            print(f"BAH {y}: {d.n_zips:,} ZIPs, {d.n_mhas} MHAs, "
                  f"retrieved {d.retrieved or 'unknown'}")
        return 0

    print(f"Refreshing BAH rates for {args.year}")
    try:
        blob = fetch(args.year)
    except Exception as e:  # noqa: BLE001 - report any network/HTTP failure plainly
        print(f"\nDownload failed: {e}", file=sys.stderr)
        print(f"\nIf {args.year} rates are not published yet, try --year {args.year - 1}.\n"
              f"If the URL 404s, DTMO may have moved the file. Check:\n"
              f"  https://www.travel.dod.mil/Allowances/Basic-Allowance-for-Housing/",
              file=sys.stderr)
        return 1

    print(f"  Downloaded {len(blob):,} bytes")
    data = build(args.year, blob)

    problems = sanity_check(data)
    if problems:
        print("\n  SANITY CHECKS FAILED:")
        for p in problems:
            print(f"    - {p}")
        if not args.force:
            print("\n  Refusing to install. A misaligned rate table is worse than no "
                  "table: every number looks plausible and every number is wrong.")
            return 2
        print("\n  --force given; installing anyway.")

    path = bah.save(data)
    report(data)
    print(f"\n  Installed to {path}")
    print("  Commit this file so the app ships with rates.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
