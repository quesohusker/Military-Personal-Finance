# The funnel contract

What every agent building on the intake funnel compiles against. It is
prescriptive on purpose: anything left ambiguous here gets resolved three
different ways by three different agents.

Two modules are the foundation and they are **already written**:

* `engine/funnel.py` — the funnel model and the question schema.
* `engine/intake/__init__.py` — assembly and the extension point.

You are writing one of `engine/intake/serving.py`, `veteran.py`,
`retiree.py`, or the pages that render them. Do not edit `engine/funnel.py`,
`engine/profile.py` or `engine/storage.py`.

---

## 1. The import surface

Everything comes from one of two places, and `engine.intake` re-exports all of
`engine.funnel`, so **a page needs one import**.

```python
from engine.intake import (
    # the three funnels, and the fourth state
    FUNNELS, FUNNEL_SERVING, FUNNEL_VETERAN, FUNNEL_RETIRED, FUNNEL_UNSET,
    Funnel, FUNNEL_SPECS, spec, label_for, is_chosen,
    # reading and writing the funnel on a plan
    infer_funnel, funnel_of, set_funnel,
    # the question schema
    Question, QUESTIONS, KINDS, GROUP_ORDER, validate,
    # assembly
    prepare, questions_to_ask, all_questions, funnel_questions, grouped,
    # spending
    essential_monthly, discretionary_monthly, has_essential_split,
)
```

A funnel-specific intake module imports from `engine.funnel` directly, because
`engine.intake` imports *it* and the other direction would be a cycle:

```python
from engine.funnel import (Question, FUNNEL_SERVING, KIND_MONEY, KIND_TOGGLE,
                           KIND_INTEGER, KIND_TEXT, KIND_CHOICE, KIND_PCT,
                           KIND_NUMBER)
```

### What each name is for

| Name | What it is |
|---|---|
| `FUNNEL_SERVING` `FUNNEL_VETERAN` `FUNNEL_RETIRED` | `"serving"` `"veteran"` `"retiree"`. **These strings are in saved plan files. Never change them.** |
| `FUNNEL_UNSET` | `""`. Not an answer — "has not been asked". Not a member of `FUNNELS`. |
| `FUNNELS` | `(FUNNEL_SERVING, FUNNEL_VETERAN, FUNNEL_RETIRED)`, in the order the landing page offers them. |
| `FUNNEL_SPECS` | The three `Funnel` records, same order. What the landing page renders. |
| `spec(key)` | The `Funnel` for a key, or `None` for unset/unknown. |
| `label_for(key)` | Display label; `"Not chosen yet"` for unset. |
| `funnel_of(h)` | **The one you call.** The stored answer if there is one, otherwise the inference. Always one of `FUNNELS`. |
| `infer_funnel(h)` | The inference alone. Only for a plan that has never been asked. |
| `set_funnel(h, key)` | Record the answer *and* fix `h.member.component`. |
| `prepare(h)` | Normalise before a render pass. Call it once at the top of the page. |
| `questions_to_ask(h)` | Everything to put on screen, in render order. |
| `grouped(qs)` | Those questions bundled into input cards. |
| `validate(qs)` | Problems in a question set, as sentences. Empty is good. |

`Funnel` is data, not behaviour: `key`, `label`, `description`, `implies`
(a tuple of plain statements), `default_component`, `frame`.

---

## 2. What the funnel is, and is not

**It is not a permissions system.** `ARCHITECTURE.md` §2. Every page stays
reachable from every funnel. A serving member deciding whether to stay to 20
needs the retiree pages to make that decision. The funnel sets defaults,
ordering and what gets scored. **Do not add `if funnel != X: st.stop()` to any
page.**

**It is not a second status field.** The app has 30+ status gates that read
`member.component` (§4a). None of them are being rewritten. `set_funnel()`
moves `component` underneath them so they keep working:

| Funnel | What `set_funnel` does to `member.component` |
|---|---|
| `serving` | Leaves Active / Guard / Reserve alone. Anything else becomes **Active Duty**. |
| `veteran` | Sets **Veteran (not retired)**. |
| `retiree` | Sets **Military Retiree**. |
| `FUNNEL_UNSET` | Leaves it alone. Clearing the answer must not rewrite the plan. |

`set_funnel()` **never invents or erases money.** Choosing the retiree funnel
does not fabricate a retired-pay figure, so `9_Survivor`'s
`retired_pay_monthly > 0` gate still prompts until the user answers. That is
correct — the funnel decides which questions are asked, not the answers.

`set_funnel()` raises `ValueError` for anything that is not a funnel key or
`FUNNEL_UNSET`.

### Inference, and the disagreement it settles

Applied in order. Two principles decide every ambiguous case:

* **A. Serving wins over everything.** The axis is how much of the future is
  still a decision. In uniform, it is.
* **B. Positive evidence beats a label; absent evidence does not.** Retired pay
  on the plan proves a pension and overrides a "Veteran" label. An *empty*
  retired-pay field proves nothing and never overrides "Military Retiree".

```
1. component in (Active, Guard, Reserve)   -> serving     (unconditional)
2. retired_pay_monthly > 0                 -> retiree     (principle B)
3. component == Military Retiree           -> retiree     (even with no pay)
4. component == Veteran (not retired)      -> veteran     (taken at its word)
5. component == Civilian, years >= 20      -> retiree     (grey-area retiree)
6. anything else                           -> veteran     (the honest default)
```

**VA compensation and VA rating are never evidence.** `1_Profile` shows its
retiree card when `va_disability_monthly > 0`; that is right for the card and
wrong for the funnel. A rated veteran with no pension is squarely the Veteran
funnel. **The DIEMS date is never evidence either** — everyone who served has
one.

`infer_funnel()` never returns `FUNNEL_UNSET`. "Has this been asked?" is
`h.funnel == FUNNEL_UNSET` and is a different question.

---

## 3. The `Question` schema

A `Question` is a rendering instruction: it names a helper in `ui.panel`, the
object to write into, and the attribute on it. Frozen dataclass.

```python
Question(
    key="q_birth_year",                     # widget key STEM, globally unique
    label="What year were you born?",       # second person, ends in "?"
    kind=KIND_INTEGER,                      # one of KINDS
    path="member",                          # dotted from Household; "" = h
    attr="birth_year",                      # attribute on that object
    group="About you",                      # the input_card it sits in
    group_rank=10,                          # that card's place in the page
    order=10,                               # within the group
    funnels=(FUNNEL_SERVING,),              # which funnels ask it
    help="Everything dated runs off this.",
    when=None,                              # optional predicate, see §5
    min_value=1930, max_value=2015,         # widget extras, see §4
)
```

| Field | Default | Notes |
|---|---|---|
| `key` | required | The stem passed to `wkey()`. **Must be unique across the common set and all three funnel modules.** Two widgets sharing a key show each other's value and neither page looks broken. Prefix yours: `srv_`, `vet_`, `ret_`. |
| `label` | required | A question put to the user. Ends in `?` **and** opens with a question word (`QUESTION_OPENERS` in `engine/funnel.py`). `validate()` enforces both — a noun label with a question mark stapled on is the thing the first-word rule catches. Put a format hint in `help`, not in the label: "What is your DIEMS date?" with "Enter it as YYYY-MM-DD" in the help, not "What is your DIEMS date? (YYYY-MM-DD)". |
| `kind` | required | §4. |
| `attr` | required | The attribute written. |
| `path` | `""` | `""` → `h`; `"member"` → `h.member`; `"spouse"` → `h.spouse`; `"investments"`, `"assumptions"`, `"healthcare"`, `"housing"`, `"estate"`, `"social_security"` likewise. Dotted paths work. |
| `help` | `""` | Passed to every helper. |
| `funnels` | all three | **Set this to your own funnel in a funnel-specific module**, e.g. `funnels=(FUNNEL_RETIRED,)`. A question asked by two funnels lists both. |
| `group` | `""` | Required in practice — `validate()` rejects a blank one. It is the `input_card` title. Reuse a `GROUP_*` constant to add to a common card, or introduce your own; your own cards sort after the common ones. |
| `group_rank` | `0` | **The order of your cards.** Every question on a card repeats its card's rank — `validate()` rejects a card carrying two. Leave gaps of 10. A card left at `0` falls back to sorting by title, which is a trap: a title is prose, prose gets rewritten, and the fallback is case-sensitive. Declare a rank. |
| `order` | `0` | Within the group. Leave gaps of 10. |
| `when` | `None` | §5. |

### Methods — use these, do not reimplement them

* `q.asks(funnel) -> bool` — is it in that funnel's set at all.
* `q.applies(h) -> bool` — **both** gates: the household's funnel asks it *and*
  `when` passes. This is what the renderer checks.
* `q.target(h)` — the object to write into, walked from the Household. Returns
  `None` when a hop is missing (unmarried household, no spouse). **A `None`
  target means do not render.**
* `q.widget_kwargs() -> dict` — exactly the keyword arguments this question's
  helper accepts, and only the ones that were set. Splat it.

---

## 4. The widget-kind vocabulary

Seven kinds. **Each one is exactly a function in `ui.panel` with the same
name.** There is no eighth without changing the renderer too.

| Kind | Constant | `ui.panel` helper | Extras honoured |
|---|---|---|---|
| `text` | `KIND_TEXT` | `text()` | `placeholder` |
| `integer` | `KIND_INTEGER` | `integer()` | `min_value`, `max_value`, `step` |
| `number` | `KIND_NUMBER` | `number()` | `min_value`, `max_value`, `step`, `fmt` |
| `money` | `KIND_MONEY` | `money()` | `min_value`, `max_value`, `step` |
| `pct` | `KIND_PCT` | `pct()` | `min_value`, `max_value`, `step`, `decimals` |
| `toggle` | `KIND_TOGGLE` | `toggle()` | — |
| `choice` | `KIND_CHOICE` | `choice()` | `options` (required), `format_func` |

Setting an extra that the kind does not honour is silently dropped by
`widget_kwargs()`, so it will not crash — it will just not do anything. Check
the table.

**`pct` stores a decimal and displays a percent.** `pct()` multiplies by 100 on
the way out and divides on the way back in, so `min_value`/`max_value`/`step`
are in *percent* (`0.0`–`100.0`) while the stored field is `0.0`–`1.0`. This
matches `member.tsp_contribution_pct`. Note that `Assumptions` fields are the
other way round — they are stored **in percent** (`4.0` means 4%) and must use
`KIND_NUMBER`, not `KIND_PCT`.

**Lists are out of scope.** Debts are a `data_editor`, not a scalar widget.
Do not try to express one as a `Question`; render it separately.

**Never put two `$` in a `label`, `help` or `placeholder`.** Streamlit parses
the text between a pair of unescaped dollar signs as LaTeX and silently eats
both signs. `help` is handed straight to the widget, so it cannot be escaped at
render time — it has to not need escaping. Write "50,000 dollars", spell the
figure, or split the two amounts across separate sentences. `validate()`
rejects it. One `$` on its own is fine.

### The renderer, in full

Every page renders a `Question` this way and no other way:

```python
import ui.panel as panel
from ui.panel import wkey, input_card
from engine.intake import prepare, questions_to_ask, grouped

prepare(h)
for title, qs in grouped(questions_to_ask(h)):
    with input_card(title):
        for q in qs:
            getattr(panel, q.kind)(q.label, q.target(h), q.attr,
                                   key=wkey(q.key), **q.widget_kwargs())
```

The helpers call `mark_dirty()` and `invalidate()` themselves when the value
changes. That is the whole reason to go through them.

---

## 5. Conditional questions

`when` is a predicate on the Household. It must be **pure** — no writes, no
Streamlit calls, no `st.session_state`.

```python
from engine.funnel import has_spouse, is_deployed

Question(key="srv_deployed_months",
         label="How many months have you been deployed this year?",
         kind=KIND_INTEGER, path="member", attr="months_deployed_this_year",
         group="Deployment", order=20, funnels=(FUNNEL_SERVING,),
         when=is_deployed, min_value=0, max_value=12)
```

Shared predicates already in `engine.funnel`: `has_spouse(h)`, `is_deployed(h)`.
Write your own as a module-level named function — not a lambda — so a failure
names something.

**The spouse trap.** Nothing in the app has ever created `Household.spouse`; it
is `None` on every plan. `has_spouse(h)` therefore checks *both* `h.has_spouse`
and that the record exists. `prepare(h)` creates it for a married household.
**Call `prepare(h)` once at the top of the page, before evaluating any
`applies()`.** `visible_questions()` also drops any question whose `target(h)`
is `None`, so a missed `prepare()` hides the spouse questions rather than
crashing — but it hides them wrongly.

---

## 6. How a funnel module registers its questions

The entire contract is one line:

```python
# engine/intake/retiree.py
QUESTIONS: tuple[Question, ...] = (...)
```

A module-level tuple of `Question`, every one carrying `funnels=(FUNNEL_X,)`
for its own funnel. **No registration call, no import-time side effects, no
mutable global registry.** `engine/intake/__init__.py` imports the module by
name from `MODULES` and reads `QUESTIONS` off it.

* The three modules are `engine/intake/serving.py`, `veteran.py`, `retiree.py`.
  The names are fixed by `MODULES`.
* A module that does not exist yet contributes nothing and the common set
  still renders. A module that exists and is **broken** raises — a silently
  empty funnel is the worse failure.
* Your module may import from `engine.funnel`, `engine.profile`, `engine.pay`,
  `engine.mortality` and so on. It must **not** import `streamlit`, `ui.panel`
  or `engine.intake`.

Add a test that your set is clean:

```python
from engine import intake
from engine.funnel import validate, FUNNEL_RETIRED

def test_the_retiree_set_validates():
    assert validate(intake.all_questions(FUNNEL_RETIRED)) == []
```

`validate()` catches: duplicate keys, unknown kinds, a `choice` with no
options, a funnel key that does not exist, a label that does not end in `?` or
does not open with a question word, a `$` pair in any user-visible string, a
missing group, a card carrying two different `group_rank` values within one
funnel, and an `attr` that does not exist on the object `path` resolves to.

Two funnels **may** reuse a card title and rank it differently — only questions
that render together have to agree. "Leaving the service" is rank 70 for
someone serving (a date they have not picked) and rank 10 for a veteran (the
DD-214).

### What the common set already asks — do not ask it again

`engine.funnel.QUESTIONS`, sixteen questions in six groups:

| Group | Fields |
|---|---|
| About you | `member.birth_year`, `member.sex` |
| Your household | `has_spouse`, `spouse.birth_year`, `n_dependents` |
| Where you live | `state_of_legal_residence`, `current_state` |
| What you have saved | `member.tsp_traditional_balance`, `member.tsp_roth_balance`, `member.ira_traditional_balance`, `member.ira_roth_balance`, `taxable_brokerage`, `cash_savings` |
| What you spend | `monthly_expenses`, `essential_monthly_expenses` |
| When you stop working | `target_retirement_age` |

The group constants are `GROUP_ABOUT`, `GROUP_HOUSEHOLD`, `GROUP_WHERE`,
`GROUP_BALANCES`, `GROUP_SPENDING`, `GROUP_PLAN`, ordered by `GROUP_ORDER`.

Per `ARCHITECTURE.md` §5, the funnel-specific sets are roughly:

* **serving** — DIEMS date (first; it decides the retirement system and nothing
  else does), grade, years of service, date of rank, duty ZIP,
  dependents-for-pay, government housing, TSP contribution % and Roth share,
  deployment and combat-zone months, SGLI, planned separation, promotions,
  GI Bill.
* **veteran** — separation date, years served, VA rating and P&T, GI Bill
  remaining, VGLI vs term, civilian employer plan.
* **retiree** — retired pay gross, retirement system, SBP elected and level,
  VA rating, CRDP/CRSC, TRICARE plan.

---

## 7. Session state and `wkey()`

* **Every widget key goes through `wkey()`. No exceptions.** `wkey()`
  namespaces a key to the loaded plan version; without it Streamlit's sticky
  widget state survives a plan load and silently shows the previous plan's
  numbers. `wkey(q.key)` — never `q.key` raw, never an f-string you build
  yourself.
* **`Question.key` is a stem, not a key.** It must be unique across all four
  question sets. Prefix: `q_` common, `srv_`, `vet_`, `ret_`.
* **The Household is the state.** It lives in `st.session_state["household"]`
  and is mutated in place, so a change on one page is visible on every other.
  `get_household()` from `ui.panel`. Do not keep a second copy of any answer in
  `st.session_state` — that is exactly how the Career timeline got lost
  (§4a).
* **Writes go through the `ui.panel` helpers.** They call `mark_dirty()` and
  `invalidate()`. Assigning `h.field = value` directly skips both, leaves the
  plan looking saved and leaves cached results stale — the live defect in
  `pages/10_Residency_and_Education.py`. If you must assign directly (choosing
  the funnel is the one real case), call `mark_dirty()` and `invalidate()`
  yourself:

  ```python
  from ui.panel import mark_dirty, invalidate
  from engine.intake import set_funnel

  if st.button(f.label, key=wkey(f"pick_{f.key}")):
      set_funnel(h, f.key)
      mark_dirty(); invalidate()
      st.rerun()
  ```

  `set_funnel()` is a pure engine function and holds no Streamlit state. It
  will not do this for you.
* Engine modules never import `streamlit`. Keep it that way.

---

## 8. The house rules that are not negotiable

From `HANDOFF.md`. Each was paid for.

1. **Every widget key through `wkey()`.**
2. **Labels are second-person questions.** "What year were you born?", not
   "Birth year". Assumption inputs are phrased as assumptions the user is
   choosing — "How long do you expect to live?" — because a field labelled
   "Life expectancy" invites people to treat a guess as a given. Page and
   section *titles* are nouns; widget *labels* are questions. `validate()`
   enforces the question mark.
3. **`esc()` takes TEXT, `md_money()` takes a NUMBER.** Streamlit parses a pair
   of unescaped `$` as LaTeX and silently eats both dollar signs. Any prose
   containing a money figure goes through `esc()`. Passing a string to
   `md_money()` crashes the page. This has bitten three times.
4. **No `st.set_page_config` in a page.** The router owns it.
5. **The page shape.** `page_header()`, then `two_pane()`, inputs on the left
   in `input_card()`s, engine calls between the panes, results on the right.
   One widget per row. **No `st.columns` inside a card.**
6. **Findings are `(severity, headline, detail)` triples** — `good` / `warn` /
   `bad` / `info` — rendered by `render_findings()`, ordered by dollars at
   stake.
7. **Verify every rate against the publisher.** A scorecard makes a wrong
   figure more dangerous, not less, because it compresses it into a single
   reassuring letter.

---

## 9. Essential vs discretionary spending

`ARCHITECTURE.md` step 1 and §8. The income-floor component is meaningless
without the split.

```python
from engine.intake import (essential_monthly, discretionary_monthly,
                           has_essential_split)
```

* `Household.essential_monthly_expenses` — **`0.0` means "not answered", not
  "nothing is essential".** Never read the field directly.
* `essential_monthly(h)` — the answer if there is one; otherwise 75% of
  `monthly_expenses` (`DEFAULT_ESSENTIAL_SHARE`); otherwise `0.0`, because a
  guess on top of a guess is worse than a blank. The answer is clamped to the
  total — an essential figure above the total is a contradiction and letting it
  through produces a confident, wrong rating.
* `discretionary_monthly(h)` — the remainder. Never negative.
* `has_essential_split(h)` — **check this before presenting a floor rating.**
  A rating built on the fallback must say it is an assumption, not an answer.

The question is phrased as *what they could not cut*, not as a budget line:
"If your income was cut tomorrow, what would you still have to pay every
month?" Users understate the floor, and §8 says so. Keep that framing in any
copy you write about it.

---

## 10. Persistence

`Household.funnel`, `Household.essential_monthly_expenses` and
`Household.target_retirement_age` are the three new fields. They round-trip for
free: `to_dict()` is `asdict()` and `_build()` skips keys a file does not
carry.

**There is no versioned migration in this codebase.** The `schema_version`
field on `Household` is written and never read. Tolerating a missing key *is*
the mechanism. Do not add a migration step; a plan saved before this work loads
with `funnel == FUNNEL_UNSET` and `funnel_of()` resolves it. Both sample plans
in `samples/` do exactly that, and there are tests for it.

---

## 11. Rulings

Questions raised by the builders during the first pass, settled here. Each one
is a decision, not a preference — change it by changing this section.

### SBP base amount: keep the assumption, do not add the field

`ARCHITECTURE.md` §5 asks for "SBP elected and level", and `ServiceMember`
carries only `sbp_elected`. **Intake asks the election and not the level.**

It is not a gap in the model. `roth_profile.MilitaryRetirement` already carries
`sbp_base_amount_monthly` with the documented convention `0.0 means full
retired pay`, and both consumers — `retirement/projection.py` and
`briefing.py` — implement that fallback identically:

```python
base = (mil.sbp_base_amount_monthly * 12.0
        if mil.sbp_base_amount_monthly > 0 else mil_gross)
```

So the app already prices SBP on the full base, which is the usual election.
Adding `sbp_base_amount_monthly` to `ServiceMember` would change no number on
its own: `roth_bridge.py` builds `MilitaryRetirement` and does not pass a base
through, so the new field would be collected, stored, and ignored. **A field
that exists and changes nothing is worse than no field**, because it invites a
retiree with a reduced base to enter it and believe the figures.

The retiree question's help text discloses the assumption and tells the reader
to treat the survivor figures as an upper bound. That is the standard §8 asks
for: a number that states what produced it.

**Known gap, for whoever does the scorecard's survivor component.** Two lines
make it real, and they belong in one change: a `sbp_base_amount_monthly` field
on `ServiceMember`, and passing it at `roth_bridge.py:485` where `sbp_elected`
is already passed. Then add the question and drop the assumption from the help.

### Card order is declared, not inferred from the title

All three funnel modules independently chose card titles to force an
alphabetical order and each warned in its docstring that renaming a card would
silently reorder the page. That is the right instinct about the wrong
mechanism. `group_rank` is the fix — see §3. The title fallback still exists
for a card that declares nothing, and it is still a trap, so declare a rank.

### The label rule is enforced, and the format hint moves to `help`

The contract said `validate()` enforced "starts with a question word" and it
did not. It does now. The existing app label `"What is your DIEMS date?
(YYYY-MM-DD)"` fails the trailing-`?` rule, which is correct and is why intake
asks `"What is your DIEMS date?"` and puts the format in the help text. The
older pages are not being swept for this; the rule binds new questions.

---

## 12. What this is for

A form is not the point. `ARCHITECTURE.md` is explicit that the app assesses
**readiness to retire**, and every question here earns its place by feeding a
scorecard component or explaining one:

| Question | Feeds |
|---|---|
| essential vs total spending | **1 Income floor** — the component is meaningless without the split |
| balances, target retirement age | **2 Funded ratio**, **3 Longevity** |
| traditional balances, DIEMS → retirement system, Part B | **4 Tax position** — RMDs, and the conversion window IRMAA closes |
| TRICARE plan, health cost, VA rating | **5 Healthcare** |
| spouse, SBP, VA P&T | **6 Survivor** |
| cash, debts, spending | **7 Liquidity & debt** |
| children, legacy intent | **8 Legacy** |

If a question you are about to add does not appear in that table, it needs a
reason to exist that is better than "the old page asked it".
