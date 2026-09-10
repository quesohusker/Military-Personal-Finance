# Page reorganization — decisions and rationale

Written 2026-09-10. Records the reasoning behind the Boldin-style menu
rewrite so a later session does not have to re-derive it.

**Ask:** "Reorganize the pages to make more sense. I like Boldin as a web
app. Rename the pages to something more simple. *What I actually get paid*
should be *Income*."

---

## The organizing idea

The old menu was organized around **events a member meets** — `Where I
stand`, `Decisions I make now`, `When I get orders`, `When I deploy`,
`When I leave the service`. That was a defensible choice and the HANDOFF
defends it: nobody wakes up wanting to visit a "benefits module".

It has two costs, and both are why the app does not feel like Boldin:

1. **A page's group depends on your career phase, not on its subject.**
   Taxes sat under "Where I stand", healthcare under "When I leave the
   service", and Roth conversions under "Decisions I make now" — three
   pages a retiree uses in one sitting, in three different groups.
2. **Titles were sentences.** "What I actually get paid", "Do I stay to
   twenty?", "What will this year's tax return look like?" A sidebar of
   full questions is slow to scan; the eye has to read each one rather
   than land on a noun.

Boldin's structure is the opposite, and it is the part worth copying:

- **`My Plan`** holds the facts you enter — Profile, Income, Savings,
  Housing, Debt, Insurance, Taxes, Estate, Assumptions.
- **`Explorers`** holds the what-ifs that run on those facts — Roth
  Conversion, Social Security, Lifetime Planner, Tax Planner.
- Every entry is a **noun**, usually one or two words.

So: **facts in one group, what-ifs in another, nouns throughout.**

## What that does not cover

Boldin's buckets have no home for the military-specific events, which are
real and which this app exists for: a deployment, a PCS, a medical board,
the transition out. Forcing `Deployment` into `My Plan` would be worse
than the problem being solved.

The answer is a fifth group, `Military`, holding exactly the pages whose
subject is service itself. That keeps Boldin's shape for the 80% that maps
cleanly and stops pretending for the 20% that does not.

`Import` is its own group for the same reason — the two upload pages are a
mechanism, not a subject, and they read as clutter anywhere else.

---

## The new menu

| Group | Title | File | Was |
|---|---|---|---|
| **Home** | Home | `0_Overview.py` | Overview |
| **My Plan** | Profile | `1_Profile.py` | Who I am |
| | Income | `2_Pay.py` | What I actually get paid |
| | Accounts | `4_Assets_and_Debts.py` | What I am worth |
| | Investments | `21_Investments.py` | How is my money invested? |
| | Taxes | `22_This_Years_Taxes.py` | What will this year's tax return look like? |
| | Estate | `20_Estate_and_Gifting.py` | Who gets what, and when |
| | Assumptions | `17_Assumptions.py` | What should we assume? |
| **Explore** | Next Dollar | `6_Prime_Directive.py` | What to do with my next dollar |
| | Roth Conversions | `14_Roth_Conversions.py` | Should I convert to Roth? |
| | Social Security | `15_Social_Security.py` | When do I claim Social Security? |
| | Pension | `8_Retirement.py` | Do I stay to twenty? |
| | Healthcare | `16_Healthcare.py` | What will healthcare cost me? |
| | Debt Payoff | `5_Debt_Payoff.py` | Getting out of debt |
| | Housing | `19_Home_and_VA_Loan.py` | Buy, rent, or keep the house? |
| **Military** | Career | `3_Career.py` | Promotions and PCS moves |
| | Deployment | `7_TSP_and_Deployment.py` | Combat-zone pay and the TSP |
| | Residency & Education | `10_Residency_and_Education.py` | My home state, and the GI Bill |
| | Transition | `18_Leaving_the_Service.py` | Leaving the service |
| | Medical Separation | `11_Separation_and_Insurance.py` | If I am medically separated |
| | Survivor Benefits | `9_Survivor_and_VA.py` | Survivors, SBP and the VA |
| **Import** | Import LES | `12_Upload_LES.py` | Read my LES or RAS |
| | Import Statements | `13_Upload_Statement.py` | Read a bank or brokerage statement |

Filenames are unchanged. Renaming them buys nothing — Streamlit takes the
title from `st.Page`, not the path — and it would break every test that
imports a page by path.

## Why each group is ordered the way it is

- **My Plan** follows the data-entry flow a new user actually walks:
  who you are, what comes in, what you hold, how it is invested, what the
  government takes, where it goes when you die, and the rates underneath
  all of it. `Assumptions` sits last because it is the one page you set
  once and revisit rarely.
- **Explore** leads with `Next Dollar` because it is the page that answers
  "what should I do?" for someone with no specific question. Then the two
  large-dollar levers (`Roth Conversions`, `Social Security`), then the
  streams (`Pension`, `Healthcare`), then the two that are situational.
- **Military** runs roughly chronologically: career, deployment, where
  you claim residency, then the three exits.

## Naming rules applied

1. **Noun, not question.** The title says the subject; the subtitle says
   the question. `Pension`, subtitle "What your pension is worth, whether
   reaching twenty is worth staying for…".
2. **One or two words wherever it does not cost meaning.** `Income`,
   `Accounts`, `Taxes`, `Estate`, `Career`, `Deployment`.
3. **The exception is kept when the short form misleads.**
   `Residency & Education` stayed two-barrelled because the page really is
   two subjects (state of legal residence, GI Bill use vs transfer) and
   dropping either hides it. Same for `Medical Separation` — `Separation`
   alone would collide with `Transition`.
4. **`Accounts` covers assets *and* debts.** Boldin splits them; this app
   enters both in one table on one page, so one title. The `Debt Payoff`
   explorer reads from it.

## Titles deliberately NOT shortened further

- `Roth Conversions` — not `Roth`. The page is about the conversion
  decision, not the account type; `Roth` would read as a balance page.
- `Social Security` — not `SS`. Never abbreviate a benefit name.
- `Survivor Benefits` — not `SBP`. The page covers SBP *and* the CRDP/CRSC
  election; SBP alone would undersell it.
- `Next Dollar` — the old "What to do with my next dollar" was the one
  question-title worth keeping the flavour of. `Priorities` was the
  alternative and is more generic than the page deserves.

---

## The mechanical problem this creates

Page titles are not confined to the router. They appear as **prose
cross-references** in about forty places — "Enter your TSP and IRA
balances on the **What I am worth** page", "the sizes on the Should I
convert to Roth? page". Every one has to move with the rename or the app
starts telling users to visit pages that no longer exist.

Known reference sites, all of which this change sweeps:

- `engine/assumptions.py` — `PAGE_WORTH`, `PAGE_TWENTY`, `PAGE_SURVIVOR`,
  `PAGE_MEDICAL`, `PAGE_CAREER`, `PAGE_TSP`, `PAGE_HOME_STATE`,
  `PAGE_THIS` constants, consumed by the "which pages this moves" table.
- `engine/ingest/les.py` — every extracted field carries a `where=` string
  naming the page to correct it on.
- `engine/tax/current_year.py`, `engine/career/transition.py`,
  `engine/estate/planning.py`, `engine/investments/tsp_allocation.py`,
  `engine/pay/taxable.py`, `engine/retirement/roth_bridge.py` — finding
  detail text.
- Eleven `pages/*.py` files with in-page prose pointers.
- `tests/` — ten assertions on `at.title[0].value`.
- `README.md` menu table, `HANDOFF.md` menu section.

**A rename that misses a cross-reference is silent.** Nothing crashes; the
user is just sent to a page name that is not in the sidebar. That is why
the sweep is done by grep over the exact old strings rather than by
reading each file.

## Verification standard

Per HANDOFF: unit tests do not catch page bugs. After the rename —

1. `pytest` must stay at 940 passing (title assertions updated, not
   deleted).
2. `grep -r` for each old title string must return zero hits outside
   `docs/REORGANIZATION.md` and git history.
3. Drive every page in headless Chromium against both sample plans; fail
   on a traceback and on any `.katex` node.

## What was considered and rejected

- **Merging `Taxes` and `Roth Conversions`.** They answer different
  questions on different horizons — this year's return vs. a multi-decade
  conversion ladder — and the Roth page is the largest in the app.
- **Splitting `Accounts` into `Savings` and `Debt` to match Boldin
  exactly.** The data lives in one editor; splitting the page to match a
  competitor's nav would be copying the label instead of the idea.
- **Dropping the `Military` group and distributing its pages.** Tried on
  paper: `Deployment` has no honest home in `My Plan` or `Explore`, and
  scattering the three exit pages across groups is exactly the fault being
  fixed.
- **Renaming the page files to match the new titles.** No user-visible
  benefit, breaks test imports, and loses git history on 22 files.
