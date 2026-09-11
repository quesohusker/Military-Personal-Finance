# What the importers did against real documents

**Status: diagnosed, not fixed.** PDF import was deprioritised right after
this test. Nothing here is built. It is written down because the finding
is the expensive part and it took a real document to get it.

`HANDOFF.md` has said from the start that neither importer had ever seen
one, because DFAS is a `.mil` host no build container can reach, and that
the first real upload would be the actual test. That test happened: one
DFAS Retiree Account Statement, three Fidelity investment reports, one
USAA checking statement.

**Four of the five were read wrongly. Three of those looked like
success.**

> **The documents are not in this repository and must never be.** It is
> public and they are a real person's pay and accounts. Everything below
> is structure with the figures removed. Any fixture built from this must
> reproduce the *layout* with fabricated values.

---

## The worst one: a 401(k) filed as a taxable brokerage

Two of the statements are Fidelity **BrokerageLink** windows inside an
employer Retirement Savings Plan — a 401(k). One pre-tax, one Roth. The
heading of the second says so outright:

```
BROKERAGELINK ROTH                 FMTC - TRUSTEE - <SPONSOR>
RSP FOR THE BENEFIT OF <NAME>
Account Number: ...
Your Account Value: $...
Ending Account Value ** $... $...
<SPONSOR> RSP - NON-PROTOTYPEAccount Summary
```

Both were proposed as `taxable_brokerage`, at high confidence, with a
reassuring note that the same figure appeared twice.

**This is the most damaging failure this module can produce**, and not
because of the dollar amount. The taxable / pre-tax / Roth split is the
single most important thing downstream consumes:
`engine/retirement/projection.py` computes RMDs and heir tax off the
pre-tax balance, `engine/scorecard/components.py` rates tax position on
it, and the app's central case — the retired LTC who believed his RMD
exposure was "almost nothing" — is exactly this number. Six figures of
pre-tax money in the taxable bucket produces a confident, precise, wrong
answer about the one thing the app exists to get right.

The vocabulary that should have decided it: `BROKERAGELINK`, `RSP`,
`RETIREMENT SAVINGS PLAN`, `NON-PROTOTYPE`, `FOR THE BENEFIT OF`,
`FMTC - TRUSTEE -`, `401(K)` all mean retirement; `ROTH` qualifying any
of them flips pre-tax to Roth; `TOD`, `INDIVIDUAL`, `JOINT` mean taxable.

**And there is nowhere right to put it.** The Household carries
`tsp_traditional_balance`, `tsp_roth_balance`, `ira_traditional_balance`,
`ira_roth_balance`, `taxable_brokerage` and `cash_savings`. A civilian
401(k) is none of them. Whatever is built here has to either add a home
or refuse honestly — quietly choosing the nearest field is how this
defect happened.

## A two-account statement collapsed into one

```
FIDELITY ACCOUNT <NAME> - INDIVIDUAL TOD <acct>   $...   $...
FIDELITY ROTH IRA <NAME> - ROTH INDIVIDUAL RETIREMENT
...
<NAME> - INDIVIDUAL - TODAccount Summary
Ending Account Value $... $...
...
<NAME> - ROTH IRAAccount Summary
Ending Account Value $... $...
```

A taxable TOD account and a Roth IRA, on one statement. The parser
returned **one** candidate, labelled it `Brokerage (ROTH)`, suggested
`ira_roth_balance`, and warned that "two different figures were found for
what looks like the same account".

They are not the same account. A multi-account statement must yield one
candidate per account. Note the section headings glue the account name
onto the section title with no space — `...- TODAccount Summary` — so the
boundaries are findable but naive splitting fails.

## Institution detection keys on any brand string

Two Fidelity statements reported as the plan sponsor's name, because
`FMTC - TRUSTEE - <SPONSOR>` appears in the header. The custodian is
stated plainly on the same page — `Brokerage services provided by
Fidelity Brokerage Services LLC` — and the document titles itself
`INVESTMENT REPORT`.

Custodian and sponsor are different facts and flattening them into one
"institution" loses the distinction that matters.

## Statement date missed on every Fidelity statement

The period is prose: `August 1, 2026 - August 31, 2026`. A compact
`YYYYMMDD` also appears in a mailing code. Found correctly on the USAA
statement, so the gap is format coverage.

---

## The RAS: the bounds check earned its keep

Detection was right — `DOC_RAS`, high confidence, eight markers. Reading
was not.

### The pay table is two column-pairs, side by side

```
 ITEM                    OLD          NEW      ITEM           OLD      NEW
 GROSS PAY               .00     4,XXX.XX      FITW           .00   XXX.XX
 SBP COSTS               .00       XXX.XX      ADDL FITW      .00   XXX.XX
 TAXABLE INCOME          .00     3,XXX.XX
                                               NET PAY        .00 3,XXX.XX
```

One physical line carries **two unrelated items**, each with an **OLD**
and a **NEW** value. `GROSS PAY` therefore sits on a line holding four
numbers, and the parser took the last — the federal withholding.

`RANGE_RETIRED_PAY` rejected it as implausible, marked it suspect and
offered nothing. **No wrong figure reached the plan.** That is the
"refuse what fails shape checks" discipline from HANDOFF working exactly
as designed, and it is the reason this test produced a diagnosis rather
than a corrupted plan.

The rules needed: split a line into item blocks at the second `ITEM`
label; within a block take the **NEW** column, not the last number on the
line; treat `.00` in OLD as "no previous value" rather than a real zero.

### When CRDP is in force there is no VA WAIVER line at all

The parser reported `VA compensation (the VA waiver)` as missing. It is
not missing — it is **structurally absent**. For a concurrent-receipt
retiree the pay items carry no waiver, and the only related figure is in
prose in the message section, in a sentence that wraps across three lines
with the amount starting the third.

**That figure is the CRDP amount, which is restored retired pay. It is
not the VA compensation figure and must never be written into
`va_disability_monthly`** — CRDP is taxable and VA compensation is not,
so the error would put a taxable figure into a tax-free field and
understate the tax bill everywhere downstream.

Whether the VA amount can be derived at all from a RAS under concurrent
receipt is an open question worth settling before anyone codes this.

### An entire SBP section is ignored, and it holds a field recorded as unobtainable

```
 SURVIVOR BENEFIT PLAN (SBP) COVERAGE

  SBP COVERAGE TYPE:   SPOUSE ONLY      ANNUITY BASE AMOUNT:   $...
  SPOUSE ONLY COST:          $...

 THE ANNUITY PAYABLE IS 55% OF YOUR ANNUITY BASE AMOUNT WHICH IS $...
 YOU HAVE BEEN CHARGED NNN MONTHS TOWARD YOUR 360 MONTHS OF PAID UP
 RC/SBP COVERAGE.
```

`ARCHITECTURE.md` and `FUNNEL_CONTRACT.md` both record
`sbp_base_amount_monthly` as a known gap, on the reasoning that nothing
supplies it so a field would collect an answer that changes no number.

**The RAS supplies it**, along with the coverage type and the
months-paid-of-360 clock that `roth_profile.MilitaryRetirement.sbp_paid_up`
exists for. Those notes should be revisited when this is picked up.

### A cross-check that holds and is not used

`TAXABLE INCOME` = `GROSS PAY` − `SBP COSTS`, exactly. It is free
validation of the two-column reading, in the same spirit as the existing
`cross_check_grade_and_pay`.

### Also present and unread

Statement effective date, next pay date, federal withholding status,
total exemptions, year-to-date taxable income and federal tax withheld,
and an arrears-of-pay beneficiary table. Worth taking selectively — the
withholding status earns its place, a beneficiary's name does not.

---

## The one that was right

The USAA checking statement: `Beginning Balance $...`, `Ending Balance
$0.00`. Read correctly, suggested `cash_savings`, and hedged honestly —
"the balance read as zero: a closed or empty account, or a misread."

Keep that behaviour. It should be the first regression fixture anyone
writes here.

---

## How to reproduce without the documents

`scripts/diagnose_upload.py` prints what either parser makes of a file —
which labels it keyed off, what it found, what it went looking for and
missed, what it rejected — **with figures, account numbers and raw lines
masked**. That output is safe to paste into a conversation. `--show-values`
opts back in.

## The standing lesson

Three of the four failures returned a plausible number with high
confidence. Only the RAS failed loudly, and only because a bounds check
refused a figure outside its range.

**Confidence in this module is a claim about a label match, not about
correctness.** Every future change here should assume the parse is wrong
until a cross-check says otherwise, and should prefer refusing to
guessing — a missing figure is an inconvenience, a wrong one in the
pre-tax bucket is a wrong answer about the whole plan.

---

# Latent bugs, independent of PDF import

Found while diagnosing the above, but **none of these needs a document to
bite.** They are ordinary defects in code that ships today. Recorded
separately because they should be judged on their own merits, not bundled
with the deprioritised import work.

Ordered by how much damage each does.

## 1. Years of service can be read wrong, at HIGH confidence, and preselected

`engine/ingest/les.py::_read_yos` searches the sliced `YRS SVC` cell with
an unanchored `\d{1,2}(?:\.\d)?` and no digit-boundary guard. `PAY DATE`
and `ETS` are both YYMMDD and both sit beside `YRS SVC` on the form, so a
slice that picks up an adjacent date matches its leading two digits:
`200612` yields **20 years**.

Every guard in the module is defeated by a value that is wrong but
ordinary. Twenty is inside `RANGE_YOS`, so bounds pass. The column path
returns HIGH, so **the box is ticked by default**.
`cross_check_grade_and_pay` may not fire, because twenty years against a
mid-career grade is entirely plausible.

Years of service drives basic pay, the retirement multiplier, the
twenty-year cliff and the Social Security earnings history. The fix is
small: forbid the match being embedded in a longer digit run, and prefer
requiring it to be the whole cell.

## 2. A combined statement containing a credit card returns zero assets

`engine/ingest/statements.py` computes `doc_is_card` from a regex over the
**whole document** (`minimum payment due|payment due date|credit limit|
available credit`), and the section loop then rejects **every** section
when it is true.

Reproduced on invented text: a statement with a checking account and a
Visa below it returns **no accounts and two rejections**, the checking
balance rejected as "money owed". Combined checking-savings-card
statements are routine at USAA and Navy Federal.

The gate is also inconsistent — the `_summary_table` path ignores
`doc_is_card` entirely, so the same document read via a summary table
*does* return assets. A document-level flag should drive a warning;
rejection belongs at section level, which already works correctly.

## 3. The page can apply a value to a mismatched target

The candidate row lets the user pick any figure from `all_values()` — the
best reading plus every alternate — while the target selectbox stays
bound to the *candidate's* target. After a bad merge the alternates
belong to a different account with a different tax treatment, so choosing
the Roth figure applies it to the taxable-brokerage field.

The value and the target come from different accounts by design.
Alternates need to carry their own target, or changing the figure must
reset the target.

## 4. `exclude` patterns are matched against the whole physical line

`_PERIOD_NOISE` contains a bare `\bTOTAL\b`. On any multi-column layout —
the three-column LES as much as the two-pane RAS — the word `TOTAL`
appearing anywhere on a row suppresses **every** item on that row, and
each field is then reported as "not found".

It fails safe, so it under-reads rather than mis-reads, but it is a large
part of why a real document comes back emptier than it should. Excludes
belong on the item, not the row.

## 5. `detect_institution` resolves ties by list order, not document position

It scans a window, then iterates `INSTITUTIONS` **in list order** and
returns the first pattern matching anywhere in it. Position in the
document is irrelevant, so the list order is an undeclared priority.

This alone explains the two misreported statements — no sponsor reasoning
needed. Custodian boilerplate ("Brokerage services provided by X",
"Securities offered through X", "clearing through X") is compliance
language with limited phrasings and deserves near-certain weight;
position should be the tiebreak.

## 6. `_money_tokens` has two parsing faults

**It cannot parse a leading-dot amount.** The regex requires a leading
digit, so `.00` matches as `00`. The value is right by accident but the
token's start offset lands one character late, which corrupts every
`label = segment[:tok.start]`. It also makes `.00` indistinguishable from
a real `0.00` — and that is the mechanism by which the whole SBP section
came back empty, because `_read_sbp` does `if premium <= 0: continue` and
walked past the election flag as well as the cost.

**It treats any digit run as money.** A six-digit `PAY DATE`, a five-digit
ZIP, a four-digit year and a three-digit exemption count are all
"money". `_scan_rule` is incidentally protected because it takes the
first token *after* a matched label; `_entitlement_rows` is not, so a
remarks line carrying a date or a ZIP can enter the special-pay sum.
`_NOT_SPECIAL_PAY` is a blocklist of *labels* and cannot catch this by
construction.

## 7. `detect_statement_date` requires the label on the same line

`Statement Period August 1, 2026 - August 31, 2026` resolves; the same
content split across two lines returns empty. A period printed below its
label is an extremely common layout. Separately, `_DATE_CONTEXT_RX`
includes a bare `ending`, which matches `Ending Balance`, so a date on a
balance line can be adopted as the statement date.

## 8. A label followed by two unequal amounts takes the first, unhedged

`Ending Account Value $100.00 $900.00` yields `100.00` at 0.92
confidence. On the statements tested the two columns happened to be
equal, so it read correctly **by luck**. A statement whose columns are
prior-period / this-period would silently import the prior period at high
confidence.

The summary-table path reasons carefully about which column is the ending
one; the label-and-values path does not reason about columns at all.

## 9. Two small ones

`_is_heading` excludes any line containing `your`, so `Your Portfolio` is
rejected; `Your Account Value` survives only incidentally because
`account` short-circuits first. Statements address the reader constantly.

`_pretty_markers` strips `\b` and `\s+` but leaves quantifiers, so the
recognised-markers caption prints `SBP COSTS?` — the trailing `?` is the
optional-`S` quantifier, not punctuation. Cosmetic, but it is the one
place the page shows parser internals to a user being asked to trust the
parser's judgement.

---

# If this is picked up again

Two design conclusions were reached before the work stopped. Both are
worth more than the code that would have implemented them.

## Tax treatment is a second axis, not a flavour of account kind

The statement parser has one axis, `account_kind` (checking / savings /
brokerage). That answers "what sort of product is this", which is not
what the plan needs. The plan needs **taxable, pre-tax, or Roth** — and
the two are orthogonal, because a brokerage account can be any of the
three.

Precedence that was settled on: liability first and unconditionally; then
*is this a retirement wrapper at all* (`BROKERAGELINK`, `RSP`,
`NON-PROTOTYPE`, `FOR THE BENEFIT OF`, `FMTC - TRUSTEE -`, `401(K)`,
`TSP`, `IRA`, `ROLLOVER`); then `ROTH` as a **modifier** on that wrapper,
never as a standalone classifier — the current code tests a bare
`\broth\b` first, which is why the word wins wherever it lands; then
taxable markers (`TOD`, `INDIVIDUAL`, `JOINT`); then non-retirement
tax-advantaged (`529`, `HSA`, `UTMA`).

Identity for merging: **account number, else heading text, else tax
classification.** Two candidates pointing at different tax buckets are by
construction not the same account, and `same_kind_unnumbered` — which
asserts identity from the *absence* of evidence — should be deleted.

## The VA compensation figure cannot be derived from a RAS

Under concurrent receipt the arithmetic is
**CRDP ≤ waiver ≤ VA compensation**. CRDP is capped at the longevity
portion of retired pay; the waiver equals VA compensation limited by the
retired pay available to waive.

Equality holds for an ordinary 20-year length-of-service retiree, and in
that case the CRDP figure *is* the VA figure. But a Chapter 61 disability
retiree, anyone mid-phase-in, and anyone whose VA compensation exceeds
their gross retired pay all break it — and **the RAS prints nothing that
lets the parser tell which case it is in.** It does not print the
retirement basis or the longevity portion, and when CRDP is in force it
prints no waiver line to compare against.

So the CRDP amount honestly supports exactly two things: that concurrent
receipt is in force, and that VA compensation is **at least** that much.
It should be emitted with an empty `field` so it is structurally incapable
of being written anywhere, and the missing-VA message should say the
specific truth — *a concurrent-receipt statement carries no VA WAIVER
line, so this figure is not on the document; take it from the award
letter* — because "not found" and "not printed" are different facts.

`sbp_base_amount_monthly` should be added after all. The contract's
objection is explicitly conditional — "a field that exists and changes
nothing is worse than no field" — and names its own two-line remedy;
reading the RAS supplies the value and wiring `roth_bridge.py` supplies
the effect, so both halves land together and the objection dissolves.
Store the paid-up clock as a **count** of months, not a boolean: the
count is what the statement prints, so it is what a user can check
against the paper.
