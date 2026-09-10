# Page reorganization — decisions and rationale

Written 2026-09-10. Records the reasoning behind the menu rewrite so a
later session does not have to re-derive it.

**Ask:** "Reorganize the pages to make more sense. I like Boldin as a web
app. Rename the pages to something more simple. *What I actually get paid*
should be *Income*." Then, mid-change: "Organize things under these basic
groups: Currently Serving, Veteran, Retiree, General."

---

## Two separate changes

The ask has two halves and they are worth keeping apart, because one is
uncontroversial and the other involved a judgement call.

1. **Renaming** — titles become nouns. This is the Boldin half and it is
   an unambiguous improvement.
2. **Regrouping** — pages are filed by **who they are for**. This was
   specified directly and overrode an earlier subject-based draft.

## Renaming: nouns, not sentences

The old titles were sentences. "What I actually get paid", "Do I stay to
twenty?", "What will this year's tax return look like?" A sidebar of full
questions is slow to scan; the eye has to read each one rather than land
on a noun. Boldin's entries are all nouns — Income, Savings, Housing,
Debt, Insurance, Taxes, Estate — and that is the part worth copying.

**The title says the subject; the subtitle says the question.** Nothing is
lost: "Pension" carries the subtitle "What your pension is worth, what
reaching twenty is worth, and the one election that can undo a career of
saving." The question survives, one line down, where it does not cost a
scan.

This does *not* change the house rule that **widget labels are
second-person questions**. That rule is about inputs, where a noun label
("Life expectancy") invites a user to treat a guess as a given. Page
titles are navigation, not input, and the reasoning does not carry across.

## Regrouping: by audience

The old menu grouped by **event** — `Where I stand`, `Decisions I make
now`, `When I get orders`, `When I deploy`, `When I leave the service`.
The new menu groups by **status**: `General`, `Currently Serving`,
`Veteran`, `Retiree`.

### The objection, recorded because it is real

**Status groups overlap, and one of them swallows everything.** A military
retiree is also a veteran. Someone currently serving will be both. So for
any page that is not narrowly tied to one status, the filing decision is
arbitrary — and most pages are not narrowly tied to one status. Taxes,
Roth conversions, investments, debt and estate planning are the same
problems in or out of uniform.

The consequence is visible in the result: **`General` holds 13 of the 23
pages.** A grouping where the catch-all is more than half the app is doing
less work than the group names suggest.

The counter-argument, which is why it was implemented as asked: the
grouping still answers the question a user actually arrives with — *which
of these pages are for someone like me right now?* — and the old event
groups answered a question nobody asked. A large `General` is not a
failure if the pages in it genuinely are general. They are.

### The filing rule used

Where a page could sit in two groups, it was filed by **who makes the
decision the page models**, not by who benefits from the outcome.

- `Pension` (was "Do I stay to twenty?") → **Currently Serving**. A
  retiree reads it to value what they already have, but the decision it
  exists to inform — stay or go — can only be made in uniform.
- `Healthcare` → **Retiree**. It covers TRICARE while serving, but the
  page's substance is the 65 cliff, Medicare Part B, and IRMAA colliding
  with Roth conversions. That is a retiree's problem.
- `Housing & VA Loan` → **Veteran**. Serving members use the VA loan too,
  but entitlement, restoration and the second-loan case are what the page
  actually models, and those bite after the first move.
- `Residency & GI Bill` → **Veteran**. The GI Bill transfer decision is
  made in uniform; using the benefit is a veteran act, and the state-of-
  residence half follows you out.

---

## The new menu

| Group | Title | File | Was |
|---|---|---|---|
| **General** | Overview | `0_Overview.py` | Overview |
| | Profile | `1_Profile.py` | Who I am |
| | Income | `2_Pay.py` | What I actually get paid |
| | Accounts | `4_Assets_and_Debts.py` | What I am worth |
| | Investments | `21_Investments.py` | How is my money invested? |
| | Taxes | `22_This_Years_Taxes.py` | What will this year's tax return look like? |
| | Next Dollar | `6_Prime_Directive.py` | What to do with my next dollar |
| | Roth Conversions | `14_Roth_Conversions.py` | Should I convert to Roth? |
| | Debt Payoff | `5_Debt_Payoff.py` | Getting out of debt |
| | Estate | `20_Estate_and_Gifting.py` | Who gets what, and when |
| | Assumptions | `17_Assumptions.py` | What should we assume? |
| | Import Pay Statement | `12_Upload_LES.py` | Read my LES or RAS |
| | Import Accounts | `13_Upload_Statement.py` | Read a bank or brokerage statement |
| **Currently Serving** | Career | `3_Career.py` | Promotions and PCS moves |
| | Deployment | `7_TSP_and_Deployment.py` | Combat-zone pay and the TSP |
| | Pension | `8_Retirement.py` | Do I stay to twenty? |
| | Transition | `18_Leaving_the_Service.py` | Leaving the service |
| **Veteran** | Medical Separation | `11_Separation_and_Insurance.py` | If I am medically separated |
| | Residency & GI Bill | `10_Residency_and_Education.py` | My home state, and the GI Bill |
| | Housing & VA Loan | `19_Home_and_VA_Loan.py` | Buy, rent, or keep the house? |
| **Retiree** | Social Security | `15_Social_Security.py` | When do I claim Social Security? |
| | Healthcare | `16_Healthcare.py` | What will healthcare cost me? |
| | Survivor Benefits | `9_Survivor_and_VA.py` | Survivors, SBP and the VA |

Filenames are unchanged. Renaming them buys nothing — Streamlit takes the
title from `st.Page`, not the path — and it would break every test that
loads a page by path.

`General` is ordered as a new user walks it: who you are, what comes in,
what you hold, what the government takes, then the decisions that run on
top of all four, then the rates underneath them, then the importers.
`Assumptions` sits near the end because it is set once and revisited
rarely. The status groups run roughly chronologically.

## Naming rules applied

1. **Noun, not question.** The title says the subject; the subtitle says
   the question.
2. **One or two words wherever it does not cost meaning.** `Income`,
   `Accounts`, `Taxes`, `Estate`, `Career`, `Deployment`, `Pension`.
3. **Two-barrelled only where the short form hides a subject.**
   `Residency & GI Bill` and `Housing & VA Loan` each really are two
   subjects, and dropping the second half buries a benefit worth five
   figures. `Medical Separation` keeps its adjective because `Separation`
   alone would collide with `Transition`.
4. **`Accounts` covers assets *and* debts.** Boldin splits them; this app
   enters both in one editor on one page, so one title. `Debt Payoff`
   reads from it.
5. **`Import <what it gives you>`, not `<what you upload>`.** "Import Pay
   Statement" and "Import Accounts" say what arrives in the plan. The old
   titles named the document, which only helps if you already know that a
   RAS is where retired pay lives.

### Titles deliberately not shortened further

- `Roth Conversions` — not `Roth`. The page is the conversion decision,
  not the account type; `Roth` would read as a balance page.
- `Social Security` — not `SS`. Never abbreviate a benefit name.
- `Survivor Benefits` — not `SBP`. The page covers SBP *and* the CRDP vs
  CRSC election, and SBP alone undersells it.
- `Next Dollar` — the one question-title worth keeping the flavour of.
  `Priorities` was the alternative and is more generic than the page
  deserves.

---

## The mechanical problem this creates

Page titles are not confined to the router. They appear as **prose
cross-references** in about forty places — "Enter your TSP and IRA
balances on the **What I am worth** page", "the sizes on the Should I
convert to Roth? page". Every one has to move with the rename, or the app
starts directing users to pages that are not in the sidebar.

Reference sites this change sweeps:

- `engine/assumptions.py` — the `PAGE_*` constants (`PAGE_WORTH`,
  `PAGE_TWENTY`, `PAGE_SURVIVOR`, `PAGE_MEDICAL`, `PAGE_CAREER`,
  `PAGE_TSP`, `PAGE_HOME_STATE`, `PAGE_THIS`), consumed by the "which
  pages this moves" table.
- `engine/ingest/les.py` — every extracted field carries a `where=` string
  naming the page to correct it on.
- `engine/tax/current_year.py`, `engine/career/transition.py`,
  `engine/estate/planning.py`, `engine/investments/tsp_allocation.py`,
  `engine/pay/taxable.py`, `engine/retirement/roth_bridge.py` — finding
  detail text.
- Eleven `pages/*.py` files with in-page prose pointers.
- `tests/` — ten assertions on `at.title[0].value`.
- `README.md` menu table, `HANDOFF.md` menu section.

**A missed cross-reference is silent.** Nothing crashes; the user is just
sent to a page name that is not in the sidebar. That is why the sweep runs
from a grep over the exact old strings rather than by reading each file
and trusting the eye.

### Two strings that must NOT be swept

`engine/housing/va_loan.py` contains "keep the house at …" and "money
invested at …" as ordinary prose. They are not page references and a
blind search-and-replace corrupts them. Any future rename needs the same
care: match the full old title, not a fragment.

## Verification standard

Per HANDOFF, unit tests do not catch page bugs. After the rename —

1. `pytest` stays green, with title assertions **updated, not deleted**.
2. `grep -r` for each old title returns zero hits outside
   `docs/REORGANIZATION.md` and git history.
3. Every page drives clean in headless Chromium against both sample
   plans — fail on a traceback and on any `.katex` node, which means
   prose was parsed as LaTeX and a dollar figure vanished.

## Considered and rejected

- **Subject-based groups (`My Plan` / `Explore` / `Military` / `Import`),
  mirroring Boldin's own split between facts and what-ifs.** Drafted
  first, then replaced by the four status groups on instruction. Recorded
  because it is the structure Boldin actually uses, and because it does
  not have the overlap problem described above — if the status grouping
  ever chafes, this is the alternative.
- **Merging `Taxes` and `Roth Conversions`.** Different questions on
  different horizons: this year's return versus a multi-decade ladder.
  The Roth page is also the largest in the app.
- **Splitting `Accounts` into `Savings` and `Debt` to match Boldin
  exactly.** The data lives in one editor. Splitting a page to match a
  competitor's nav copies the label instead of the idea.
- **Renaming the page files to match the new titles.** No user-visible
  benefit, breaks test loads, and loses `git log --follow` on 23 files.
