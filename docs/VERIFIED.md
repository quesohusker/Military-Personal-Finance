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

Three hosts refuse every automated request -- SSA, DFAS and DTMO all sit
behind a bot filter that neither a full browser header set nor curl's
different TLS handshake gets past. TRICARE returns a JavaScript shell. What
that leaves outstanding, in the order it changes an answer:

1. **The SSA period life table.** `engine/mortality.py` still runs on a
   built-in approximation, and every pension value, SBP ratio and conversion
   horizon in the app is measured against it. `scripts/import_life_table.py`
   will install a browser-saved copy through the same shape checks.
2. **The Part B IRMAA brackets.** The standard premium is confirmed; the six
   income tiers are not. They are what makes a Roth conversion cost more two
   years later, so the healthcare page's central argument rests on them.
   Note also that `engine/tax/tables.py` carries Part D IRMAA figures that
   re-derive from a 2025 base premium -- last year's amounts.
3. **The SSA PIA bend points.** Everything the Social Security page estimates
   for someone without a statement scales directly with these two numbers.
4. **TRICARE enrolment fees and the catastrophic cap.** The retiree lifetime
   figure is dominated by Part B, so these move the total by a few percent.
5. **BAS.** Small, but it is in every pay calculation, and the original brief
   for this project had the enlisted and officer rates backwards.

`python3 scripts/fetch_gov_data.py --manual` prints the short list with the
saving instructions each one needs.
