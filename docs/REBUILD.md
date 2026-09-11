# The retiree rebuild — what is kept, what goes, what surprised us

Decided 2026-09-11. **Nothing is built yet.** This is the demolition plan,
grounded in the import graph rather than in anyone's memory of the
codebase — including mine, which was wrong twice.

**The decision:** narrow to military retirees, rebuild the shell, keep
the engines. `main` currently holds 51 engine modules, 27,850 lines,
26 pages and 1,428 passing tests.

---

## What the import graph actually says

Walking every `engine.*` import from the entry points a retiree hits:

| | Modules | Lines |
|---|---:|---:|
| **Reachable by a retiree** | 42 | 21,226 |
| **Unreachable** | 9 | 6,104 |

I had estimated "roughly 8,000 lines go dormant". **It is 6,104**, and the
composition is not what I claimed.

## The correction that matters: `pay/` and `career/` do not go dormant

I said all of `engine/pay/` and all of `engine/career/` could be moved
aside as serving-only. **That is wrong, and the reason is worth
understanding before anyone tries it again.**

```
engine.pay.basepay     ← social_security, prime_directive, roth_bridge, pay.taxable
engine.pay.bah         ← roth_bridge, tax.current_year, housing.rent_vs_buy
engine.career.timeline ← engine.profile, social_security, roth_bridge
engine.tax.military    ← benefits.healthcare, tax.current_year
```

**A retiree's Social Security estimate is reconstructed from their own
career.** `income/social_security.py::estimate_pia_from_career()` walks
the grade history and prices each year off the published pay tables,
because a member who never had an ssa.gov statement still needs a PIA.
That needs `basepay`, `grades` and `career/timeline` — for somebody who
left the service twenty years ago.

Likewise `tax/military.py` holds the CZTE machinery *and* the
taxable/untaxed split that `benefits/healthcare.py` reads.

**Those are history, not active duty.** They stay.

## What genuinely goes

| | Lines | Why |
|---|---:|---|
| `engine/funnel.py` | 1,234 | The three-funnel machinery. Superseded by narrowing to one audience. |
| `engine/intake/` (4 modules) | 1,655 | Funnel-specific question sets and the pay confirmation. The pay-confirmation *behaviour* is worth keeping; the funnel scaffolding is not. |
| `engine/ingest/` (2 modules) | 2,695 | PDF import, deprioritised. `docs/IMPORT_FINDINGS.md` holds the diagnosis. |
| `engine/career/transition.py` | 1,239 | Leaving the service — retrospective for someone who left. |
| `engine/benefits/gi_bill.py` | 234 | Transfer is a serving decision. |
| `engine/benefits/disability_separation.py` | 281 | Chapter 61 is an exit event. |
| The 26-page menu | — | Replaced by whatever the retiree shell turns out to be. |
| The eight-component scorecard, as shaped | — | See below. |

**`engine/funnel.py` shows as "live" in the graph only because
`scorecard/components.py` imports it.** That dependency has to be cut
before the funnel can go, and it is the one real entanglement between the
two things being removed.

## Nothing is deleted

All of it moves aside intact and tested. It is correct code that a second
audience will want, and the cost of keeping it is a directory name. The
cost of deleting it is paying for the same lessons twice — this is a
codebase where checking has repeatedly beaten recollection, and
`docs/VERIFIED.md` records 21 figures confirmed and 14 corrected.

## The scorecard question, still open

Eight components rated C-1..C-5 was designed when the app served three
audiences and had to produce comparable ratings across them. For a
retiree alone that machinery may be more than the job needs.

For a retiree **income is locked** — pension, VA, SBP and Social Security
are decided. What is left is **sequencing**: when to claim, how much to
convert, which account to draw first, and what reaches the heirs. That is
a different question from "are you ready", and it may want a timeline
with decision points rather than a scorecard.

**Not decided.** It depends on the plan document being brought across.

## The privacy claim has to be settled first

`pages/0_Overview.py` says *"Nothing you enter leaves this machine. No
account, no server, no analytics."* Three other pages repeat it.

`HANDOFF.md` says the app deploys to **Streamlit Community Cloud**. That
is a server. At the hosted URL the app runs on Streamlit's
infrastructure, an uploaded plan reaches their container, and
`saved_plans/` writes to their disk — `engine/storage.py`'s own comment
hedges with *"works when Streamlit runs on"* the user's machine.

**The claim is true run locally and false at the hosted URL.** Given the
app handles a Retiree Account Statement, account balances and an estate
plan, the resolution should be local-only, and the hosted deployment
should go. Convenience is not worth a false promise about a pay
statement.

## The rule that keeps generalising cheap

Build for one retiree first, generalise after — but:

> **Figures go in the JSON. Rules go in the engine. Nothing about one
> person gets hardcoded.**

The moment a year, a target, or a retirement system appears as a literal
inside a calculation rather than as a value read from the plan, the
result works for one person and cannot be lifted. This costs nothing now
and is the whole difference later.
