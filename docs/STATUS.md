# Where this work is — pick up here

Written 2026-09-10 mid-session. Read `docs/REORGANIZATION.md` alongside
this; that one is the *why* of the menu change, this one is the *state of
play* across everything currently in flight.

**Branch** `claude/boldin-page-reorganization-x0j7wy`
**PR** quesohusker/Military-Personal-Finance#1 (draft, not merged)
**Base** `main` — nothing has deployed; Community Cloud deploys on merge.

---

## 1. Menu reorganization — DONE, committed, pushed

Two commits are on the branch and pushed:

| | |
|---|---|
| `8fed55c` | the decision record, `docs/REORGANIZATION.md` |
| `85caa2d` | the rename and regroup, 43 files |

Every page title is now a noun. Groups are `General` / `Currently
Serving` / `Veteran` / `Retiree`. `What I actually get paid` → `Income`,
and 21 others; the full old-to-new map is in `REORGANIZATION.md`.

**Verified:** 940 tests pass; all 23 pages driven in headless Chromium
against both sample plans, no traceback, no `.katex` node.

**The one open question for Paul:** `General` holds 13 of 23 pages. A
grouping whose catch-all is more than half the app is doing less work
than the group names suggest, and this is the half of the change that
pulls against the Boldin reference — Boldin splits by *subject* (facts in
`My Plan`, what-ifs in `Explorers`), not by audience. The subject-based
alternative is fully specified in `REORGANIZATION.md` under "Considered
and rejected" if he wants to switch. He has not looked at the sidebar
yet.

---

## 2. The Roth CZTE bug — FIXED, NOT YET COMMITTED

This was HANDOFF's second open item and it was a genuinely wrong number.

### What was wrong

`engine/pay/taxable.py::compute().annual` is deliberately the figure
**before** the Combat Zone Tax Exclusion — the domicile comparison wants
what is at stake in a normal year, and its docstring says so. The Roth
bridge called it anyway. So the E-5 sample, seven months in the zone, was
modelled at the full **$49,320** of taxable wages when the real figure
is **$20,550**. The member paid phantom tax on $28,770 that never
reaches a return — in the one year it matters most, because a deployed
year is the cheapest conversion window most members will ever get.

### The design decision that mattered

The naive fix — subtract the exclusion from `wages_annual` — is wrong the
other way. That wage is grown forward for every working year, so a
seven-month deployment would model a **thirty-year pay cut**.

A deployment is a *this-year* event, so the fix is a first-year-only
figure. Later years use the full wage.

### What changed

| File | Change |
|---|---|
| `engine/pay/taxable.py` | new `czte_months(m)` and `annual_after_czte(m, months=None)`. `compute().annual` is untouched — domicile still needs the pre-exclusion figure. Local import of `engine.tax.military` inside the function to avoid a cycle. |
| `engine/roth_profile.py` | `Person.wages_first_year: float = 0.0` (0 = first year is like every other) |
| `engine/retirement/projection.py` | the wage loop uses `wages_first_year` when `yrs == 0`, ungrown |
| `engine/retirement/roth_bridge.py` | `RothInputs.wages_this_year`; new `_member_wages_this_year()`; `_member_wages()` docstring now says why it stays pre-exclusion; `describe()` shows the deployed year |
| `pages/14_Roth_Conversions.py` | first input relabelled "in a full year" (it feeds *every* year, so "this year" was the actual mislabel); new conditional input "And this year, with combat-zone pay excluded?" that only appears when the exclusion applies, with help text that finally says it is editable and why |
| `tests/test_roth_engine.py` | 7 regression tests appended |

The bonus is deliberately left taxable. A bonus paid in the zone is
excluded whole, but whether it *was* paid in the zone is a question the
profile does not ask, and assuming it was would understate the tax bill.
Erring the other way costs conversion room rather than inventing it.

### Numbers, E-5 sample

```
                      before        after       delta
year-1 wages          49,320       20,550     -28,770
year-1 taxable        55,120       26,350     -28,770
year-1 tax             6,118        2,666      -3,452
lifetime tax         519,952      496,745     -23,207
```

$20,550 is exactly the box-1 figure HANDOFF quotes for this sample,
which is a good independent check. Arithmetic: enlisted members exclude
ALL military pay in a qualifying month, so 5/12 × 49,320 = 20,550.

The conversion *advantage* falls slightly ($36,923 → $33,735) because the
no-conversion baseline also pays less tax. That is correct, not a
regression.

### Verification done

- 940 existing tests still pass; 7 new ones pass (78 in
  `test_roth_engine.py`).
- **Mutation-checked**: disabling the `wages_first_year` branch in
  `projection.py` makes exactly 2 of the new tests fail. They are not
  passing by accident.

### NOT yet done for this fix

- Not committed. Working tree is dirty with all of the above.
- Browser drive has **not** been re-run since the page-14 edit. Do it
  before committing — the new input is inside an `input_card` and the
  page must be re-driven per HANDOFF discipline.

---

## 3. Date of Rank — INVESTIGATED, NOT STARTED

HANDOFF's first open item, recorded as unresolved: *"Paul asked to
'change to What is your Date of Rank?' while pointing at the
years-of-service field. Those are different things … Still unresolved;
ask before touching it."*

Paul has now said: **"add Date of Rank where needed"** — an addition, not
a rename.

### What the investigation found — Paul was right, the earlier session guessed the wrong field

`ServiceMember` **already carries `time_in_grade_years: float = 2.0`**,
and the Profile page already asks for it, one row *below* years of
service:

```
pages/1_Profile.py:38   "How many years have you served?"   -> years_of_service
pages/1_Profile.py:39   "How long in your current grade?"   -> time_in_grade_years
```

Date of Rank is exactly the date form of time in grade: TIG = today −
DOR. The earlier session assumed Paul was pointing at `years_of_service`
(where DOR genuinely would be wrong — that drives longevity pay and the
retirement multiplier) and never checked the adjacent field. Pointing at
"How long in your current grade?" and asking for Date of Rank is
**correct and an improvement**, because:

- A DOR is a fact off the LES/ORB that does not change until promotion.
- "Years in grade" goes stale the moment the plan is saved and reopened
  next year. It is a number that silently rots.
- `diems_date` is already stored as ISO text on the same dataclass, so
  there is a house pattern to copy exactly.

### Where `time_in_grade_years` is actually consumed

```
engine/income/social_security.py:567  grade_history(...)
engine/income/social_security.py:582  promoted_at = years_of_service - time_in_grade_years
engine/income/social_security.py:657  steps = grade_history(..., member.time_in_grade_years, ...)
```

It reconstructs the earnings record for Social Security by working out
when the member was promoted. So a stale TIG quietly distorts the SS
earnings history — which is a real, if second-order, money error.

### The plan (not yet written)

1. Add `date_of_rank: str = ""` to `ServiceMember`, ISO text, mirroring
   `diems_date`. Add a `dor` property mirroring the existing `diems`
   property that parses it.
2. Make `time_in_grade_years` **derived from DOR when DOR is set**, and
   keep the typed number as the fallback for anyone who does not know
   their DOR. Do NOT delete the field — old saved plans carry it and must
   keep loading.
3. Profile page: ask "What is your Date of Rank? (YYYY-MM-DD)" using the
   same `text()` helper as DIEMS. When it is set, show the derived time
   in grade as a caption rather than a second editable number, so the two
   cannot disagree.
4. Consider surfacing it on **Career** (`pages/3_Career.py`) — time in
   grade gates promotion eligibility, and `engine/career/timeline.py`
   currently schedules promotions purely off years of service.
5. There is a real second use worth checking before building: the
   **retire-in-grade** rule. An officer must serve a minimum time in
   grade (generally 3 years) to retire *at* that grade, and retiring
   short of it drops the pension to the lower grade. That is a five-
   figure consequence and the app does not model it. Verify the rule
   against a publisher before implementing — do not write it from
   memory.
6. Tests, and a browser drive.

**Nothing for Date of Rank has been written yet.** Item 5 in particular
needs a published source, and `.gov`/`.mil` hosts are unreachable from
this container (see HANDOFF, "Sourcing rates: the .gov problem") — so it
may need Paul to fetch a page on his Mac.

---

## 4. Environment notes for whoever picks this up

- Deps are installed here, but `cryptography` was broken on first run
  (`ModuleNotFoundError: _cffi_backend`) and made 6 PDF tests fail in a
  way that looks like a code bug and is not. `pip install --upgrade cffi`
  fixes it. Re-check before believing any PDF-test failure.
- Playwright's Python package is NOT preinstalled — `pip install
  playwright`. The browser IS: `/opt/pw-browsers/chromium`. Do not run
  `playwright install`.
- The browser-drive script written for this work lives in the session
  scratchpad, not the repo:
  `/tmp/claude-0/-home-user-cv19/22177656-9bbb-5185-befa-609f42876465/scratchpad/drive_pages.py`
  It is worth moving into `scripts/` — it is the only automated version
  of the verification discipline HANDOFF insists on.
  **Its one trap:** loading a sample plan requires clicking the button
  labelled **"Open this file"**. An earlier version of the script tried
  three other labels, matched none, and silently drove every page with a
  *blank* plan while reporting a pass. It now raises if the plan did not
  load. Any rewrite must keep that assertion.
- Run the app: `python3 -m streamlit run Military_Finance.py --server.port 8501
  --server.headless true --server.fileWatcherType none`

## 5. Still untouched from HANDOFF's open items

- `data_editor` column headers are still noun labels rather than
  questions. They double as the DataFrame keys the save loops read back,
  so renaming them changes code, not labels.
- The annual January refresh: DFAS pay tables and the DTMO BAH archive.
- The biggest gap in the app remains a lifetime year-by-year cash-flow
  projection tying the active-duty years to the retiree engine.
