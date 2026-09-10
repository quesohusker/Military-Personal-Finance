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

## 4a. The evidence — this is not a new idea, it is a scattered one

A full inventory of all 23 pages turned up three things that change how
strong the case is.

### The app is already status-gated, thirty times over, ad hoc

There are **30+ separate status gates** already in the pages. A sample:

```
1_Profile     show_retiree = (m.component in (RETIRED,)
                              or m.retired_pay_monthly > 0
                              or m.va_disability_monthly > 0)
2_Pay         if m.component in (GUARD, RESERVE):
7_Deployment  is_brs = has_tsp_match(m.retirement_system)
8_Pension     if system == S.SYS_BRS:        # lump-sum section
9_Survivor    if m.retired_pay_monthly > 0:  # else "enter your retired pay"
16_Healthcare if m.component in (VETERAN, CIVILIAN):
              HC.plans_for(m.component)      # the option list itself
19_Housing    bah = ... if m.is_serving else BAH.BAHResult()
22_Taxes      if m.is_serving:               # combat-zone months
```

**The funnel is not new behaviour. It is the behaviour the app already
has, done once and consistently instead of thirty times by hand.** Each
of those gates was written independently, they disagree about what
"retired" means (component? retired pay? VA rating?), and a reader has no
way to know which pages will change shape until they visit them.

### The same question is asked in up to three places

| Field | Asked on |
|---|---|
| `in_combat_zone`, `months_deployed_this_year`, `drawing_hostile_fire_pay`, `sdp_balance` | Profile **and** Deployment |
| `retired_pay_monthly`, `sbp_elected` | Profile, Survivor Benefits, Import Pay Statement |
| `civilian_wages_annual` | Profile **and** Social Security |
| `state_of_legal_residence` | Profile (free text) **and** Residency & GI Bill (dropdown) |
| `grade`, `years_of_service`, `has_dependents`, `duty_zip` | Profile **and** Import Pay Statement |

Worse, three pages — **Pension**, **Medical Separation**, **Taxes** —
write *nothing* back at all. Every input on them is a page-local knob
seeded from the profile, so a member who corrects a figure there has
corrected nothing. Medical Separation has **eighteen** such inputs.

That is the chaos, precisely located. Intake fixes it by asking once.

### Two defects found on the way

- **`pages/10_Residency_and_Education.py`** assigns
  `h.state_of_legal_residence = slr` directly rather than through the
  `choice()` helper, so it never calls `mark_dirty()` or `invalidate()`.
  Changing your state of legal residence there leaves the plan looking
  saved and leaves cached results stale.
- **`m.bas_monthly_override` has no page.** It can only be set by the LES
  importer. Anyone typing their plan in by hand cannot enter it.

### The Career timeline is not saved with the plan

`pages/3_Career.py` keeps the whole timeline — separation year,
promotions, PCS moves — in `st.session_state["timeline"]`, never in the
Household. **It is lost on every reload and absent from every downloaded
plan file.**

That matters more than it looks: promotions and the separation point are
exactly the inputs the spine needs to model the serving years. **Step 4
of the build order is blocked until the timeline is persisted**, so that
moves into step 1.

## 4b. The fault line under all of this

Mapping all 42 engine modules turned up the structural problem the
navigation was only a symptom of.

### There are two data models, and they disagree

```
Household / ServiceMember      the app's model. 23 pages read and write it.
Profile / Person / Military…   the projection's model. Nothing writes it.
        ↑
   engine/retirement/roth_bridge.py   the ONLY thing that connects them
```

They are not just separate — they **disagree**:

| | `profile.py` | `roth_profile.py` |
|---|---|---|
| High-3 | `"High-3"` | `"High-3 (Legacy)"` |
| No pension | `SYS_NONE` | `"No military retired pay"` |
| Assumptions units | percent (`4.0`) | decimal (`0.045`) |

`roth_bridge.py` exists to translate between them, holding a `SYSTEM_MAP`
and a percent-to-decimal conversion. And `RothInputs` — 30-odd fields —
exists because **`Profile` needs things `Household` does not carry**:
death ages, spouse balances, cost basis, conversion strategy.

Most telling of all: **`Profile` has no field for whether the member is
still serving.** No grade, no DIEMS date, no BAH, no BAS, no debts, no
home. It is a purely retiree-shaped cash-flow input.

That is why the spine stops at the retiree. It was never given the
vocabulary to describe someone in uniform.

**The scorecard must read one model.** Extending the spine over the
serving years means teaching `Profile` about service — grade, DIEMS,
promotions, separation — or collapsing the two models into one. That
decision comes before step 4 and is the single largest call in this
design. *Recommendation:* extend `Profile`, keep the bridge, and do not
attempt a merge — `Household` is a UI-entry model and `Profile` is a
projection input, and they are legitimately different shapes.

### `prime_directive` already solves the funnel-scoring problem

`engine/coach/prime_directive.py` is the closest thing to a scorecard
that exists, and it already does the hard part:

```python
Step{key, order, title, status, why, action,
     amount_needed, amount_done, target, military_note, weight}
     .applies   .complete   .progress          # 0..1

score = round(100 * Σ(weight*progress) / Σ(weight), 1)   # applicable only
```

Steps carry a `weight` and an `applies` gate, and **the score
renormalises over applicable weight** — so 12 of 12 steps for a serving
member and 8 of 12 for a veteran still produce comparable scores. That is
exactly the problem three funnels create, already solved.

**Copy this shape for the readiness scorecard.** It scores the wrong
thing — waterfall completion, not readiness — but the mechanism is right
and it is already tested.

### Sixteen modules already emit findings

`tax/current_year`, `benefits/healthcare`, `benefits/sbp`,
`benefits/concurrent_receipt`, `benefits/disability_separation`,
`housing/rent_vs_buy`, `housing/va_loan`, `career/transition`,
`income/spouse`, `income/social_security`, `investments/tsp_allocation`,
`debt/payoff`, `networth/balance_sheet`, `estate/planning`,
`retirement/roth_analysis`, `assumptions.sanity`.

A component's rating can be **derived from findings that already exist**,
with severity and dollars-at-stake driving the band. The scorecard is
largely an aggregator, not a new analysis engine.

### One nuance for the floor

`investments/tsp_allocation.pension_as_bond()` sums retired pay **+ VA +
CRSC**. So a rated veteran with no pension still gets a partial floor —
the component is not retiree-only, which is another argument against
forking Veteran and Retiree in the engine.

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
| 1 | **Persist the Career timeline** into the Household, and add **essential vs discretionary spending** | Both are small, and both are prerequisites. The timeline is currently lost on reload and step 4 cannot start without it; the spending split unblocks the floor. |
| 2 | **`engine/scorecard/`** over the existing retiree projection | Six of eight components work immediately for retirees and veterans. Proves the frame before the expensive part. |
| 3 | **Scorecard page**, C-ratings, drill-down links | The app has a front door and an answer. |
| 4 | **Teach `Profile` about service, then extend the spine over the serving years** | The expensive step, and the one HANDOFF has been asking for. `Profile` has no concept of serving at all (§4b), so that comes first. Unlocks the Serving funnel properly. |
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
