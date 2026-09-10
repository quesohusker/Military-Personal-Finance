# Military Personal Finance

A financial planning application built for the way military pay and benefits
actually work — for active duty first, and for retirees and veterans on the
same machinery.

**Status: under construction.** The pay engine, the Roth conversion engine and
the debt payoff engine are in. The UI is not yet.

## First run

```bash
git clone https://github.com/quesohusker/military-personal-finance.git
cd military-personal-finance
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/refresh_bah.py     # see "Rate data" below
```

## Rate data

The app ships with everything except BAH. BAH is ~40,000 ZIP codes × 27 pay
grades × 2 dependency states, published by the Defense Travel Management
Office as one small archive. Download it with:

```bash
python scripts/refresh_bah.py            # current year
python scripts/refresh_bah.py --year 2026
python scripts/refresh_bah.py --check    # what is installed
```

Then commit `data/pay/bah_YYYY.json` so the app ships with rates.

Rates change **1 January**, so this is an annual job.

### Why the script refuses to install some downloads

The DTMO rate files have no header row — the pay grade of each column is
positional. A table that is misaligned by one column parses perfectly and
produces entirely plausible, entirely wrong numbers for every user. So the
parser validates the column count, and the installer runs shape checks: senior
grades must out-earn junior ones, with-dependents must beat without, and the
ZIP and MHA counts must be in the expected range. If any fail it refuses to
install rather than guess. `--force` exists but you should inspect the archive
first.

| Data | Source | Refresh |
|---|---|---|
| BAH | DTMO ASCII archive | `scripts/refresh_bah.py`, annually (1 Jan) |
| BAS | Two scalars, in `engine/pay/bas.py` | Edit annually (1 Jan) |
| Basic pay | Table in `engine/pay/` | Annual raise, verify against DFAS |
| VA disability | Rates by rating and dependents | Annually (1 Dec) |

BAS is indexed to the USDA food cost index, **not** the military pay raise —
in 2026 those were 2.4% and 3.8%. Do not derive one from the other.

## Layout

```
engine/
  pay/          grades, basic pay, BAH, BAS, allowances
  tax/          federal, state, the taxable/non-taxable split
  retirement/   retirement systems, TSP, projection, Roth conversions
  debt/         snowball / avalanche payoff, SCRA interest cap
  networth/     balance sheet
  coach/        the financial priority waterfall as a rule engine
data/pay/       versioned rate tables
scripts/        data refresh utilities
pages/          Streamlit UI
tests/
```

## Tests

```bash
python -m pytest tests/ -q
```

## Scope

This is an estimator and a planning tool. It is not tax, legal or investment
advice, and it is not a substitute for your LES, your Retiree Account
Statement, or a conversation with a financial counsellor — Military OneSource
provides those free.
