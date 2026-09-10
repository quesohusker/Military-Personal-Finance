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


def _pick(names: list[str], *fragments: str, exclude: tuple = ()) -> str | None:
    """
    Find the archive member whose name contains all fragments.

    The DTMO archive ships superseded copies alongside the current ones -- both
    "bahw26.txt" and "bahw26 - old.txt", and .dat duplicates of each. The old
    files hold DIFFERENT rates, so picking one silently installs last
    revision's numbers. Exclude them, and prefer .txt over .dat.
    """
    candidates = [
        n for n in names
        if all(f in n.lower() for f in fragments)
        and not any(x in n.lower() for x in exclude)
        and "old" not in n.lower()
        and not n.lower().endswith(".pdf")
    ]
    if not candidates:
        return None
    # Prefer .txt, then the shortest name (the canonical one has no suffix).
    candidates.sort(key=lambda n: (not n.lower().endswith(".txt"), len(n)))
    return candidates[0]


# DoD web servers reject requests that do not look like a browser. A bare
# library User-Agent gets a 403, not a 404 -- the file is there, the request is
# refused. Send a full browser header set.
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 "
                   "Safari/537.36"),
    "Accept": "application/zip,application/octet-stream,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": ("https://www.travel.dod.mil/Allowances/"
                "Basic-Allowance-for-Housing/BAH-Rate-Lookup/"),
}


def fetch(year: int, url: str = "") -> bytes:
    import urllib.error
    import urllib.request

    target = url or bah.BAH_SOURCE_URL.format(year=year)
    print(f"  Downloading {target}")
    req = urllib.request.Request(target, headers=BROWSER_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(_http_help(e.code, target, year)) from e


def _http_help(code: int, url: str, year: int) -> str:
    """Turn an HTTP status into something actionable."""
    if code == 403:
        return (
            f"\nHTTP 403 Forbidden for:\n  {url}\n\n"
            f"The file exists but the server refused the request. This is a bot\n"
            f"filter, not a missing file. Download it in a browser and hand the\n"
            f"script the local copy -- that always works:\n\n"
            f"  1. Open this in your browser:\n     {url}\n"
            f"  2. Then run:\n"
            f"     python scripts/refresh_bah.py --file ~/Downloads/BAH-ASCII-{year}.zip\n\n"
            f"If the browser download also fails, the whole BAH page is here:\n"
            f"  https://www.travel.dod.mil/Allowances/Basic-Allowance-for-Housing/\n"
            f"Find the ASCII archive, download it, and pass it with --file."
        )
    if code == 404:
        return (
            f"\nHTTP 404 for:\n  {url}\n\n"
            f"That year is not published at this path. Try:\n"
            f"  python scripts/refresh_bah.py --year {year - 1}\n\n"
            f"Or pass the archive URL directly if DTMO moved it:\n"
            f"  python scripts/refresh_bah.py --url <url>"
        )
    return (f"\nHTTP {code} for:\n  {url}\n\n"
            f"Download it in a browser and use --file, or pass --url.")


def build(year: int, blob: bytes) -> bah.BAHData:
    zf = zipfile.ZipFile(io.BytesIO(blob))
    names = [n for n in zf.namelist() if not n.endswith("/")]
    print(f"  Archive contains: {', '.join(names)}")

    def read(member: str) -> str:
        return zf.read(member).decode("utf-8", errors="replace")

    zip_member = _pick(names, "zipmha")
    # "bahw" is a prefix of "bahwo", so the with-dependents file must exclude it.
    with_member = _pick(names, "bahw", exclude=("bahwo",))
    without_member = _pick(names, "bahwo")
    names_member = _pick(names, "mhanames") or _pick(names, "mha", "name")

    print(f"  Using: {with_member}, {without_member}, {zip_member}, {names_member}")

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
    ap.add_argument("--file", type=str, default="",
                    help="Use an archive already downloaded to disk instead of "
                         "fetching it. Use this if the download is blocked.")
    ap.add_argument("--url", type=str, default="",
                    help="Download from this URL instead of the built-in one.")
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

    if args.file:
        path = Path(args.file).expanduser()
        if not path.exists():
            print(f"No such file: {path}", file=sys.stderr)
            return 1
        blob = path.read_bytes()
        print(f"  Read {len(blob):,} bytes from {path}")
    else:
        try:
            blob = fetch(args.year, args.url)
        except SystemExit:
            raise
        except Exception as e:  # noqa: BLE001 - any network failure, reported plainly
            print(f"\nDownload failed: {e}\n\n"
                  f"Download the archive in a browser and pass it directly:\n"
                  f"  python scripts/refresh_bah.py --file ~/Downloads/BAH-ASCII-{args.year}.zip",
                  file=sys.stderr)
            return 1
        print(f"  Downloaded {len(blob):,} bytes")

    if not blob[:2] == b"PK":
        print("\nThat file is not a zip archive. If you downloaded it in a "
              "browser, check you saved the ASCII .zip and not an HTML error "
              "page.", file=sys.stderr)
        return 1
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
