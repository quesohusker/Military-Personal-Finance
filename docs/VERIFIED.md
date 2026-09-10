# Figures checked against the agency that publishes them

Every rate in this app was first written from recollection, because the
machine it was built on cannot reach any `.gov` or `.mil` host. This records
what has since been checked against the source, what was wrong, and what is
still unverified. `scripts/fetch_gov_data.py` produced the archive; the hash
column identifies the exact file each figure was read from.

Fetched 2026-09-10. Nothing below was taken from memory.

| Figure | Source | Result | Detail |
|---|---|---|---|
| EITC, all 2026 amounts | `irs_rev_proc_2025_32` | **CORRECTED** | 11 of 12 figures matched exactly. The childless MFJ threshold phaseout is $18,140; it was carried as $18,130. Earned income amounts 8,680 / 13,020 / 18,290 / 18,290 and maximum credits 664 / 4,427 / 7,316 / 8,231 confirmed. |
| EITC investment income limit | `irs_rev_proc_2025_32` | **CONFIRMED** | $12,200. |
| Child Tax Credit | `irs_rev_proc_2025_32` | **CONFIRMED** | $2,200 maximum, $1,700 refundable. |
| Standard deduction | `irs_rev_proc_2025_32` | **CONFIRMED** | $32,200 joint, $24,150 head of household, $16,100 single. |
| Estate basic exclusion | `irs_rev_proc_2025_32` | **CONFIRMED** | $15,000,000, set by OBBBA s70106 -- so the TCJA sunset the published advice still assumes did NOT happen. GST exemption the same. |
| Gift annual exclusion | `irs_rev_proc_2025_32` | **CONFIRMED** | $19,000 per recipient per donor. Non-citizen spouse $194,000, which had been the least confident figure on the estate page. |
| Medicare Part B premium | `cms_part_b_2026` | **CONFIRMED** | $202.90 a month standard, $283 annual deductible. |
| VA funding fee, every tier | `va_funding_fee` | **CONFIRMED** | First use 2.15 / 1.5 / 1.25%; after first use 3.3 / 1.5 / 1.25% -- the agent's reading that the two are identical at 5% or more down was right. IRRRL 0.5%, cash-out 2.15 / 3.3%, assumption 0.5%. |
| SGLI premium rate | `va_sgli_rates` | **CONFIRMED** | 5 cents per $1,000 of coverage, so $25 a month at the $500,000 maximum. |
| VGLI windows and cap | `va_vgli_rates` | **CONFIRMED** | 240 days with no health review; '1 year and 120 days' = the 485-day outer deadline; $10,000 to $500,000 of coverage. |
| TSP expense ratios | `tsp_expense_ratios` | **CORRECTED** | G 0.034, F 0.035, C 0.035, S 0.051, I 0.048 percent. Every one was carried HIGHER than published -- G by nearly half. |
| TSP I Fund index | `tsp_expense_ratios` | **CORRECTED** | MSCI ACWI IMI ex USA ex China ex Hong Kong. The exclusion of China and Hong Kong was missing from the description. |
| SSA period life table | browser save | **INSTALLED** | 120 ages, both sexes, through the importer's shape checks. `is_authoritative()` now returns True. The approximation it replaces ran two years SHORT at every age under 60. |
| Part B IRMAA tiers | browser save, ssa.gov | **CORRECTED** | Published as the standard premium plus 81.20 / 202.90 / 324.60 / 446.30 / 487.00. Three tiers were a dime high when derived from the statutory cost shares: 405.80 not 405.90, 649.20 not 649.30, 689.90 not 690.00. |
| Part D IRMAA tiers | browser save, ssa.gov | **CONFIRMED / CORRECTED** | 0 / 14.50 / 37.50 / 60.40 / 83.30 / 91.00. `healthcare.py` had these exactly right. `engine/tax/tables.py` was carrying the 2025 amounts (13.70 through 85.80) and is now fixed. |
| IRMAA MAGI brackets | browser save, ssa.gov | **CONFIRMED** | 109 / 137 / 171 / 205 / 500k single, double that joint except the top at 750k. |
| IRMAA, married filing separately | browser save, ssa.gov | **RECORDED** | Its own two-step schedule, and its top surcharge is 487.90 rather than the 487.00 every other status pays. Not modelled; recorded so it is not re-derived wrongly. |
| SSA PIA bend points | browser save, ssa.gov | **CONFIRMED** | $1,286 and $7,749 for 2026, exact. These had been inferred from wage-index growth off the 2025 figures and were the numbers the Social Security page said it would not defend. |
| BAS rates | browser save, dfas.mil | **CONFIRMED** | Enlisted $476.95, officer $328.48, BAS II $953.90. Settles the direction for good: enlisted BAS is the LARGER of the two. The original brief for this project had them the other way round. |
| TRICARE reserve premiums | browser save, tricare.mil | **CORRECTED** | TRS $57.88 member / $286.66 family; TRR $645.90 / $1,548.30. All four were carried high, TRS family by $14 a month. |
| TRICARE enrolment fees | browser save, tricare.mil | **CORRECTED** | Prime Group A $381.96 / $765, Group B $462.96 / $927; Select Group A $186.96 / $375, Group B $594.96 / $1,191. Select Group B had been carried at $199 / $398 -- a third of the real figure. |
| TRICARE catastrophic caps | browser save, tricare.mil | **CONFIRMED** | $1,000 and $1,324 for active-duty families, $3,000 and $4,635 for retirees -- including the two rated LOW. Select Group A has its own cap of $4,381, which was missing entirely. |
| TSP L Fund lineup | `tsp_lifecycle_funds` | **CONFIRMED** | L Income and L 2030 through L 2075 in five-year steps. L 2075 was rated LOW confidence on the grounds it might not exist yet. It does. |

## Source files

| Key | SHA-256 (first 16) | URL |
|---|---|---|
| `irs_rev_proc_2025_32` | `e9ada115fb43a4af` | https://www.irs.gov/pub/irs-drop/rp-25-32.pdf |
| `irs_rev_proc_2025_32` | `e9ada115fb43a4af` | https://www.irs.gov/pub/irs-drop/rp-25-32.pdf |
| `irs_rev_proc_2025_32` | `e9ada115fb43a4af` | https://www.irs.gov/pub/irs-drop/rp-25-32.pdf |
| `irs_rev_proc_2025_32` | `e9ada115fb43a4af` | https://www.irs.gov/pub/irs-drop/rp-25-32.pdf |
| `irs_rev_proc_2025_32` | `e9ada115fb43a4af` | https://www.irs.gov/pub/irs-drop/rp-25-32.pdf |
| `irs_rev_proc_2025_32` | `e9ada115fb43a4af` | https://www.irs.gov/pub/irs-drop/rp-25-32.pdf |
| `cms_part_b_2026` | `e8652f7da7519f86` | https://www.medicare.gov/basics/costs/medicare-costs |
| `va_funding_fee` | `3b79a45628252416` | https://www.va.gov/housing-assistance/home-loans/funding-fee-and-closing-costs/ |
| `va_sgli_rates` | `8d205ade9c2049ac` | https://www.va.gov/life-insurance/options-eligibility/sgli/ |
| `va_vgli_rates` | `219548c7b8e827c5` | https://www.va.gov/life-insurance/options-eligibility/vgli/ |
| `tsp_expense_ratios` | `e945e37e16c94717` | https://www.tsp.gov/funds-individual/ |
| `tsp_expense_ratios` | `e945e37e16c94717` | https://www.tsp.gov/funds-individual/ |
| `tsp_lifecycle_funds` | `cd7094d25ee2780c` | https://www.tsp.gov/funds-lifecycle/ |

## Still unverified

Everything that changes a number has now been checked. What remains is the
annual refresh rather than an open question:

- **DFAS pay tables** and the **DTMO BAH archive**, both already installed
  for 2026 from files downloaded by hand in an earlier session. Next year's
  editions will need the same treatment -- neither host will serve an
  automated request.
- **VA disability compensation rates**, fetched but not yet read into the
  app; the user is asked for their own figure instead.

`python3 scripts/fetch_gov_data.py --manual` still prints the browser-save
list, and the saving method matters: **Page Source** for SSA and DFAS, whose
tables are in the markup, and **Print to PDF** for TRICARE, whose page builds
itself in JavaScript and whose Save As returns an empty shell.

## What one year of life expectancy was worth

The installed table puts the retired O-5 sample's death at 87 rather than the
86 the approximation gave. That single year moved the case for Roth
conversion by half: the legacy gain went from $28,954 to $43,482, because a
longer life means more RMD years, and more RMD years is exactly what leaving
the balance alone costs you. Two tests that pin those figures failed when the
table was installed, which is what they are for.
