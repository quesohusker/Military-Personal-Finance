# Military Personal Finance — handoff

Everything a new session needs to pick this up. Read this before touching
anything; several of the conventions below were arrived at the hard way and
look arbitrary until you know what broke.

**Repo** `github.com/quesohusker/Military-Personal-Finance` (public)
**Entry** `Military_Finance.py` — the router, not a page
**Stack** Streamlit 1.63, pandas, numpy, altair, pypdf. Local JSON only, no server, no database.
**State** 21 pages, 42 engine modules, ~29,000 lines, **940 tests, all passing**
**Deploy** Streamlit Community Cloud, auto-deploys on push to `main`

---

## Who this is for

Active-duty first, retirees on the same machinery. It exists because military
compensation does not behave like a salary and every civilian planning tool
gets it wrong in the same four places:

1. **BAH and BAS are untaxed.** The E-5 sample is paid $84,815 and shows
   $20,550 in box 1. Seventy-six percent never reaches a tax return.
2. **The TSP match only exists under BRS.** "Always get the match" is advice
   that does nothing for a High-3 member. The DIEMS date decides, and nothing
   else does.
3. **An HSA is not available on active duty.** TRICARE is not a
   high-deductible plan, so the step every civilian priority list ranks above
   maxing retirement simply does not exist.
4. **A deployment is the highest-leverage financial window in a career.**
   SDP pays a guaranteed 10%, and CZTE can make a year nearly tax-free.

The owner is Paul Dalen — retired Army officer, 22 years, REDUX, ~100% VA,
retiring from USAA on 31 Mar 2027. He built this partly for an Army friend, a
retired LTC at 26 years, 100% P&T, who believed his RMD exposure was "almost
nothing." That is still the app's central case.

---

## House style — non-negotiable, and every page follows it

Read `pages/1_Profile.py` and `ui/panel.py` before writing a page. Copy them.

```python
h = get_household()
page_header("🎖️ Title", "One-sentence subtitle.")
inputs, results = two_pane()          # narrow left, wide right
with inputs:
    with input_card("A short prompt"):
        ...one widget per row, NO st.columns inside a card...
# engine calls go HERE, between the panes
with results:
    ...section(), metric_row(), render_findings(), charts...
```

- **Every widget key goes through `wkey()`.** It namespaces the key to the
  loaded plan version. Without it, Streamlit's sticky widget state survives a
  plan load and silently shows the previous plan's numbers.
- **Labels are second-person questions.** "What year were you born?", not
  "Birth year". Assumption inputs are phrased as assumptions the user is
  choosing — "How long do you expect to live?" — because a field labelled
  "Life expectancy" invites people to treat a guess as a given.
- **`esc()` takes TEXT, `md_money()` takes a NUMBER.** Streamlit parses a pair
  of unescaped `$` as LaTeX and silently eats both dollar signs. Any prose
  containing a money figure must go through `esc()`. Passing a string to
  `md_money()` crashes the page. This has bitten three times.
- **No `st.set_page_config` in a page.** The router owns it.
- Findings are `(severity, headline, detail)` triples — `good` / `warn` /
  `bad` / `info` — rendered by `render_findings()`, ordered by dollars at stake.

## Menu structure

Organised around **who a page is for**. Most of personal finance does not care
whether you are in uniform, so `General` holds the pages everyone uses and the
three status groups hold only what is genuinely particular to that status.

`General` · `Currently Serving` · `Veteran` · `Retiree`

**Titles are nouns.** The title says the subject, the subtitle says the
question — a sidebar of full sentences is slow to scan, and the eye should
land rather than read. This does not touch the label rule above: widget labels
are inputs and stay second-person questions.

The earlier menu grouped by event — `Where I stand`, `Decisions I make now`,
`When I get orders` — on the argument that nobody wakes up wanting a "benefits
module". That rationale is superseded. `docs/REORGANIZATION.md` has the full
reasoning, the old-to-new title map, the filing rule for a page that fits two
groups, and the recorded objection that status groups overlap and `General`
ends up holding 13 of the 23 pages.

Titles are not confined to the router: they appear as prose cross-references
in about forty places, and a missed one is silent — nothing crashes, the user
is just sent to a page name that is not in the sidebar. Sweep a rename by
grepping the exact old title, never a fragment; "money invested" and "keep the
house" also occur as ordinary prose.

`st.navigation(MENU, expanded=True)` — past ten pages Streamlit folds the tail
behind a "View 3 more" button, and the group it hid was the retiree one.

---

## Streamlit traps this project has already paid for

| Trap | What happens | Fix |
|---|---|---|
| Sticky widget keys | A loaded plan shows the previous plan's values | `wkey()` versioning |
| `$` pairs in markdown | Rendered as LaTeX, dollar signs vanish | `esc()` on all money prose |
| `.block-container` top padding | Below ~60px, every page title renders *under* the opaque fixed toolbar and looks clipped | keep ≥ 4.5rem |
| Dead CSS selectors | 1.63 dropped `stVerticalBlockBorderWrapper` and all `data-baseweb` attributes; rules silently do nothing | verify in the browser, not by reading |
| `alt.Axis(format=None)` | Invalid in Altair 6 | `alt.Undefined` |
| Module edits not reloading | Streamlit does not reliably reload imported modules | restart the server, don't trust a rerun |
| Browser refresh | Session state dies, loaded plan is gone | expected; tell users to re-upload |

## Verification discipline — this is the part that matters

**Unit tests do not catch page bugs.** Every page-level defect in this project
was found by driving a real browser, never by pytest. Do this after any UI
change:

1. Start the app, then drive every page in headless Chromium
   (`/opt/pw-browsers/chromium`, Playwright is installed).
2. Fail on a traceback **and on any `.katex` node** — a KaTeX element means
   prose got parsed as LaTeX and a dollar figure was eaten silently.
3. Do it with both sample plans in `samples/`, because the two exercise
   different branches almost everywhere.

**Verify figures against the publisher, never from memory.** This has caught
errors repeatedly — including mine. The importers refuse to install a table
that fails shape checks (senior grades must out-earn junior, remaining years
must fall as age rises, female life expectancy must exceed male), because a
column shifted by one parses perfectly and produces plausible, wrong numbers
for every user.

---

## Sourcing rates: the .gov problem

**This container cannot reach any `.gov` or `.mil` host.** Every rate was
first written from recollection, then checked. See `docs/VERIFIED.md` for the
full record — 21 figures confirmed, 14 corrected, each with the file and
SHA-256 it was read from.

`scripts/fetch_gov_data.py` fetches 39 sources and archives every raw
response. Paul runs it on his Mac (`bash scripts/fetch.sh`). Results:

- **IRS, VA, TSP, CMS, FHFA** — fetch cleanly.
- **SSA, DFAS, DTMO** — 403 to everything. Akamai bot filter; neither full
  browser headers nor curl's different TLS handshake gets past it. **Browser
  save only.** Use **Save As → Page Source** (their tables live in the markup).
- **TRICARE** — returns a 6,803-byte JavaScript shell to any fetch. **Print to
  PDF**, because Save As gets the same empty shell.

The script refuses a 200 that carries nothing — too small, too digit-free,
says "enable javascript", or byte-identical in size to another page in the
same run. A response that arrives looking fine and carries nothing is more
dangerous than one that fails loudly, because nobody goes back to check it.

### What checking actually found

Worth knowing, because it calibrates how much to trust an unverified figure:

- **TRICARE Select Group B enrolment** was carried at $199/$398. Real:
  **$594.96/$1,191** — about a third of the true cost.
- **`engine/tax/tables.py` had last year's Part D IRMAA.** The 2025 amounts
  re-derive exactly from a 2025 base premium, which is how the staleness
  showed up. Both numbers looked plausible.
- **TSP expense ratios were all overstated** — G is 0.034%, not 0.057%.
- **The I Fund excludes China and Hong Kong.** The description said "outside
  the US and Canada", which described the *old* index it stopped tracking in 2024.
- **Two figures the agents refused to defend turned out exact**: the SSA bend
  points ($1,286 / $7,749) and BAS ($476.95 enlisted / $328.48 officer).
  Self-assessed confidence ran pessimistic where the work was careful.

---

## The finding that changed an answer

Installing the real SSA life table moved the retired-O-5 sample's death age
from 86 to 87. **That single year moved the Roth conversion advantage from
$28,954 to $43,482** — a longer life means more RMD years, and more RMD years
is precisely what leaving a traditional balance alone costs you.

Two regression tests failed on install, which is what they were for. Anyone
telling you conversions "don't pencil out" has a life expectancy assumption
doing more work in that answer than they realise.

---

## What is built

**Ingest** — DFAS LES and Retiree Account Statement; bank and brokerage
statements (PDF/CSV/text). Both propose, never apply: every figure shows the
raw line it came from and a confidence, and the user ticks what to accept.
Neither has ever seen a real document — DFAS is a `.mil` host. **Paul's first
real upload is the actual test.**

**Pay** — basic pay, BAH by ZIP (40,959 ZIPs, 338 MHAs), BAS, drill pay,
taxable/untaxed split. Convention: housing + utilities run **105% of BAH**.

**Decisions** — Roth conversion (two futures, paired-path Monte Carlo, bracket
sweep, LLM briefing export), the priority waterfall, debt avalanche/snowball
with the SCRA 6% cap, state of legal residence, GI Bill use vs transfer.

**Retirement** — all four systems, the 20-year cliff, the BRS lump-sum trap,
TSP limits and the combat-zone overflow, Social Security claiming 62–70.

**Leaving** — Chapter 61 vs severance, terminal leave vs selling it, SGLI →
VGLI vs term, SBP priced honestly, CRDP vs CRSC after tax.

**Money** — net worth including the pension's replacement cost, healthcare
with IRMAA, housing and the VA loan, estate and gifting, TSP allocation.

## What is not built

- **A lifetime year-by-year cash-flow projection.** The spine that would tie
  all of the above together. The Roth engine does the retiree half; it needs
  the active-duty years in front of it. **This is the biggest remaining gap.**
- PCS/PPM move profit; Guard/Reserve points and TRS detail; student loans and
  PSLF; expense tracking from transaction CSVs; dual-military specifics.

## Open items

- **Date of Rank.** Paul asked to "change to What is your Date of Rank?" while
  pointing at the years-of-service field. Those are different things —
  years-of-service drives longevity pay and the retirement multiplier — so I
  asked which he meant and he dismissed the question. **Still unresolved; ask
  before touching it.**
- The Roth engine overstates a deployed member's wages: it uses taxable pay
  *before* the combat-zone exclusion, so the E-5 sample is modelled at the
  full $49,320 despite 7 months in the zone. It is an editable input, but the
  help text does not say so.
- `data_editor` column headers are still noun labels, not questions — they
  double as the DataFrame keys the save loops read back, so renaming them
  changes code, not labels.
- Annual refresh each January: DFAS pay tables and the DTMO BAH archive.
  Neither host will ever serve an automated request.

---

## Working with Paul

Direct, concise, no preamble. He wants to be corrected rather than flattered,
and he is right often enough that it is worth checking before you assume he
is wrong — but not always. When he pointed at a years-of-service field and
asked for Date of Rank, asking was correct. When my brief had BAS backwards,
the agent that trusted the repo over my prompt was correct.

State disagreement plainly with the reason. Skip the closing "let me know if
you'd like more". Lead with the answer.
