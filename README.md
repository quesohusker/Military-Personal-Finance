# Military Personal Finance

Financial planning built for the way military pay and benefits actually work —
active duty first, with retirees and veterans on the same machinery.

```bash
git clone https://github.com/quesohusker/Military-Personal-Finance.git
cd Military-Personal-Finance
./mpf.sh start
```

`mpf.sh` builds a virtual environment, installs dependencies, starts the app
and opens it. `./mpf.sh update` pulls and restarts; `./mpf.sh test` runs the
suite.

## Why a military-specific tool

The civilian financial order of operations is close to right, and wrong in five
places that each cost money:

1. **The TSP match only exists under BRS.** "Always get the match" does nothing
   for a High-3 member. Your DIEMS date decides which system applies.
2. **The match is on basic pay only** — not BAH, not BAS, not special pays.
3. **An HSA is unavailable on active duty.** TRICARE is not a high-deductible
   plan. Civilian lists rank it above maxing your retirement plan; the step
   does not exist for you.
4. **The Savings Deposit Program outranks everything while deployed.** 10%
   guaranteed on $10,000, risk-free. No civilian equivalent.
5. **SCRA comes before the debt step.** Capping pre-service debt at 6% can
   change which debt is actually expensive, so invoke it before you optimise.

And one reframing: **BAH is not income.** It has been set below full local
housing cost since 2015, with members absorbing about 5% out of pocket. The app
assumes housing and utilities cost **105% of BAH** unless you say otherwise.

## Pages

| Page | What it does |
|---|---|
| **Profile** | Component, grade, DIEMS date, location, deployment, VA |
| **Pay** | Basic pay, BAH by ZIP, BAS, drill pay, taxable/untaxed split |
| **Career** | Promotion timeline, PCS moves, projected pay year by year |
| **Assets & Debts** | Net worth, including replacement cost of guaranteed income |
| **Debt Payoff** | Avalanche vs snowball, priced with the SCRA 6% cap |
| **Prime Directive** | Your ordered next actions, scored |
| **TSP & Deployment** | Match, contribution limits, CZTE, the combat-zone overflow |
| **Retirement** | All four systems, the 20-year cliff, the BRS lump-sum trap |
| **Survivor & VA** | SBP priced honestly, CRDP vs CRSC after tax |
| **Residency & Education** | State of legal residence, GI Bill use vs transfer |

## Rate data

Ships with 2026 rates already installed — no download needed.

| Data | Source | Refresh |
|---|---|---|
| BAH | DTMO ASCII archive — 338 housing areas, 40,959 ZIPs | `scripts/refresh_bah.py`, annually (1 Jan) |
| Basic pay | DFAS published table | `scripts/import_basepay.py`, annually (1 Jan) |
| BAS | Two scalars in `engine/pay/bas.py` | Edit annually (1 Jan) |
| Drill pay | Derived: basic pay ÷ 30 per drill | Automatic |

Both importers refuse to install data that fails shape checks. The DTMO rate
files carry no header row, so each column's pay grade is positional — a table
misaligned by one column parses perfectly and produces plausible, wrong numbers
for every user. The checks verify senior grades out-earn junior ones,
with-dependents beats without, and the ZIP and area counts are in range.

BAS tracks the USDA food index, **not** the pay raise — 2.4% against 3.8% in
2026. Do not derive one from the other.

## Layout

```
engine/
  pay/          grades, basic pay, BAH (locality + non-locality), BAS, drill pay
  tax/          federal, state, the taxable/non-taxable split
  retirement/   projection, Roth conversions, Monte Carlo
  debt/         snowball / avalanche, SCRA interest cap
  networth/     balance sheet, guaranteed income valuation
  career/       promotion timeline, PCS moves, pay projection
  coach/        the financial priority waterfall as a rule engine
data/pay/       versioned rate tables
scripts/        data importers
pages/          Streamlit UI
```

## Tests

```bash
python -m pytest tests/ -q
```

365 tests. The data-driven ones skip cleanly when rate tables are absent, so a
fresh clone passes either way.

## Scope

An estimator and a planning tool. Not tax, legal or investment advice, and no
substitute for your LES, your Retiree Account Statement, or a conversation with
a financial counsellor. Military OneSource provides those free at 800-342-9647.
