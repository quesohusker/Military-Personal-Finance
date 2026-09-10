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

## 2. The Roth CZTE bug — DONE, committed (`6973435`)

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

Committed as `6973435` after a full re-drive of every page.

---

## 3. Date of Rank — DONE

HANDOFF recorded this as unresolved, on the reading that Paul had pointed
at the years-of-service field, where a Date of Rank genuinely would be a
category error — that field drives longevity pay and the retirement
multiplier.

**Paul was right and the earlier session checked the wrong field.**
`ServiceMember` already carried `time_in_grade_years`, and the Profile
page already asked for it one row *below* years of service:

```
pages/1_Profile.py:38   "How many years have you served?"   -> years_of_service
pages/1_Profile.py:39   "How long in your current grade?"   -> time_in_grade_years
```

Date of Rank is exactly the date form of that. It is strictly better than
a number of years, because a DOR is a fact off the LES or ORB that does
not change until the next promotion, whereas "years in grade" is right on
the day it is typed and quietly wrong every time the plan is opened
afterwards. That matters: `time_in_grade_years` feeds
`grade_history()` in `engine/income/social_security.py`, which
reconstructs when the member was promoted in order to build the Social
Security earnings record. A stale figure puts the promotion in the wrong
year.

### What changed

| File | Change |
|---|---|
| `engine/profile.py` | `date_of_rank: str = ""` (ISO text, mirroring `diems_date`), a `dor` property, and `time_in_grade(as_of=None)`. DOR wins when set; the typed number is the fallback. A future or unparseable DOR falls back rather than returning a negative. |
| `engine/income/social_security.py` | reads `member.time_in_grade()` instead of the raw field |
| `pages/1_Profile.py` | asks for the Date of Rank; shows derived time in grade as a caption when set, and only falls back to the number widget when it is blank, so the two can never disagree |
| `pages/3_Career.py` | shows time in grade beside the promotion sliders, which are in years of service — but only from a real DOR, since a stale figure stated that confidently is worse than saying nothing |
| `tests/test_coach_and_career.py` | 8 tests |

`time_in_grade_years` is deliberately **not** deleted. Every plan saved
before this existed carries one, and old plans must keep loading — there
is a test for exactly that.

### Deliberately NOT done: the retire-in-grade rule

An officer must serve a minimum time in grade to retire *at* that grade,
and retiring short of it drops the pension to the lower grade. That is a
five-figure consequence and the app does not model it.

It is not implemented because the minimums would have to be written from
memory, and HANDOFF's rule is that a figure is verified against the
publisher or it does not go in. `.gov` and `.mil` hosts are unreachable
from this container. **This needs Paul to fetch the source on his Mac
before anyone builds it.** It is the highest-value remaining item on this
thread.

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

- **The retire-in-grade minimums** (see section 3) — blocked on a
  published source Paul has to fetch.
- `data_editor` column headers are still noun labels rather than
  questions. They double as the DataFrame keys the save loops read back,
  so renaming them changes code, not labels.
- The annual January refresh: DFAS pay tables and the DTMO BAH archive.
- The biggest gap in the app remains a lifetime year-by-year cash-flow
  projection tying the active-duty years to the retiree engine.
