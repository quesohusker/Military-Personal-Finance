# The scorecard architecture

A design, not a description. Nothing here is built yet.

**Purpose, stated once:** this app assesses **readiness to retire**. It is
a scorecard, not a toolbox. Everything in it either feeds the score or
explains it.

---

## 1. The diagnosis

The app is 23 pages, ~42 engine modules and ~29,000 lines of verified,
well-tested work. The engines are good. The problem is above them.

**There is no answer.** The app is a set of calculators, and reorganising
calculators does not make them a product. The menu was regrouped twice —
by career event, then by audience — and `General` ended up holding 13 of
23 pages, which is the symptom rather than the disease. A navigation
scheme cannot impose a spine on software that has none.

What makes Boldin feel coherent is not its navigation. It is that Boldin
computes **one projection**, reports **one headline**, and every page
either feeds that projection or explains it. The navigation reads clearly
because the *model* is singular.

`HANDOFF.md` has said this the whole time, filed under "What is not
built": *"A lifetime year-by-year cash-flow projection. The spine that
would tie all of the above together … This is the biggest remaining
gap."*

That is the fix. The funnels are how it gets asked; the scorecard is how
it gets answered.

## 2. The correction to the three-funnel plan

Three funnels is right at the **intake** and **scorecard** layers. It is
wrong at the **engine** layer.

`Veteran` and `Retired Military` differ in exactly two things: whether a
military pension and SBP stream exists, and whether healthcare is
TRICARE-shaped or VA-shaped. Everything else is identical — the
projection, Roth sequencing, Social Security, estate, debt, investments,
taxes. Building three parallel engines triples the maintenance for one
boolean and one income stream.

```
3 funnels of questions
3 scorecard framings
2 engine modes      (future-still-a-decision / future-largely-locked)
1 projection spine
```

### The axis that actually separates them

Not demographics — **how much of the future is still a decision.** This
is a better justification for three funnels than "who you are", and it
maps onto what the engines already do.

| Funnel | The future is | So the scorecard must |
|---|---|---|
| **Currently Serving** | unwritten — stay to 20 or not, BRS lump sum, deployments, separation point, GI Bill transfer | compare **courses of action**. Readiness is not one number; it is one per branch. |
| **Veteran** | civilian accumulation. No pension. VA disability may be the only indexed income. | score a **civilian problem with military assets** — the case the app currently says least about. |
| **Retired Military** | largely locked | score **sequencing** — when to claim, how much to convert, which account to draw first. |

### What the funnel must not do

**It must not hide pages permanently.** A serving member deciding whether
to stay to 20 needs the retiree pages to make that decision. The funnel
sets *defaults*, *ordering*, and *what gets scored*. It is not a
permissions system. Every page stays reachable.

## 3. The scorecard

### The device: C-ratings

The military already has a readiness vocabulary, and every member and
retiree reads it instantly. Unit readiness is rated C-1 to C-5. Use it.

| | |
|---|---|
| **C-1** | Fully ready |
| **C-2** | Ready, minor shortfalls |
| **C-3** | Ready, significant shortfalls |
| **C-4** | Not ready — requires resources |
| **C-5** | Not ready — undergoing reset |

C-5 is also the honest home for *"you have not entered this yet"* and
*"this does not apply to you"*, which a 0–100 score cannot express
without lying about it.

### The eight components

Each rated C-1..C-5, each rolling up, each drilling into a page that
already exists.

| # | Component | What it measures | Existing engine |
|---|---|---|---|
| 1 | **Income floor** | guaranteed inflation-linked income vs *essential* spending | `retirement/systems`, `benefits`, `income/social_security` |
| 2 | **Funded ratio** | PV of resources vs PV of needs | `retirement/projection` |
| 3 | **Longevity** | share of Monte Carlo paths with no shortfall | `retirement/montecarlo` |
| 4 | **Tax position** | conversion window used or wasted; RMD exposure | `retirement/roth_analysis`, `tax/*` |
| 5 | **Healthcare** | continuity to 65 and past it; IRMAA exposure | `benefits/healthcare` |
| 6 | **Survivor** | does the spouse still make it if you die first | `estate/planning`, SBP, DIC |
| 7 | **Liquidity & debt** | reserve months; high-rate debt | `debt/payoff`, `coach/prime_directive` |
| 8 | **Legacy** | only scored when the user says it is a goal | `estate/planning` |

### Why the floor is component 1

For a military retiree the floor is the whole story, and civilian tools
miss it. Pension, VA compensation, Social Security and a spouse's SSDI
are all inflation-linked, and the VA slice is untaxed. A retiree whose
floor covers essential spending is structurally safe in a way a civilian
with identical net worth is not: the portfolio is funding *wants*, not
survival.

The app cannot currently say that about anyone, including its owner.

### Why this is a score and not a checklist

A checklist scores behaviour — *are you contributing enough?* A readiness
score answers a question — *can you stop working?* The app should answer
the question. The behavioural advice already exists in `Next Dollar` and
belongs underneath, as the **remedy** for a low rating rather than as the
top-level frame.

## 4. The spine — much closer than it looks

The single most important finding from reading the code:

**`engine/retirement/projection.py::run_projection()` is already the
spine.** It walks year by year and already computes, on
`ProjectionResult`:

```
total_shortfall            years_with_shortfall
lifetime_total_tax         lifetime_irmaa_surcharge
lifetime_rmds              peak_marginal_rate
ending_traditional/roth/taxable/cash
heir_value_total           heir_tax_paid
```

Those are, almost exactly, components 2, 4, 6 and 8.

**`engine/retirement/montecarlo.py` already computes per-path shortfall**
(`shortfall_no_convert`, `shortfall_convert`). A success rate — component
3 — is `(shortfall == 0).mean()`. One line. It is not reported today
because `MCSummary.win_rate()` answers a different question: whether
*converting* beats *not converting*.

So the machinery is built and pointed at the wrong target. The spine
exists; it is **retiree-shaped and Roth-headlined**.

### What actually has to change

1. **Extend the spine backwards over the serving years.** Today wages are
   one figure grown at a real rate until `work_through_year`. It needs
   military pay that steps at longevity boundaries and jumps at
   promotion — which `engine/career/timeline.py` already models — plus
   the separation event, terminal leave, the pension starting, and
   TRICARE changing. This is the real work.
2. **Add an essential-vs-discretionary split to spending.** The floor
   component is meaningless without it, and it is one field plus a
   question.
3. **Report readiness, not Roth advantage.** A thin `engine/scorecard/`
   that reads a `ProjectionResult` and an `MCSummary` and returns eight
   ratings plus a roll-up. It computes almost nothing new.

## 5. Intake

One funnel replaces scattered profile entry. It asks only what the chosen
funnel needs, in an order that means something, and it can be re-entered.

**Question 1 sets the funnel.** *Where are you in your service?* →
Currently Serving · Veteran · Retired Military.

| Asked of | Fields |
|---|---|
| **Everyone** | birth year, sex (mortality table only), spouse and their birth year, dependents, state of residence, balances (TSP / IRA / brokerage / cash), debts, **essential** and **total** spending, target retirement age, life-expectancy assumption, legacy goal (yes/no + amount) |
| **Serving only** | **DIEMS date** (decides the retirement system, and nothing else does), grade, years of service, date of rank, duty ZIP, dependents-for-pay, government housing, TSP contribution % and Roth share, deployment and combat-zone months, SGLI, planned separation point, promotion expectations, GI Bill use or transfer |
| **Veteran only** | separation date, years served (drives the SS earnings history), VA rating and whether P&T, GI Bill remaining, VGLI vs term, civilian employer plan |
| **Retired only** | retired pay gross, retirement system, SBP elected and level, VA rating, CRDP/CRSC, TRICARE plan |

The two importers (`Import Pay Statement`, `Import Accounts`) become the
**fast path into intake** rather than separate destinations: upload an
LES or RAS and the funnel arrives pre-filled, with every figure showing
the raw line it came from. That is what they were built for.

## 6. What the 23 pages become

**Nothing is deleted.** Each page becomes the drill-down for a scorecard
component — the place you go when a rating is low and you want to know
what to do about it.

```
Scorecard  (home; eight ratings and the roll-up)
   └── a component reads C-3
         └── the page that explains it, and the lever that moves it

My Plan    (the facts, re-entrant intake)
Explore    (what-ifs that do not change the plan: Roth, SS timing,
            stay-to-20, buy vs rent)
```

The audience grouping shipped in PR #1 becomes unnecessary once the
scorecard is the front door — pages are reached by *what they fix*, not
by *who you are*. **PR #1 is still worth merging**: the noun titles are
right regardless, and the regroup is strictly better than what it
replaced. This supersedes the grouping, not the renaming.

## 7. Build order

Each step is shippable on its own. Nothing here is a rewrite.

| | Step | Why it is first |
|---|---|---|
| 1 | **Essential vs discretionary spending** + the funnel question | One field. Unblocks the floor, which is the component with the most to say. |
| 2 | **`engine/scorecard/`** over the existing retiree projection | Six of eight components work immediately for retirees and veterans. Proves the frame before the expensive part. |
| 3 | **Scorecard page**, C-ratings, drill-down links | The app has a front door and an answer. |
| 4 | **Extend the spine over the serving years** | The expensive step, and the one HANDOFF has been asking for. Unlocks the Serving funnel properly. |
| 5 | **Intake funnel** replacing scattered profile entry | Worth doing after 1–4, because only then is it clear which questions actually earn their place. |
| 6 | **Courses of action for the Serving funnel** | Stay to 20 vs leave at 12, scored side by side. The app's original central case. |

Steps 2 and 3 are the cheap ones that change how the app feels. Step 4 is
the one that takes real time.

## 8. Risks

- **Do not rewrite the engines.** 958 tests pass. This is a re-frame: a
  new layer on top and one existing layer extended backwards.
- **A score invites false precision.** C-ratings are bands for exactly
  that reason, and every rating must state the two or three figures that
  produced it. A number with no visible derivation is worse than no
  number.
- **The floor needs an honest essential-spending figure.** Users will
  understate it. Ask for it as a question about what they could not cut,
  not as a budget line.
- **Every rate still gets verified against the publisher.** A scorecard
  makes wrong figures *more* dangerous, not less, because it compresses
  them into a single reassuring letter.
