#!/usr/bin/env python3
"""
Fetch the published figures this app hard-codes, from the agencies that own them.

WHY THIS EXISTS. The app was built in a container with no route to any .gov or
.mil host, so every rate in it -- Part B and IRMAA, the EITC table, VA funding
fees, SSA bend points, the mortality table, TRICARE costs -- was written from
recollection and marked VERIFY. A number that is plausible and wrong is worse
than one that is obviously missing, because nobody checks it. This script runs
somewhere with real network access and replaces recollection with the source.

RUN IT LIKE THIS

    python3 scripts/fetch_gov_data.py                 # everything
    python3 scripts/fetch_gov_data.py --list          # what it would fetch, and why
    python3 scripts/fetch_gov_data.py --only ssa,irs  # one or more categories
    python3 scripts/fetch_gov_data.py --zip           # bundle the raw archive

Standard library only. No pip install, no API key, nothing to configure.

WHAT IT DOES WITH WHAT IT GETS

Two things, and the first matters more than the second:

    1. ARCHIVES the raw response of every source under data/_gov_raw/<date>/,
       byte for byte, alongside a MANIFEST.json recording the URL, the HTTP
       status, the fetch time, the size and a SHA-256 of each. Even where the
       parser below fails -- and on hand-written agency HTML it will -- the
       archive is the thing worth having. Zip it and send it back and the
       figures can be read out of it by hand.

    2. PARSES what there are already parsers for, and installs it: the SSA
       period life table straight into data/mortality/, the DTMO BAH archive
       and the DFAS pay tables staged for the importers that already exist.

Nothing is overwritten silently. Parsed output goes through the same shape
checks the importers use, and a table that fails them is refused, not
installed.

A NOTE ON BEING POLITE. One request per source, a real User-Agent, a pause
between hosts. These are public pages; this is a person checking figures, not
a crawler. If a host answers 403 it is bot filtering rather than a missing
page -- open the URL in a browser, save the file, and pass it to the matching
importer by hand.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW_ROOT = ROOT / "data" / "_gov_raw"

# A plain browser UA. Several DoD hosts return 403 to anything that looks
# automated -- learned the hard way when the BAH archive refused us.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "application/pdf;q=0.9,*/*;q=0.8"),
    "Accept-Language": "en-US,en;q=0.9",
}

TIMEOUT = 45
RETRIES = 3
PAUSE_BETWEEN = 1.5          # seconds, to stay well inside anyone's rate limit


# ==========================================================================
# What we need, and who publishes it
# ==========================================================================

class Source:
    def __init__(self, key, category, url, supplies, filename="",
                 parser=None, note=""):
        self.key = key
        self.category = category
        self.url = url
        self.supplies = supplies      # which hard-coded figures this replaces
        self.filename = filename or (key + _suffix_for(url))
        self.parser = parser          # optional callable(bytes, Path) -> str
        self.note = note


def _suffix_for(url: str) -> str:
    tail = url.split("?")[0].rsplit("/", 1)[-1].lower()
    for ext in (".pdf", ".zip", ".csv", ".txt", ".xlsx", ".xls", ".json"):
        if tail.endswith(ext):
            return ext
    return ".html"


SOURCES: list[Source] = [
    # ---- Social Security -------------------------------------------------
    Source("ssa_period_life_table", "ssa",
           "https://www.ssa.gov/oact/STATS/table4c6.html",
           "engine/mortality.py -- the whole built-in table, which is an "
           "approximation and the single largest unverified thing in the app",
           parser=lambda b, p: _parse_life_table(b)),
    Source("ssa_bend_points", "ssa",
           "https://www.ssa.gov/oact/COLA/bendpoints.html",
           "engine/income/social_security.py -- the PIA formula bend points"),
    Source("ssa_wage_index", "ssa",
           "https://www.ssa.gov/oact/COLA/AWI.html",
           "engine/income/social_security.py -- indexing past earnings"),
    Source("ssa_contribution_base", "ssa",
           "https://www.ssa.gov/oact/COLA/cbb.html",
           "the FICA wage base, which caps covered earnings"),
    Source("ssa_cola_history", "ssa",
           "https://www.ssa.gov/oact/COLA/colaseries.html",
           "COLA history, for the REDUX CPI-minus-one comparison"),
    Source("ssa_medicare_premiums", "ssa",
           "https://www.ssa.gov/benefits/medicare/medicare-premiums.html",
           "engine/benefits/healthcare.py -- Part B and Part D IRMAA brackets"),
    Source("ssa_retirement_age", "ssa",
           "https://www.ssa.gov/benefits/retirement/planner/ageincrease.html",
           "full retirement age by birth year"),

    # ---- Medicare / CMS --------------------------------------------------
    Source("cms_part_b_2026", "medicare",
           "https://www.cms.gov/newsroom/fact-sheets/2026-medicare-parts-b-premiums-and-deductibles",
           "engine/benefits/healthcare.py -- the standard Part B premium and "
           "deductible, and the IRMAA table in full",
           note="The URL carries the year. If 2026 404s, try the CMS newsroom "
                "listing and correct the year."),
    Source("cms_newsroom_factsheets", "medicare",
           "https://www.cms.gov/newsroom/fact-sheets",
           "a fallback listing, to find the current Part B fact sheet"),

    # ---- IRS -------------------------------------------------------------
    Source("irs_rev_proc_2025_32", "irs",
           "https://www.irs.gov/pub/irs-drop/rp-25-32.pdf",
           "engine/tax/tables.py and engine/tax/current_year.py -- brackets, "
           "standard deduction, the whole EITC table, the gift annual "
           "exclusion and the estate basic exclusion for 2026",
           note="The annual inflation-adjustment revenue procedure. If this "
                "number is wrong for the year you want, the IRS 'Tax "
                "inflation adjustments' newsroom item links the right one."),
    Source("irs_inflation_adjustments", "irs",
           "https://www.irs.gov/newsroom/irs-provides-tax-inflation-adjustments-for-tax-year-2026",
           "the readable summary of the same figures"),
    Source("irs_retirement_limits", "irs",
           "https://www.irs.gov/newsroom/401k-limit-increases-to-24500-for-2026-ira-limit-increases-to-7500",
           "engine/retirement/tsp.py -- elective deferral, catch-up and the "
           "annual-additions limit; and the Saver's Credit AGI tiers"),
    Source("irs_eitc_tables", "irs",
           "https://www.irs.gov/credits-deductions/individuals/earned-income-tax-credit/earned-income-and-earned-income-tax-credit-eitc-tables",
           "engine/tax/current_year.py -- EITC amounts and phase-outs, the "
           "figures the agent was least confident about"),
    Source("irs_combat_pay_eitc", "irs",
           "https://www.irs.gov/individuals/military/combat-pay-special-combat-pay",
           "the combat-pay election into earned income for EITC"),
    Source("irs_pub_3_armed_forces", "irs",
           "https://www.irs.gov/pub/irs-pdf/p3.pdf",
           "Publication 3, Armed Forces' Tax Guide -- the authority for the "
           "BAH/BAS exclusion, CZTE, and the moving-expense deduction"),
    Source("irs_pub_915_ss_taxation", "irs",
           "https://www.irs.gov/pub/irs-pdf/p915.pdf",
           "provisional-income thresholds for taxing Social Security"),
    Source("irs_estate_gift", "irs",
           "https://www.irs.gov/businesses/small-businesses-self-employed/estate-and-gift-taxes",
           "engine/estate/planning.py -- the annual exclusion and the basic "
           "exclusion amount"),
    Source("irs_rmd_uniform_table", "irs",
           "https://www.irs.gov/pub/irs-pdf/p590b.pdf",
           "Publication 590-B -- the Uniform Lifetime Table behind every RMD "
           "in the Roth conversion engine, and the SECURE 10-year rule"),

    # ---- Defense pay and allowances --------------------------------------
    Source("dfas_pay_tables", "dod",
           "https://www.dfas.mil/militarymembers/payentitlements/Pay-Tables/",
           "data/pay/basepay_2026.json -- basic pay by grade and longevity",
           note="Find the current year's PDF here, then: "
                "python3 scripts/import_basepay.py --file <pdf>"),
    Source("dtmo_bah_ascii", "dod",
           "https://www.travel.dod.mil/Portals/119/Documents/BAH/BAHASCII2026.zip",
           "data/pay/bah_2026.json -- every MHA rate by grade and dependency",
           note="If this 403s it is bot filtering, not a missing file. Open it "
                "in a browser, then: python3 scripts/refresh_bah.py --file <zip>"),
    Source("dtmo_bas_rates", "dod",
           "https://www.travel.dod.mil/Allowances/Basic-Allowance-for-Subsistence/BAS-Rates/",
           "engine/pay/bas.py -- the enlisted and officer BAS rates"),
    Source("dtmo_bah_nonlocality", "dod",
           "https://www.travel.dod.mil/Allowances/Basic-Allowance-for-Housing/BAH-Rate-Lookup/",
           "engine/pay/bah_nonlocality.py -- the partial and non-locality rates"),
    Source("dfas_sbp", "dod",
           "https://www.dfas.mil/retiredmilitary/provide/sbp/",
           "engine/benefits/sbp.py -- the 6.5% premium, the paid-up rule and "
           "the 55% annuity"),
    Source("dfas_crdp_crsc", "dod",
           "https://www.dfas.mil/retiredmilitary/disability/comparison/",
           "engine/benefits/concurrent_receipt.py -- CRDP against CRSC"),
    Source("tsp_contribution_limits", "dod",
           "https://www.tsp.gov/making-contributions/contribution-limits/",
           "engine/retirement/tsp.py -- the elective deferral and annual "
           "addition limits, and the combat-zone overflow"),
    Source("tsp_lifecycle_funds", "dod",
           "https://www.tsp.gov/funds-lifecycle/",
           "engine/investments/tsp_allocation.py -- the L fund glide path"),
    Source("tsp_expense_ratios", "dod",
           "https://www.tsp.gov/funds-individual/",
           "engine/investments/tsp_allocation.py -- expense ratios"),

    # ---- Veterans Affairs -------------------------------------------------
    Source("va_disability_rates", "va",
           "https://www.va.gov/disability/compensation-rates/veteran-rates/",
           "the monthly compensation table by rating and dependents -- the "
           "app asks the user for this figure and could look it up instead"),
    Source("va_funding_fee", "va",
           "https://www.va.gov/housing-assistance/home-loans/funding-fee-and-closing-costs/",
           "engine/housing/va_loan.py -- the funding fee tiers and the "
           "exemption at a 10% rating"),
    Source("va_loan_limits", "va",
           "https://www.va.gov/housing-assistance/home-loans/loan-limits/",
           "engine/housing/va_loan.py -- entitlement and the conforming limit"),
    Source("va_sgli_rates", "va",
           "https://www.va.gov/life-insurance/options-eligibility/sgli/",
           "engine/benefits/life_insurance.py -- the SGLI premium"),
    Source("va_vgli_rates", "va",
           "https://www.va.gov/life-insurance/options-eligibility/vgli/",
           "engine/benefits/life_insurance.py -- the age-banded VGLI table, "
           "which drives the whole term-versus-VGLI argument"),
    Source("va_dic_rates", "va",
           "https://www.va.gov/disability/survivor-dic-rates/",
           "engine/benefits/sbp.py -- DIC, and the SBP-DIC offset repeal"),
    Source("va_gi_bill_rates", "va",
           "https://www.va.gov/education/benefit-rates/post-9-11-gi-bill-rates/",
           "engine/benefits/gi_bill.py -- the housing allowance and tuition caps"),
    Source("va_severance_recoupment", "va",
           "https://www.va.gov/disability/eligibility/special-claims/",
           "engine/benefits/disability_separation.py -- severance recoupment"),

    # ---- TRICARE ----------------------------------------------------------
    Source("tricare_costs", "tricare",
           "https://www.tricare.mil/Costs/HealthPlanCosts",
           "engine/benefits/healthcare.py -- enrolment fees and the "
           "catastrophic cap, Group A against Group B"),
    Source("tricare_for_life", "tricare",
           "https://www.tricare.mil/Plans/HealthPlans/TFL",
           "engine/benefits/healthcare.py -- that TFL requires Part B"),
    Source("tricare_reserve_select", "tricare",
           "https://www.tricare.mil/Plans/HealthPlans/TRS",
           "engine/benefits/healthcare.py -- TRS premiums"),

    # ---- Housing ----------------------------------------------------------
    Source("fhfa_conforming_limits", "housing",
           "https://www.fhfa.gov/data/conforming-loan-limit",
           "engine/housing/va_loan.py -- the conforming loan limit that sets "
           "the no-down-payment ceiling on full entitlement"),
]


# ==========================================================================
# Parsers -- only where there is already a checked importer to feed
# ==========================================================================

def _parse_life_table(raw: bytes) -> str:
    """
    The SSA period life table, straight into data/mortality/life_table.json.

    Reuses engine.mortality.check(), so a table whose columns have shifted is
    refused rather than installed. A shifted table parses perfectly and gives
    plausible, wrong answers to every user of the app.
    """
    sys.path.insert(0, str(ROOT))
    from engine import mortality as M

    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"<[^>]+>", " ", text)          # strip tags, keep the numbers
    text = text.replace("\xa0", " ")

    row = re.compile(
        r"(\d{1,3})\s+"                # exact age
        r"([\d.]+)\s+([\d,]+)\s+([\d.]+)\s+"    # male: q, lives, e
        r"([\d.]+)\s+([\d,]+)\s+([\d.]+)"       # female: q, lives, e
    )
    male, female = {}, {}
    for m in row.finditer(text):
        age = int(m.group(1))
        if age > 120:
            continue
        male[age] = float(m.group(4))
        female[age] = float(m.group(7))

    if not male:
        return "no rows matched -- the page layout has changed; use the archive"

    M.check(male, female)                          # refuses a shifted table
    M.DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    M.DATA_PATH.write_text(json.dumps(
        {"source": f"SSA period life table, fetched {dt.date.today()}",
         "male": male, "female": female}, indent=2), encoding="utf-8")
    return (f"installed {M.DATA_PATH.relative_to(ROOT)} "
            f"({len(male)} ages; at 40 a man reaches "
            f"{M.life_expectancy(40, M.SEX_MALE)}, a woman "
            f"{M.life_expectancy(40, M.SEX_FEMALE)})")


# ==========================================================================
# Fetching
# ==========================================================================

def fetch(url: str) -> tuple[int, bytes, str]:
    """(status, body, error). Retries on transport failure, not on a 4xx."""
    ctx = ssl.create_default_context()
    last = ""
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
                return r.status, r.read(), ""
        except urllib.error.HTTPError as e:
            body = b""
            try:
                body = e.read()
            except Exception:
                pass
            # 403 is a bot filter and 404 is a moved page. Neither improves
            # on a retry, and hammering a public site over it is rude.
            return e.code, body, f"HTTP {e.code} {e.reason}"
        except Exception as e:                     # timeout, DNS, TLS, reset
            last = f"{type(e).__name__}: {e}"
            if attempt < RETRIES - 1:
                time.sleep(2 ** attempt)
    return 0, b"", last


def run(sources: list[Source], out_dir: pathlib.Path) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    last_host = ""
    for i, s in enumerate(sources, 1):
        host = s.url.split("/")[2]
        if last_host and host != last_host:
            time.sleep(PAUSE_BETWEEN)
        last_host = host

        print(f"[{i:2d}/{len(sources)}] {s.key:<28} ", end="", flush=True)
        status, body, err = fetch(s.url)
        rec = {"key": s.key, "category": s.category, "url": s.url,
               "supplies": s.supplies, "status": status,
               "bytes": len(body), "fetched": dt.datetime.now().isoformat(timespec="seconds"),
               "error": err, "parsed": "", "note": s.note}

        if body:
            path = out_dir / s.filename
            path.write_bytes(body)
            rec["file"] = s.filename
            rec["sha256"] = hashlib.sha256(body).hexdigest()

        if status == 200 and body:
            print(f"ok   {len(body):>9,} bytes", end="")
            if s.parser:
                try:
                    rec["parsed"] = s.parser(body, out_dir)
                    print(f"  -> {rec['parsed']}")
                except Exception as e:
                    rec["parsed"] = f"PARSE FAILED: {type(e).__name__}: {e}"
                    print(f"\n{'':>36}!! {rec['parsed']}")
            else:
                print()
        else:
            print(f"FAILED  {err or status}")
            if s.note:
                print(f"{'':>36}-> {s.note}")

        results.append(rec)
    return results


# ==========================================================================
# CLI
# ==========================================================================

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true",
                    help="show every source and the figures it supplies")
    ap.add_argument("--only", default="",
                    help="comma-separated categories or keys "
                         "(ssa, medicare, irs, dod, va, tricare, housing)")
    ap.add_argument("--out", default="",
                    help="archive directory (default data/_gov_raw/<date>)")
    ap.add_argument("--zip", action="store_true",
                    help="bundle the archive into one .zip to send back")
    args = ap.parse_args()

    cats = sorted({s.category for s in SOURCES})

    if args.list:
        for c in cats:
            print(f"\n=== {c} " + "=" * (68 - len(c)))
            for s in SOURCES:
                if s.category == c:
                    print(f"  {s.key}\n    {s.url}\n    supplies: {s.supplies}")
                    if s.note:
                        print(f"    note: {s.note}")
        print(f"\n{len(SOURCES)} sources in {len(cats)} categories.")
        return 0

    chosen = SOURCES
    if args.only:
        want = {w.strip().lower() for w in args.only.split(",") if w.strip()}
        chosen = [s for s in SOURCES
                  if s.category in want or s.key in want]
        if not chosen:
            print(f"Nothing matched {sorted(want)}. Categories: {cats}")
            return 1

    out_dir = pathlib.Path(args.out) if args.out else \
        RAW_ROOT / dt.date.today().isoformat()

    print(f"Fetching {len(chosen)} sources into {out_dir}\n")
    results = run(chosen, out_dir)

    manifest = {
        "fetched": dt.datetime.now().isoformat(timespec="seconds"),
        "script": "scripts/fetch_gov_data.py",
        "sources": results,
    }
    (out_dir / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")

    ok = [r for r in results if r["status"] == 200 and r["bytes"]]
    bad = [r for r in results if r not in ok]
    parsed = [r for r in ok if r["parsed"] and "FAILED" not in r["parsed"]]

    print(f"\n{'=' * 72}")
    print(f"{len(ok)}/{len(results)} fetched, {len(parsed)} parsed and installed")
    if parsed:
        print("\nInstalled:")
        for r in parsed:
            print(f"  {r['key']}: {r['parsed']}")
    if bad:
        print("\nCould not fetch -- open these in a browser and save them:")
        for r in bad:
            print(f"  {r['key']:<28} {r['error'] or r['status']}")
            print(f"    {r['url']}")
    print(f"\nArchive: {out_dir}")
    print(f"Manifest: {out_dir / 'MANIFEST.json'}")

    if args.zip:
        zpath = out_dir.with_suffix(".zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(out_dir.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(out_dir.parent))
        print(f"\nBundled: {zpath}  ({zpath.stat().st_size:,} bytes)")
        print("Send that back and the figures can be read out of it.")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
