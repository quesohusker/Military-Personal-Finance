# Where this work is — pick up here

Current as of 2026-09-10, end of session. This is the *state of play*;
`docs/REORGANIZATION.md` is the *why* behind the menu change. Read
`HANDOFF.md` first if you are new to the repo.

**Branch** `claude/boldin-page-reorganization-x0j7wy`
**PR** [#1](https://github.com/quesohusker/Military-Personal-Finance/pull/1) — **draft, not merged**
**Base** `main` — nothing has deployed. Community Cloud deploys on merge.

```
11f1dd1  Ask for a Date of Rank instead of a number that goes stale
6973435  Stop taxing a deployed member on pay that never reaches a return
85caa2d  Rename every page to a noun and regroup the menu by audience
8fed55c  Record the Boldin-style page reorganization decisions
```

All four are pushed; local and remote are identical. Working tree clean.

**958 tests pass** (was 940; 15 added). Every page driven in headless
Chromium against both sample plans after each change — no traceback, no
`.katex` node.

---

## The one thing waiting on Paul

**Does `General` holding 13 of the 23 pages read as a junk drawer?**

Everything else on this branch is finished. This is the only open design
question, and it needs his eyes on the actual sidebar rather than a
description of it.

```bash
cd ~/Military-Personal-Finance
git fetch origin
git checkout claude/boldin-page-reorganization-x0j7wy
./mpf.sh restart
```

Three outcomes:

1. **Reads fine** → mark PR #1 ready and merge.
2. **Too big** → switch to the subject-based grouping already specified
   in `REORGANIZATION.md` under "Considered and rejected": `My Plan` /
   `Explore` / `Military` / `Import`, spread 7/7/6/2, no catch-all. That
   is what Boldin actually does. Only the router and two docs change; no
   engine or page code moves.
3. **Specific titles wrong** → cheap to change now, expensive once they
   are back in prose in forty places.

---

## 1. Menu reorganization — DONE

Titles are nouns. The rule throughout: **the title says the subject, the
subtitle says the question.** `Do I stay to twenty?` became `Pension`,
with the stay-or-go question moved into the subtitle. `What I actually
get paid` → `Income`, and 21 others. Full map in `REORGANIZATION.md`.

Groups went from career-event (`Where I stand`, `When I deploy`, …) to
audience: `General` / `Currently Serving` / `Veteran` / `Retiree`. Where
a page could sit in two, it is filed by **who makes the decision the page
models**, not who benefits.

This does **not** touch the house rule that widget labels are
second-person questions. That rule is about inputs, where a noun invites
a user to treat a guess as a given. Page titles are navigation.

### Why the diff was 43 files

Page names appear as prose cross-references in about forty places —
finding details, `help=` strings, the LES importer's `where=` pointers.
**A missed one is silent**: nothing crashes, the user is just sent to a
name that is not in the sidebar. The sweep ran from a grep over exact old
titles, and sentences were rewrapped so the noun reads naturally rather
than being substituted in place.

Two strings in `engine/housing/va_loan.py` — "keep the house at…" and
"money invested at…" — are ordinary prose a blind replace would corrupt.
Deliberately untouched. Any future rename needs the same care: **match
the full old title, never a fragment.**

Filenames are unchanged. Streamlit takes the title from `st.Page`, not
the path.

---

## 2. The Roth CZTE bug — DONE (`6973435`)

HANDOFF's second open item, and a genuinely wrong number.

### What was wrong

`engine/pay/taxable.py::compute().annual` is deliberately the figure
**before** the Combat Zone Tax Exclusion — its docstring says so, because
the domicile comparison wants what is at stake in a normal year. The Roth
bridge called it anyway. The E-5 sample, seven months in the zone, was
modelled at the full **$49,320** when the real taxable figure is
**$20,550**: phantom tax on $28,770 that no return ever sees.

It matters more than the size suggests. A deployed year is the cheapest
conversion window most members will ever get, and overstating the wage
hides exactly that.

### The design decision that mattered

The naive fix — subtract the exclusion from `wages_annual` — is wrong the
other way. That wage is grown forward for every working year, so a
seven-month deployment would model a **thirty-year pay cut**. A
deployment is a this-year event, so the reduction applies once, ungrown.

### What changed

| File | Change |
|---|---|
| `engine/pay/taxable.py` | new `czte_months(m)` and `annual_after_czte(m, months=None)`. `compute().annual` untouched — domicile still needs the pre-exclusion figure. Local import of `engine.tax.military` inside the function avoids a cycle. |
| `engine/roth_profile.py` | `Person.wages_first_year` (0 = first year is like every other) |
| `engine/retirement/projection.py` | wage loop uses `wages_first_year` when `yrs == 0` |
| `engine/retirement/roth_bridge.py` | `RothInputs.wages_this_year`; `_member_wages_this_year()`; `describe()` shows the deployed year |
| `pages/14_Roth_Conversions.py` | first input relabelled "in a full year" — it feeds *every* year, so "this year" was the real mislabel. New conditional input appears only when the exclusion applies, with help text that finally says the figure is editable and why. |
| `tests/test_roth_engine.py` | 7 regression tests |

The bonus is deliberately left taxable. A bonus paid in the zone is
excluded whole, but whether it *was* is a question the profile does not
ask, and assuming it was would understate the tax bill. Erring the other
way costs conversion room rather than inventing it. **If a
`bonus_paid_in_zone` field is ever added to the profile, wire it here** —
`engine/tax/current_year.py` already takes it as a parameter.

### Numbers, E-5 sample

```
                      before        after       delta
year-1 wages          49,320       20,550     -28,770
year-1 taxable        55,120       26,350     -28,770
year-1 tax             6,118        2,666      -3,452
lifetime tax         519,952      496,745     -23,207
```

$20,550 is exactly the box-1 figure HANDOFF quotes for this sample — a
good independent check. Enlisted members exclude ALL military pay in a
qualifying month, so 5/12 × 49,320 = 20,550.

The conversion *advantage* falls slightly ($36,923 → $33,735) because the
no-conversion baseline also pays less tax. Correct, not a regression.

**Mutation-checked**: disabling the `wages_first_year` branch in
`projection.py` fails exactly 2 of the 7 new tests. They are not passing
by accident.

---

## 3. Date of Rank — DONE (`11f1dd1`)

HANDOFF recorded this unresolved, on the reading that Paul pointed at the
years-of-service field — where a Date of Rank genuinely would be a
category error, since that field drives longevity pay and the retirement
multiplier.

**Paul was right; the earlier session checked the wrong field.**
`ServiceMember` already carried `time_in_grade_years`, and Profile
already asked for it one row *below* years of service:

```
pages/1_Profile.py:38   "How many years have you served?"   -> years_of_service
pages/1_Profile.py:39   "How long in your current grade?"   -> time_in_grade_years
```

Date of Rank is the date form of that, and the better way to store it: a
DOR is a fact off the LES or ORB that does not change until the next
promotion, while a number of years is right on the day it is typed and
quietly wrong every time the plan is reopened.

Not cosmetic — `time_in_grade_years` feeds `grade_history()` in
`engine/income/social_security.py`, which reconstructs when the member
was promoted to build the Social Security earnings record. A stale figure
puts the promotion in the wrong year.

| File | Change |
|---|---|
| `engine/profile.py` | `date_of_rank: str = ""` (ISO text, mirroring `diems_date`), a `dor` property, and `time_in_grade(as_of=None)`. DOR wins when set; the typed number is the fallback. A future or unparseable DOR falls back rather than returning negative years. |
| `engine/income/social_security.py` | reads `member.time_in_grade()` |
| `pages/1_Profile.py` | asks for the DOR; shows derived time in grade as a caption when set, and only offers the number widget while blank, so the two cannot disagree |
| `pages/3_Career.py` | shows time in grade beside the promotion sliders (which are in years of service) — but only from a real DOR, since a stale figure stated that confidently is worse than saying nothing |
| `tests/test_coach_and_career.py` | 8 tests |

`time_in_grade_years` is deliberately **not** deleted. Every plan saved
before this carries one and must keep loading; there is a test for it.
The sample plans still use the fallback path, which is deliberate — it
keeps backwards compatibility exercised.

---

## 4. The funnel front door — DONE (`a585a76`)

Built by four agents against a contract written first, then reviewed and
approved by the agent that wrote the contract before anything was
committed.

- `engine/funnel.py` + `docs/FUNNEL_CONTRACT.md` — the funnel model, the
  `Question` schema, and the prescriptive contract everything compiles
  against.
- `engine/intake/serving.py` · `veteran.py` · `retiree.py` — 59
  questions, none duplicating the common set.
- `pages/00_Start.py` — the front door. One question, three cards
  rendered from `FUNNEL_SPECS`.
- `pages/01_Intake.py` — the renderer. **No funnel name, no key prefix,
  no branch in the file.** Adding a funnel is a spec and a question
  module, not a page.

**The funnel feeds the 30+ existing status gates rather than replacing
them.** `set_funnel()` moves `member.component` underneath them; none
were rewritten. It is not a permissions system — all 23 pages stay
reachable from every funnel.

### Three defects caught in review, before the commit

1. A `help=` string carried a `$` pair. Help text cannot be escaped at
   render time, so `validate()` now rejects the pattern.
2. A GI Bill question wrote "children who could use the benefit" into the
   field the estate planner reads as "children" — four children, two over
   26, would have silently halved the gifting plan. That is the §4a
   one-field-two-meanings defect, reintroduced by the thing built to end
   it.
3. Card order was smuggled through card titles; all three modules gamed
   alphabetical sorting and one only worked because uppercase `V` sorts
   below lowercase `c`. Questions now carry an explicit `group_rank`.

### Deliberately not stored

`sbp_base_amount_monthly` — the projection already treats 0 as full
retired pay, and `roth_bridge.py` never passes a base through, so the
field would collect an answer that changes no number and invite a
reduced-base retiree to trust a figure it never reaches. GI Bill months
remaining, a civilian employer plan and promotion expectations have no
field on `ServiceMember`, and none was invented.

**Verified:** 1178 tests (up from 958); all 25 pages driven in headless
Chromium against both sample plans, no traceback and no `.katex` node;
all three funnels driven from the landing page through to a rendered
intake (29 / 23 / 23 widgets).

### Next, per ARCHITECTURE.md §7

Step 1 is **not** finished: the Career timeline is still unpersisted
(`st.session_state` only) and blocks extending the spine over the serving
years. Then `engine/scorecard/` over the existing retiree projection —
six of eight components work immediately.

---

## Next up: the retire-in-grade rule — BLOCKED on a source

An officer must serve a minimum time in grade to retire *at* that grade.
Retiring short of it drops the pension to the lower grade — a five-figure
consequence the app does not model. Now that a Date of Rank exists, the
input is there and this is the natural next build.

**It is blocked, not forgotten.** The minimums would have to be written
from memory, and this repo's rule is that a figure is verified against
the publisher or it does not go in (see HANDOFF, "Sourcing rates: the
.gov problem" — checking has caught errors repeatedly, including
TRICARE Select Group B carried at a third of its true cost).

`.gov` and `.mil` hosts are unreachable from the build container. **Paul
needs to fetch the source on his Mac** — DFAS or the service personnel
regulations — before anyone implements it. Do not guess the numbers.

---

## Environment traps — read before debugging

- **`cryptography` is broken on a fresh container.**
  `ModuleNotFoundError: _cffi_backend` makes 6 PDF tests fail in a way
  that looks exactly like a code bug and is not. `pip install --upgrade
  cffi` fixes it. Re-check before believing any PDF-test failure.
- **Playwright's Python package is not preinstalled** — `pip install
  playwright`. The browser **is**: `/opt/pw-browsers/chromium`. Do not
  run `playwright install`.
- **`pkill -f "streamlit run"` kills its own shell** — the pattern
  matches the `bash -c` command line. Use `fuser -k 8501/tcp`.
- Run the app:
  `python3 -m streamlit run Military_Finance.py --server.port 8501 --server.headless true --server.fileWatcherType none`

### The browser-drive script

Lives in the session scratchpad, **not in the repo**:
`/tmp/claude-0/-home-user-cv19/22177656-9bbb-5185-befa-609f42876465/scratchpad/drive_pages.py`

It is the only automated version of the verification discipline HANDOFF
insists on, and **it is worth moving into `scripts/`** — that is a small
loose end. It drives all 23 pages and fails on a traceback or any
`.katex` node.

**Its two traps, both paid for the hard way:**

1. Loading a sample plan requires clicking the button labelled **"Open
   this file"**. An earlier version tried three other labels, matched
   none, and silently drove every page against a *blank* plan while
   reporting a pass. It now raises if the plan did not load. **Any
   rewrite must keep that assertion** — a green run that tested nothing
   is worse than a red one.
2. Pass **absolute** paths to the sample plans. Relative paths resolve
   against the wrong directory and hit the same false-pass shape.

---

## Still open from HANDOFF

- **Retire-in-grade minimums** — see above; blocked on a published
  source.
- **`data_editor` column headers** are still noun labels rather than
  questions. They double as the DataFrame keys the save loops read back,
  so renaming them changes code, not labels.
- **The annual January refresh**: DFAS pay tables and the DTMO BAH
  archive. Neither host will ever serve an automated request.
- **The biggest gap remains a lifetime year-by-year cash-flow
  projection** tying the active-duty years to the retiree engine. The
  Roth engine does the retiree half.
- **The importers have still never seen a real document.** DFAS is a
  `.mil` host. Paul's first real upload is the actual test.
