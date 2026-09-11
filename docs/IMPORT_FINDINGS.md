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
