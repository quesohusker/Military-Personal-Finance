"""
Bank and brokerage statements: pull the ENDING balance out, and nothing else.

A member who wants their cash and brokerage balances in the plan should not
have to read them off a PDF and retype them. A statement is a document they
already have; this module reads it (PDF, CSV or pasted text) and proposes
balances for the Household. It only ever PROPOSES. The page shows every
candidate with the line it came from and a confidence, the member picks where
each one goes, and nothing changes until they press Apply.

THE TRAP: a statement is full of numbers, and almost all of them are wrong for
this purpose. The opening balance. Total deposits. Each transaction's running
balance. On a brokerage statement, every holding's market value, the
year-to-date change, the cost basis. A parser that grabs "the big number near
the word balance" will confidently import last month's opening balance or a
single mutual fund's value, and the plan will be wrong in a way that looks
completely plausible. So the matching here is phrase-driven and deliberately
narrow: it looks for "ending balance", "closing balance", "total account
value" and their relatives, refuses anything qualified by "beginning",
"opening", "previous" or "change in", and when several candidates survive it
reports all of them rather than guessing. A value that is negative or absurdly
large is rejected outright rather than imported.

Every institution lays its statement out differently and this code was written
without seeing any of them. Treat every result as a suggestion to be checked
against the paper, which is why the raw line is carried alongside each number.

PRIVACY: a statement carries the member's name, address and account numbers.
The upload is read from memory and never written to disk; nothing is sent
anywhere, because this app has no server side. The raw text is not kept in the
result -- only the matched lines are, and those are masked to the last four
digits of any account number before they are stored or shown. Nothing from a
statement is written into the Household except the balances the member chose
to apply.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
import csv
import io
import re

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

KIND_CHECKING = "checking"
KIND_SAVINGS = "savings"
KIND_BROKERAGE = "brokerage"
KIND_MONEY_MARKET = "money market"
KIND_CD = "cd"
KIND_UNKNOWN = "unknown"
ACCOUNT_KINDS = [KIND_CHECKING, KIND_SAVINGS, KIND_MONEY_MARKET, KIND_CD,
                 KIND_BROKERAGE, KIND_UNKNOWN]

# Things that can appear on a combined statement and must NOT be imported as
# an asset. A credit card's "new balance" is money owed.
LIABILITY_KINDS = ("credit card", "loan", "mortgage", "line of credit")

# Where a balance can land. Each target is (object path, attribute).
TARGET_CASH = "cash_savings"
TARGET_BROKERAGE = "taxable_brokerage"
TARGET_ROTH_IRA = "ira_roth_balance"
TARGET_TRAD_IRA = "ira_traditional_balance"
TARGET_OTHER = "other_assets"
TARGET_SKIP = "skip"

TARGETS = [TARGET_CASH, TARGET_BROKERAGE, TARGET_ROTH_IRA, TARGET_TRAD_IRA,
           TARGET_OTHER, TARGET_SKIP]
TARGET_LABELS = {
    TARGET_CASH: "Cash and savings",
    TARGET_BROKERAGE: "Taxable brokerage",
    TARGET_ROTH_IRA: "Roth IRA",
    TARGET_TRAD_IRA: "Traditional IRA",
    TARGET_OTHER: "Other assets",
    TARGET_SKIP: "Do not import",
}
# (attribute owner, attribute). "household" or "member".
TARGET_FIELDS = {
    TARGET_CASH: ("household", "cash_savings"),
    TARGET_BROKERAGE: ("household", "taxable_brokerage"),
    TARGET_ROTH_IRA: ("member", "ira_roth_balance"),
    TARGET_TRAD_IRA: ("member", "ira_traditional_balance"),
    TARGET_OTHER: ("household", "other_assets"),
}

DEFAULT_TARGET_FOR_KIND = {
    KIND_CHECKING: TARGET_CASH,
    KIND_SAVINGS: TARGET_CASH,
    KIND_MONEY_MARKET: TARGET_CASH,
    KIND_CD: TARGET_CASH,
    KIND_BROKERAGE: TARGET_BROKERAGE,
    KIND_UNKNOWN: TARGET_CASH,
}

# Sanity bounds. Nothing outside these is offered, whatever the phrase said.
MIN_BALANCE = 0.0
MAX_BALANCE = 50_000_000.0

# A candidate at or above this is ticked by default on the page. Anything
# lower is shown, but the member has to opt in.
PRESELECT_THRESHOLD = 0.70

SOURCE_TEXT = "text"
SOURCE_CSV = "csv"
SOURCE_PDF = "pdf"


class StatementFormatError(ValueError):
    """The input could not be read at all (not: it was read and had no balance)."""


class PDFSupportMissing(StatementFormatError):
    """pypdf is not installed. The page tells the member to paste or use CSV."""


# --------------------------------------------------------------------------
# The result model
# --------------------------------------------------------------------------

@dataclass
class Alternate:
    """Another number that matched a balance phrase in the same account."""
    value: float = 0.0
    phrase: str = ""
    raw_line: str = ""      # masked
    confidence: float = 0.0


@dataclass
class Candidate:
    """One account the parser thinks it found. Nothing here is applied."""
    institution: str = "unknown"
    account_kind: str = KIND_UNKNOWN
    account_label: str = ""         # e.g. "Checking ****1234" -- always masked
    account_last4: str = ""
    ending_balance: float = 0.0
    statement_date: str = ""        # ISO, or ""
    matched_phrase: str = ""
    raw_line: str = ""              # masked
    confidence: float = 0.0
    target: str = TARGET_CASH       # suggested Household field
    alternates: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def preselected(self) -> bool:
        return self.confidence >= PRESELECT_THRESHOLD

    @property
    def target_label(self) -> str:
        return TARGET_LABELS.get(self.target, self.target)

    def all_values(self) -> list[tuple[float, str, str]]:
        """(value, phrase, raw_line) for the best and every alternate."""
        out = [(self.ending_balance, self.matched_phrase, self.raw_line)]
        out += [(a.value, a.phrase, a.raw_line) for a in self.alternates]
        return out


@dataclass
class Rejected:
    """A number the parser saw, matched, and refused. Shown so the member can
    see what was NOT taken and why."""
    value: float = 0.0
    phrase: str = ""
    raw_line: str = ""      # masked
    reason: str = ""


@dataclass
class ParseResult:
    source_kind: str = SOURCE_TEXT
    institution: str = "unknown"
    statement_date: str = ""
    accounts: list = field(default_factory=list)     # [Candidate]
    rejected: list = field(default_factory=list)     # [Rejected]
    warnings: list = field(default_factory=list)     # [str]
    n_lines: int = 0

    @property
    def ok(self) -> bool:
        return bool(self.accounts)

    @property
    def preselected(self) -> list:
        return [c for c in self.accounts if c.preselected]


# --------------------------------------------------------------------------
# Phrases. Confidence is the prior that a number next to this phrase is the
# closing balance of the account. Ordered strongest first; the first phrase
# to match a line wins, so put longer, more specific phrases before shorter
# ones they contain.
# --------------------------------------------------------------------------

def _rx(words: str) -> str:
    """'ending balance' -> regex tolerant of PDF extraction squashing spaces."""
    parts = words.split()
    return r"\b" + r"\s*".join(re.escape(p) for p in parts) + r"\b"


# (phrase, confidence, family). family hints the account kind when the
# heading did not say: "bank" phrases come from deposit statements,
# "brokerage" phrases from investment statements, "" is neutral.
BALANCE_PHRASES: list[tuple[str, float, str]] = [
    ("total ending balance", 0.92, "bank"),
    ("ending ledger balance", 0.90, "bank"),
    ("ending balance", 0.90, "bank"),
    ("closing balance", 0.90, "bank"),
    ("balance at end of period", 0.88, "bank"),
    ("end of period balance", 0.88, "bank"),
    ("balance as of", 0.85, ""),
    ("ending net account value", 0.92, "brokerage"),
    ("ending account value", 0.92, "brokerage"),
    ("total account value", 0.92, "brokerage"),
    ("total value of accounts", 0.88, "brokerage"),
    ("ending portfolio value", 0.90, "brokerage"),
    ("ending market value", 0.85, "brokerage"),
    ("ending value", 0.88, "brokerage"),
    ("net account value", 0.80, "brokerage"),
    ("total portfolio value", 0.80, "brokerage"),
    ("portfolio value", 0.70, "brokerage"),
    ("account value", 0.72, "brokerage"),
    ("total market value", 0.65, "brokerage"),
    ("balance on", 0.65, ""),           # Vanguard: "Balance on 03/31/2026"
    ("new balance", 0.60, "bank"),      # bank if not a card; see liability check
    ("statement balance", 0.55, "bank"),
    ("total value", 0.55, "brokerage"),
    ("total holdings", 0.40, "brokerage"),   # excludes cash; alternate only
    ("total investments", 0.40, "brokerage"),
    ("current balance", 0.45, "bank"),
]
_BALANCE_RX = [(p, c, fam, re.compile(_rx(p), re.IGNORECASE))
               for p, c, fam in BALANCE_PHRASES]

# A phrase preceded or followed (within the label) by one of these is NOT the
# closing figure, whatever else it says.
NEGATIVE_QUALIFIERS = [
    "beginning", "opening", "previous", "prior", "starting", "start of",
    "last statement", "last month", "last period", "change in", "changes in",
    "increase in", "decrease in", "average", "avg", "minimum", "maximum",
    "daily", "available", "pending", "projected", "estimated", "cost basis",
    "unrealized", "realized", "ytd", "year to date", "year-to-date",
    "required", "due", "payoff",
]
# Word-bounded: "due" must not fire inside "residue", nor "prior" inside
# "priority". Whitespace inside a qualifier is tolerant of PDF squashing.
_NEG_RX = re.compile(
    r"\b(?:" + "|".join(_rx(q)[2:-2] for q in NEGATIVE_QUALIFIERS) + r")\b",
    re.IGNORECASE)

# Money. Requires either a dollar sign or cents, so a bare "2026" or the
# "03" in a date never reads as an amount. Handles $1,234.56, 1234.56,
# (1,234.56), -1,234.56, 1,234.56-, 1,234.56 CR/DR.
_MONEY_RX = re.compile(
    r"(?<![\d/.\-])"                      # not inside a date or another number
    r"(?P<open>\()?"
    r"(?P<sign>[-−])?\s?"
    r"(?P<dollar>\$)?\s?"
    r"(?P<sign2>[-−])?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+\.\d{2})"
    r"(?P<close>\))?"
    r"(?P<trail>-|\s?(?:CR|DR))?"
    r"(?![\d/]|\.\d)"                     # 1,234.567 is a share count, not money
)

# Column-header words: a line with two or more of these is a table header,
# not a balance line, even if it says "Market Value".
_TABLE_HEADER_WORDS = ("quantity", "price", "symbol", "description", "shares",
                       "units", "cost basis", "date", "amount", "cusip",
                       "yield", "ticker")

# Account headings and kinds. Order matters: "money market savings" must be
# money market, "share certificate" a CD, before plain "savings".
_KIND_PATTERNS: list[tuple[str, str]] = [
    (KIND_MONEY_MARKET, r"money\s*market|\bmmsa\b|\bmmda\b|money\s*mkt"),
    (KIND_CD, r"certificate|\bcds?\b|time\s*deposit|term\s*share"),
    (KIND_CHECKING, r"checking|chequing|cash\s*management|\bcma\b"),
    (KIND_SAVINGS, r"savings?\b|share\s*account"),
    (KIND_BROKERAGE, r"brokerage|investment|individual\s+account|joint\s+"
                     r"(?:tenants|account|wros|with)|\bira\b|roth|401\s*\(?k\)?|"
                     r"\bsep\b|\bsimple\b|rollover|\b529\b|\bhsa\b|\butma\b|"
                     r"\bugma\b|trust\s+account|portfolio|managed\s+account|"
                     r"mutual\s+fund"),
]
_KIND_RX = [(k, re.compile(p, re.IGNORECASE)) for k, p in _KIND_PATTERNS]

_LIABILITY_RX = re.compile(
    r"credit\s*card|\bvisa\b|mastercard|american\s*express|\bamex\b|"
    r"auto\s*loan|\bloan\b|mortgage|line\s*of\s*credit|\bheloc\b|"
    r"minimum\s*payment|payment\s*due|credit\s*limit|available\s*credit",
    re.IGNORECASE)

_RETIREMENT_ROTH_RX = re.compile(r"\broth\b", re.IGNORECASE)
_RETIREMENT_TRAD_RX = re.compile(
    r"traditional\s*ira|rollover\s*ira|\bsep\b|simple\s*ira|\bira\b",
    re.IGNORECASE)
_OTHER_ASSET_RX = re.compile(r"\b529\b|\bhsa\b|\butma\b|\bugma\b|401\s*\(?k\)?|"
                             r"\b403\s*\(?b\)?|\btsp\b", re.IGNORECASE)

# Account numbers, in the forms statements print them.
_ACCT_NUM_RX = re.compile(
    r"(?:acc(?:oun)?t\.?\s*(?:no\.?|number|#)?\s*[:#]?\s*|"
    r"ending\s+in\s+|\bno\.?\s*|#\s*|[xX*•]{2,}[-\s]?)"
    r"([xX*•\d][xX*•\d\- ]{2,}\d{4})\b")
# Eight or more digits, hyphens allowed, not carrying cents and not preceded
# by a dollar sign or decimal point: an identifier, never an amount.
_LONG_DIGITS_RX = re.compile(r"(?<![\d.$])(\d[\d\-]{6,}\d)(?![\d.])")
_SSN_RX = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_MASKED_TAIL_RX = re.compile(r"(?:[xX*•]{2,}[-\s]?)+(\d{4})\b")
_ENDING_IN_RX = re.compile(r"(?:ending\s+in|last\s+four|last\s+4)\s*:?\s*(\d{4})\b",
                           re.IGNORECASE)

# Institutions, most specific first. (regex, canonical name)
INSTITUTIONS: list[tuple[str, str]] = [
    (r"navy\s*federal|\bnfcu\b", "Navy Federal Credit Union"),
    (r"\busaa\b", "USAA"),
    (r"pentagon\s*federal|\bpenfed\b", "PenFed Credit Union"),
    (r"armed\s*forces\s*bank", "Armed Forces Bank"),
    (r"service\s*credit\s*union", "Service Credit Union"),
    (r"security\s*service\s*federal", "Security Service FCU"),
    (r"andrews\s*federal", "Andrews Federal Credit Union"),
    (r"fidelity", "Fidelity"),
    (r"charles\s*schwab|\bschwab\b", "Charles Schwab"),
    (r"vanguard", "Vanguard"),
    (r"jpmorgan\s*chase|j\.?p\.?\s*morgan|\bchase\b", "Chase"),
    (r"bank\s*of\s*america|merrill", "Bank of America / Merrill"),
    (r"wells\s*fargo", "Wells Fargo"),
    (r"capital\s*one", "Capital One"),
    (r"\bally\b", "Ally"),
    (r"marcus|goldman\s*sachs", "Marcus by Goldman Sachs"),
    (r"american\s*express|\bamex\b", "American Express"),
    (r"discover", "Discover"),
    (r"\bciti\b|citibank|citigroup", "Citi"),
    (r"\bsofi\b", "SoFi"),
    (r"e\*trade|etrade", "E*TRADE"),
    (r"td\s*ameritrade", "TD Ameritrade"),
    (r"interactive\s*brokers|\bibkr\b", "Interactive Brokers"),
    (r"robinhood", "Robinhood"),
    (r"betterment", "Betterment"),
    (r"wealthfront", "Wealthfront"),
    (r"morgan\s*stanley", "Morgan Stanley"),
    (r"edward\s*jones", "Edward Jones"),
    (r"t\.?\s*rowe\s*price", "T. Rowe Price"),
    (r"\bm1\s*finance\b", "M1 Finance"),
    (r"\bpnc\b", "PNC"),
    (r"u\.?s\.?\s*bank\b", "U.S. Bank"),
    (r"truist", "Truist"),
    (r"regions\s*bank", "Regions"),
    (r"synchrony", "Synchrony"),
    (r"\btiaa\b", "TIAA"),
]
_INST_RX = [(re.compile(p, re.IGNORECASE), name) for p, name in INSTITUTIONS]

# Dates.
_MONTHS = ("january|february|march|april|may|june|july|august|september|"
           "october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|"
           "oct|nov|dec")
_DATE_RX = re.compile(
    r"(?P<mdy>\b\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b)|"
    r"(?P<iso>\b\d{4}-\d{2}-\d{2}\b)|"
    r"(?P<long>\b(?:" + _MONTHS + r")\.?\s+\d{1,2},?\s+\d{4}\b)|"
    r"(?P<dmy>\b\d{1,2}\s+(?:" + _MONTHS + r")\.?,?\s+\d{4}\b)",
    re.IGNORECASE)
_MONTH_NUM = {m: i % 12 + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"])}
_MONTH_NUM.update({m[:3]: n for m, n in list(_MONTH_NUM.items())})
_MONTH_NUM["sept"] = 9

_DATE_CONTEXT_RX = re.compile(
    r"statement\s*date|as\s*of|period\s*ending|ending|through|thru|closing\s*date|"
    r"statement\s*period|for\s*the\s*period|statement\s*closing|balance\s*on",
    re.IGNORECASE)


# --------------------------------------------------------------------------
# Small pure helpers
# --------------------------------------------------------------------------

def parse_money(token: str) -> float | None:
    """'$1,234.56' -> 1234.56; '(1,234.56)' and '1,234.56-' -> -1234.56."""
    if token is None:
        return None
    m = _MONEY_RX.search(str(token).strip())
    if not m:
        return None
    return _money_from_match(m)


def _money_from_match(m: re.Match) -> float:
    value = float(m.group("num").replace(",", ""))
    negative = bool(m.group("sign") or m.group("sign2")
                    or (m.group("open") and m.group("close")))
    trail = (m.group("trail") or "").strip().upper()
    if trail in ("-", "DR"):
        negative = True
    return -value if negative else value


def money_tokens(line: str) -> list[tuple[float, int, int]]:
    """Every money value on a line, with its span."""
    return [(_money_from_match(m), m.start(), m.end())
            for m in _MONEY_RX.finditer(line)]


def is_sane_balance(value: float) -> tuple[bool, str]:
    """A balance is a non-negative number below the cap. Reason if not."""
    if value is None or value != value:      # NaN
        return False, "not a number"
    if value < MIN_BALANCE:
        return False, ("negative — an overdraft or something owed, not an "
                       "asset balance")
    if value > MAX_BALANCE:
        return False, (f"above the ${MAX_BALANCE:,.0f} sanity cap; almost "
                       f"certainly a misread")
    return True, ""


def mask_account_numbers(text: str) -> str:
    """
    Reduce anything that looks like an account number to its last four digits.

    Money is left alone: digit runs that carry a decimal part or thousands
    separators are amounts, not identifiers. Runs of seven or more bare digits
    (with or without hyphens) are identifiers. SSNs are masked to the last
    four as well.
    """
    if not text:
        return ""
    out = _SSN_RX.sub("***-**-XXXX", text)

    def _tail(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(1))
        return "****" + digits[-4:]

    out = _LONG_DIGITS_RX.sub(_tail, out)
    # Already-masked forms with a long run of x's: normalise to ****1234.
    out = _MASKED_TAIL_RX.sub(lambda m: "****" + m.group(1), out)
    return out


def last4(text: str) -> str:
    """The last four digits of an account number on this line, or ''."""
    if not text:
        return ""
    m = _MASKED_TAIL_RX.search(text) or _ENDING_IN_RX.search(text)
    if m:
        return m.group(1)
    m = _ACCT_NUM_RX.search(text)
    if m:
        digits = re.sub(r"\D", "", m.group(1))
        if len(digits) >= 4:
            return digits[-4:]
    m = _LONG_DIGITS_RX.search(text)
    if m:
        return re.sub(r"\D", "", m.group(1))[-4:]
    return ""


def _kind_of(text: str) -> str:
    for kind, rx in _KIND_RX:
        if rx.search(text):
            return kind
    return KIND_UNKNOWN


def _is_liability_line(text: str) -> bool:
    return bool(_LIABILITY_RX.search(text))


def default_target(kind: str, heading: str = "") -> str:
    """Where a balance of this kind should land unless the member says otherwise."""
    if heading:
        if _RETIREMENT_ROTH_RX.search(heading):
            return TARGET_ROTH_IRA
        if _OTHER_ASSET_RX.search(heading):
            return TARGET_OTHER
        if _RETIREMENT_TRAD_RX.search(heading):
            return TARGET_TRAD_IRA
    return DEFAULT_TARGET_FOR_KIND.get(kind, TARGET_CASH)


def detect_institution(text: str, filename: str = "") -> str:
    """Canonical institution name from the header, the body, or the filename."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    head = "\n".join(lines[:25])
    for rx, name in _INST_RX:
        if rx.search(head):
            return name
    fname = re.sub(r"[_\-.]+", " ", filename or "")
    for rx, name in _INST_RX:
        if rx.search(fname):
            return name
    body = "\n".join(lines[25:])
    for rx, name in _INST_RX:
        if rx.search(body):
            return name
    return "unknown"


def _to_iso(token: str) -> str:
    """Normalise a matched date to ISO. '' if it does not resolve to a real date."""
    t = token.strip().rstrip(",.")
    try:
        m = re.fullmatch(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})", t)
        if m:
            mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if y < 100:
                y += 2000
            return date(y, mo, d).isoformat()
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        m = re.fullmatch(r"([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})", t)
        if m:
            mo = _MONTH_NUM.get(m.group(1).lower())
            if mo:
                return date(int(m.group(3)), mo, int(m.group(2))).isoformat()
        m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\.?,?\s+(\d{4})", t)
        if m:
            mo = _MONTH_NUM.get(m.group(2).lower())
            if mo:
                return date(int(m.group(3)), mo, int(m.group(1))).isoformat()
    except ValueError:
        return ""
    return ""


def detect_statement_date(text: str) -> str:
    """
    The statement's closing date, if it can be found honestly.

    Looks for a date on a line that says "statement date", "as of", "period
    ending", "through" and so on. For a range ("02/01/2026 - 02/28/2026") the
    LAST date on the line is the end of the period. No guessing from
    transaction dates: the latest date in a document is often a payment due
    date or a print date.
    """
    best = ""
    for ln in (text or "").splitlines()[:80]:
        if not _DATE_CONTEXT_RX.search(ln):
            continue
        found = [_to_iso(m.group(0)) for m in _DATE_RX.finditer(ln)]
        found = [f for f in found if f]
        if found:
            best = found[-1]
            if re.search(r"statement\s*date|as\s*of|period\s*ending|"
                         r"closing\s*date", ln, re.IGNORECASE):
                return best
    return best


def _is_table_header(line: str) -> bool:
    low = line.lower()
    return sum(1 for w in _TABLE_HEADER_WORDS if w in low) >= 2


# --------------------------------------------------------------------------
# Plain text (also what a PDF becomes)
# --------------------------------------------------------------------------

@dataclass
class _Section:
    heading: str = ""
    kind: str = KIND_UNKNOWN
    last4: str = ""
    liability: bool = False
    lines: list = field(default_factory=list)
    hits: list = field(default_factory=list)     # (value, phrase, conf, raw, family)


def _is_heading(line: str) -> bool:
    """
    Does this line start a new account?

    A heading names an account kind and either carries an account number, says
    "account", or is short enough to be a title rather than a sentence. A line
    with a money amount on it is a data row, not a heading.
    """
    if money_tokens(line):
        return False
    kind = _kind_of(line)
    if kind == KIND_UNKNOWN and not _is_liability_line(line):
        return False
    if _is_table_header(line):
        return False
    low = line.lower()
    if last4(line) or "account" in low or "acct" in low:
        return True
    # A transaction description ("TRANSFER TO SAVINGS") is not a heading.
    if re.search(r"transfer|deposit|withdrawal|payment|purchase|\bfee\b|"
                 r"interest|your|you\b|earn|could|learn", low):
        return False
    words = line.split()
    if len(words) > 6:
        return False
    # Headings are set in Title Case or CAPITALS; sentences are not.
    capitalised = sum(1 for w in words if w[:1].isupper())
    return capitalised >= max(1, round(len(words) * 0.6))


def _split_sections(lines: list[str]) -> list[_Section]:
    sections: list[_Section] = [_Section()]
    for ln in lines:
        if _is_heading(ln):
            sec = _Section(heading=ln, kind=_kind_of(ln), last4=last4(ln),
                           liability=_is_liability_line(ln))
            if sec.kind == KIND_UNKNOWN and sec.liability:
                sec.kind = "liability"
            sections.append(sec)
            continue
        sections[-1].lines.append(ln)
    return sections


def _phrase_hits(line: str) -> list[tuple[float, str, float, str, int]]:
    """
    (value, phrase, confidence, family, value_position) for a balance phrase
    with a money value after it on this line. Empty if the phrase is qualified
    by a negative word, or there is no value.
    """
    out = []
    tokens = money_tokens(line)
    if not tokens:
        return out
    if _is_table_header(line):
        return out
    for phrase, conf, fam, rx in _BALANCE_RX:
        m = rx.search(line)
        if not m:
            continue
        # The label is the text between the previous amount (or the start of
        # the line) and the phrase, plus anything between the phrase and its
        # amount. "Total Deposits $3,500.00 Ending Balance $1,834.44" on one
        # line must not be poisoned by "deposits" from the previous label.
        prev_end = max([e for _, _, e in tokens if e <= m.start()], default=0)
        before = line[max(prev_end, m.start() - 40):m.start()]
        after = [(v, s, e) for v, s, e in tokens if s >= m.end()]
        if after:
            value, vstart, _ = after[0]
            between = line[m.end():vstart]
            penalty = 0.0
        else:
            # Value printed before its label -- a column order some PDF
            # extractors produce. Take the nearest amount, less confidently.
            value, vstart, _ = [t for t in tokens if t[2] <= m.start()][-1]
            between = line[vstart:m.start()]
            penalty = 0.15
        if _NEG_RX.search(before) or _NEG_RX.search(between):
            continue
        out.append((value, phrase, conf - penalty, fam, vstart))
        break        # first (strongest, most specific) phrase wins
    return out


def _phrase_only(line: str) -> tuple[str, float, str] | None:
    """A balance phrase with NO value on the line (the value may be on the next)."""
    if money_tokens(line) or _is_table_header(line):
        return None
    for phrase, conf, fam, rx in _BALANCE_RX:
        m = rx.search(line)
        if m:
            window = line[max(0, m.start() - 24):]
            if _NEG_RX.search(window):
                return None
            return (phrase, conf, fam)
    return None


def _bare_value_line(line: str) -> float | None:
    """A line that is nothing but one money value (and maybe a date)."""
    tokens = money_tokens(line)
    if len(tokens) != 1:
        return None
    rest = _MONEY_RX.sub("", line)
    rest = _DATE_RX.sub("", rest)
    if re.sub(r"[\s$:\-]", "", rest):
        return None
    return tokens[0][0]


def _summary_table(lines: list[str]) -> list[tuple[str, str, float, str, float]]:
    """
    Navy Federal-style "Summary of Accounts": a header row naming an ending
    column, followed by one row per account with several amounts.

        Account               Number     Beginning Balance   Ending Balance
        Active Duty Checking  ****1234   1,234.56            1,834.44
        Basic Savings         ****5678   10,000.00           10,125.00

    Returns (kind, last4, value, raw, confidence). The ending column is chosen
    by where "ending"/"closing"/"current" sits relative to "beginning" in the
    header: after it means the last amount on each row, before it the first.
    """
    out = []
    for i, ln in enumerate(lines):
        low = ln.lower()
        if money_tokens(ln):
            continue
        end_m = re.search(r"ending|closing|current|new\s*balance", low)
        beg_m = re.search(r"beginning|opening|previous|prior", low)
        if not (end_m and beg_m and ("balance" in low or "value" in low)):
            continue
        take_last = end_m.start() > beg_m.start()
        # "Beginning Value / Ending Value" is an investment summary.
        table_kind = (KIND_BROKERAGE if "value" in low and "balance" not in low
                      else KIND_UNKNOWN)
        for row in lines[i + 1:i + 30]:
            if not row.strip():
                break
            toks = money_tokens(row)
            if len(toks) < 2:
                if _is_heading(row) or _phrase_hits(row):
                    break
                continue
            kind = _kind_of(row)
            if kind == KIND_UNKNOWN and not last4(row):
                continue
            if _is_liability_line(row):
                continue
            if kind == KIND_UNKNOWN:
                kind = table_kind
            value = toks[-1][0] if take_last else toks[0][0]
            out.append((kind, last4(row), value, row, 0.75))
    return out


def parse_text(text: str, filename: str = "",
               source_kind: str = SOURCE_TEXT) -> ParseResult:
    """
    Read a statement's text and propose balances. Never raises on content;
    an unreadable document yields a result with no accounts and a warning.
    """
    raw_lines = [re.sub(r"[ \t ]+", " ", ln).strip()
                 for ln in (text or "").replace("\r", "\n").splitlines()]
    lines = [ln for ln in raw_lines if ln]
    res = ParseResult(source_kind=source_kind, n_lines=len(lines))
    if not lines:
        res.warnings.append("The statement had no readable text.")
        return res

    res.institution = detect_institution(text, filename)
    res.statement_date = detect_statement_date(text)
    doc_kind = _kind_of("\n".join(lines[:40]))
    doc_is_card = bool(re.search(
        r"minimum\s*payment\s*due|payment\s*due\s*date|credit\s*limit|"
        r"available\s*credit", text, re.IGNORECASE))
    if doc_is_card:
        res.warnings.append(
            "This looks like a credit card or loan statement. Balances on it "
            "are money OWED, not owned; nothing from it is offered as an asset. "
            "Enter debts on the Debt Payoff page instead.")

    sections = _split_sections(lines)

    # 1. Label-and-value lines within each section.
    for sec in sections:
        prev_phrase = None
        for ln in sec.lines:
            hits = _phrase_hits(ln)
            if hits:
                for value, phrase, conf, fam, _ in hits:
                    sec.hits.append((value, phrase, conf, ln, fam))
                prev_phrase = None
                continue
            if prev_phrase:
                bare = _bare_value_line(ln)
                if bare is not None:
                    phrase, conf, fam, pline = prev_phrase
                    sec.hits.append((bare, phrase, conf - 0.20,
                                     pline + " / " + ln, fam))
                prev_phrase = None
                continue
            po = _phrase_only(ln)
            prev_phrase = (po[0], po[1], po[2], ln) if po else None

    # 2. A summary table, wherever it sits.
    table_rows = _summary_table(lines)

    # 3. Turn sections into candidates.
    candidates: list[Candidate] = []
    for sec in sections:
        if not sec.hits:
            continue
        if sec.liability or sec.kind == "liability" or doc_is_card:
            for value, phrase, conf, ln, fam in sec.hits:
                res.rejected.append(Rejected(
                    value=value, phrase=phrase, raw_line=mask_account_numbers(ln),
                    reason="on a credit card or loan section: money owed, not "
                           "an asset"))
            continue
        cand = _candidate_from_hits(sec, res, doc_kind)
        if cand:
            candidates.append(cand)

    for kind, l4, value, row, conf in table_rows:
        ok, why = is_sane_balance(value)
        masked = mask_account_numbers(row)
        if not ok:
            res.rejected.append(Rejected(value=value, phrase="summary table",
                                         raw_line=masked, reason=why))
            continue
        candidates.append(Candidate(
            institution=res.institution, account_kind=kind,
            account_label=_label(kind, l4, row), account_last4=l4,
            ending_balance=value, statement_date=res.statement_date,
            matched_phrase="summary table: ending column", raw_line=masked,
            confidence=conf, target=default_target(kind, row),
            notes=["Read from a summary table with beginning and ending "
                   "columns; the ending column was taken."]))

    res.accounts = _merge(candidates, res)

    # A single-account statement usually prints the account number in the
    # header block, above any heading. Attach it when it is unambiguous.
    if len(res.accounts) == 1 and not res.accounts[0].account_last4:
        header_nums = {last4(ln) for ln in sections[0].lines if last4(ln)}
        if len(header_nums) == 1:
            c = res.accounts[0]
            c.account_last4 = header_nums.pop()
            c.account_label = _label(c.account_kind, c.account_last4, "")

    if not res.accounts and not res.rejected:
        res.warnings.append(
            "No closing balance was recognised. The parser looks for phrases "
            "like \"ending balance\", \"closing balance\" or \"total account "
            "value\" with an amount beside them. If the statement uses other "
            "words, type the balance on the Assets page.")
    return res


def _label(kind: str, l4: str, heading: str) -> str:
    name = kind.title() if kind != KIND_UNKNOWN else "Account"
    if kind == KIND_CD:
        name = "CD"
    if heading:
        for word in ("roth", "traditional ira", "rollover", "529", "hsa"):
            if word in heading.lower():
                name += f" ({word.upper() if len(word) <= 4 else word.title()})"
                break
    return f"{name} ****{l4}" if l4 else name


def _candidate_from_hits(sec: _Section, res: ParseResult,
                         doc_kind: str) -> Candidate | None:
    """Best hit becomes the balance; the rest are alternates. Sanity-checks."""
    sane = []
    for value, phrase, conf, ln, fam in sec.hits:
        ok, why = is_sane_balance(value)
        if ok:
            sane.append((value, phrase, conf, ln, fam))
        else:
            res.rejected.append(Rejected(value=value, phrase=phrase,
                                         raw_line=mask_account_numbers(ln),
                                         reason=why))
    if not sane:
        return None

    # Collapse repeats of the same phrase with the same value (a statement
    # often prints the closing balance twice).
    seen = {}
    for h in sane:
        key = (h[1], round(h[0], 2))
        if key not in seen or h[2] > seen[key][2]:
            seen[key] = h
    sane = sorted(seen.values(), key=lambda h: (-h[2], h[0]))

    kind = sec.kind if sec.kind != KIND_UNKNOWN else doc_kind
    notes = []
    best = sane[0]
    fam = best[4]
    if kind == KIND_UNKNOWN:
        if fam == "brokerage":
            kind = KIND_BROKERAGE
            notes.append("No account heading was found; treated as a "
                         "brokerage account because the phrase matched is an "
                         "investment-statement phrase.")
        elif fam == "bank":
            notes.append("No account heading was found; the balance phrase "
                         "reads like a bank statement.")

    conf = best[2]
    if sec.kind == KIND_UNKNOWN:
        conf -= 0.12
    distinct_strong = {round(h[0], 2) for h in sane if h[2] >= 0.80}
    if len(distinct_strong) > 1:
        conf -= 0.20
        notes.append("More than one strong closing-balance figure was found in "
                     "this section. If this is a combined statement whose "
                     "account headings were not recognised, each figure may "
                     "belong to a different account -- check the alternates.")
    if best[0] == 0:
        conf -= 0.10
        notes.append("The balance read as zero. A closed or empty account, or "
                     "a misread.")
    conf = max(0.05, min(0.98, conf))

    cand = Candidate(
        institution=res.institution, account_kind=kind,
        account_label=_label(kind, sec.last4, sec.heading),
        account_last4=sec.last4, ending_balance=best[0],
        statement_date=res.statement_date, matched_phrase=best[1],
        raw_line=mask_account_numbers(best[3]), confidence=conf,
        target=default_target(kind, sec.heading), notes=notes)
    for value, phrase, c, ln, _ in sane[1:]:
        if abs(value - best[0]) < 0.005:
            continue        # the same figure under another name is not an alternative
        cand.alternates.append(Alternate(value=value, phrase=phrase,
                                         raw_line=mask_account_numbers(ln),
                                         confidence=max(0.05, min(0.98, c))))
    if cand.target in (TARGET_ROTH_IRA, TARGET_TRAD_IRA, TARGET_OTHER):
        cand.notes.append(f"The heading suggests this is not a taxable "
                          f"account; suggested target is "
                          f"{TARGET_LABELS[cand.target]}. Change it if that "
                          f"is wrong.")
    return cand


def _merge(cands: list[Candidate], res: ParseResult) -> list[Candidate]:
    """
    Fold duplicates: the same account seen in a summary table and again in
    its own section. Same kind and last-four with the same value merge and
    gain confidence; with different values, the stronger one stays and the
    other becomes an alternate with a warning.
    """
    out: list[Candidate] = []
    for c in cands:
        twin = None
        for o in out:
            same_num = c.account_last4 and c.account_last4 == o.account_last4
            same_kind_unnumbered = (not c.account_last4 and not o.account_last4
                                    and c.account_kind == o.account_kind)
            if same_num or same_kind_unnumbered:
                twin = o
                break
        if twin is None:
            out.append(c)
            continue
        if abs(twin.ending_balance - c.ending_balance) < 0.005:
            # Same account, same figure: keep the better-supported reading's
            # phrase and line, and let the agreement raise confidence.
            if c.confidence > twin.confidence:
                twin.matched_phrase, twin.raw_line = c.matched_phrase, c.raw_line
            twin.confidence = min(0.98, max(twin.confidence, c.confidence) + 0.05)
            if twin.account_kind == KIND_UNKNOWN and c.account_kind != KIND_UNKNOWN:
                twin.account_kind = c.account_kind
                twin.account_label = c.account_label
                twin.target = c.target
            twin.notes.append("The same figure appears twice on the statement, "
                              "which is reassuring.")
            for a in c.alternates:
                if all(abs(a.value - b.value) > 0.005 for b in twin.alternates) \
                   and abs(a.value - twin.ending_balance) > 0.005:
                    twin.alternates.append(a)
        else:
            keep, drop = ((twin, c) if twin.confidence >= c.confidence
                          else (c, twin))
            if keep is c:
                out[out.index(twin)] = c
            keep.alternates.append(Alternate(
                value=drop.ending_balance, phrase=drop.matched_phrase,
                raw_line=drop.raw_line, confidence=drop.confidence))
            keep.confidence = max(0.05, keep.confidence - 0.15)
            keep.notes.append("Two different figures were found for what looks "
                              "like the same account. Check the alternates "
                              "against the paper.")
    return out


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------

def _norm_col(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).strip()


# Balance columns, best first. Matched against normalised header names.
CSV_BALANCE_COLUMNS = [
    ("ending balance", 0.90), ("closing balance", 0.90), ("end balance", 0.88),
    ("ending value", 0.88), ("total account value", 0.90),
    ("account value", 0.85), ("market value", 0.80), ("current value", 0.80),
    ("total value", 0.75), ("running balance", 0.80), ("balance", 0.80),
    ("current balance", 0.78), ("value", 0.60),
]
_CSV_DATE_COLS = ("date", "posted date", "post date", "transaction date",
                  "posting date", "as of", "as of date")
_CSV_ACCT_NUM_COLS = ("account number", "account", "acct", "account no",
                      "account id", "acct number", "acct no")
_CSV_ACCT_NAME_COLS = ("account name", "account type", "type", "name",
                       "account description", "product", "nickname",
                       "description of account")
_CSV_HOLDING_COLS = ("symbol", "ticker", "quantity", "shares", "cusip",
                     "last price", "price")
_CSV_TXN_COLS = ("amount", "debit", "credit", "withdrawal", "deposit",
                 "transaction", "payee", "memo")


def _find_col(cols: list[str], wanted) -> str | None:
    for w in wanted:
        for c in cols:
            if c == w:
                return c
    for w in wanted:
        for c in cols:
            if w in c:
                return c
    return None


def parse_csv(text: str, filename: str = "") -> ParseResult:
    """
    A CSV is the easy case when it has a column called something like
    "balance" or "market value". Three shapes are recognised:

      accounts   one row per account, a balance column -> one candidate a row
      holdings   one row per position with a symbol/quantity column -> the
                 value column is SUMMED per account, because a single row is
                 one holding, never the account
      transactions  a date and amount column with a running balance -> the
                 balance on the latest-dated row is the ending balance
    """
    res = ParseResult(source_kind=SOURCE_CSV)
    body = (text or "").lstrip("﻿")
    if not body.strip():
        res.warnings.append("The CSV was empty.")
        return res

    # Some exports lead with a few title lines before the header. Find the
    # first line that splits into several cells and looks like a header.
    lines = body.splitlines()
    try:
        dialect = csv.Sniffer().sniff("\n".join(lines[:20]), delimiters=",;\t|")
        delim = dialect.delimiter
    except csv.Error:
        delim = ","
    start = 0
    for i, ln in enumerate(lines[:15]):
        cells = [c.strip() for c in next(csv.reader([ln], delimiter=delim), [])]
        filled = [c for c in cells if c]
        # A header has several cells and none of them is a number.
        if len(filled) >= 2 and not any(re.fullmatch(r"[\d,.$()\- /]+", c)
                                        for c in filled):
            start = i
            break
    reader = csv.reader(lines[start:], delimiter=delim)
    try:
        header = next(reader)
    except StopIteration:
        res.warnings.append("The CSV had no header row.")
        return res
    cols = [_norm_col(c) for c in header]
    rows = [r for r in reader if any(c.strip() for c in r)]
    res.n_lines = len(rows)
    res.institution = detect_institution("\n".join(lines[:5]), filename)

    bal_col, bal_conf = None, 0.0
    for wanted, conf in CSV_BALANCE_COLUMNS:
        hit = _find_col(cols, (wanted,))
        if hit and not _NEG_RX.search(hit):
            bal_col, bal_conf = hit, conf
            break
    if bal_col is None:
        res.warnings.append(
            "No balance column was found. Columns seen: "
            + ", ".join(h.strip() for h in header if h.strip()) + ". The "
            "parser looks for a column named balance, ending balance, market "
            "value, account value or current value.")
        return res
    bi = cols.index(bal_col)

    def cell(row, name):
        if name is None or name not in cols:
            return ""
        i = cols.index(name)
        return row[i].strip() if i < len(row) else ""

    date_col = _find_col(cols, _CSV_DATE_COLS)
    num_col = _find_col(cols, _CSV_ACCT_NUM_COLS)
    name_col = _find_col(cols, _CSV_ACCT_NAME_COLS)
    type_col = _find_col(cols, ("account type", "type", "product"))
    if name_col == num_col:
        name_col = None
    if type_col in (name_col, num_col):
        type_col = None
    holding_col = _find_col(cols, _CSV_HOLDING_COLS)
    txn_col = _find_col(cols, _CSV_TXN_COLS)
    if txn_col == bal_col:
        txn_col = None
    fname_hint = re.sub(r"[_\-.]+", " ", filename or "")

    def kind_and_label(row):
        heading = " ".join(x for x in (cell(row, name_col), cell(row, type_col),
                                       cell(row, num_col)) if x)
        kind = _kind_of(heading) if heading else KIND_UNKNOWN
        if kind == KIND_UNKNOWN and holding_col:
            kind = KIND_BROKERAGE
        if kind == KIND_UNKNOWN and not _is_liability_line(fname_hint):
            kind = _kind_of(fname_hint)      # "usaa_checking_export.csv"
        l4 = last4(cell(row, num_col)) or re.sub(r"\D", "", cell(row, num_col))[-4:]
        return kind, l4, heading

    candidates: list[Candidate] = []

    if date_col and txn_col and not holding_col:
        # Transactions with a running balance: take the latest-dated row.
        dated = []
        for r in rows:
            v = parse_money(cell(r, bal_col))
            d = _to_iso(cell(r, date_col))
            if v is not None and d:
                dated.append((d, v, r))
        if not dated:
            res.warnings.append("No row had both a date and a balance.")
            return res
        dated.sort(key=lambda t: t[0])
        d, v, r = dated[-1]
        kind, l4, heading = kind_and_label(r)
        ok, why = is_sane_balance(v)
        raw = mask_account_numbers(delim.join(x for x in r))
        if not ok:
            res.rejected.append(Rejected(value=v, phrase=f"column '{bal_col}'",
                                         raw_line=raw, reason=why))
        else:
            res.statement_date = d
            candidates.append(Candidate(
                institution=res.institution, account_kind=kind,
                account_label=_label(kind, l4, heading), account_last4=l4,
                ending_balance=v, statement_date=d,
                matched_phrase=f"column '{bal_col}' on the latest-dated row",
                raw_line=raw, confidence=min(bal_conf, 0.72),
                target=default_target(kind, heading),
                notes=["A transaction export: the running balance on the "
                       "latest-dated row was taken as the ending balance. If "
                       "several transactions share that date, the one listed "
                       "last was used -- check it against the bank's own "
                       "balance."]))

    elif holding_col:
        # Positions export: sum the value column per account.
        groups: dict[str, list] = {}
        order = []
        for r in rows:
            v = parse_money(cell(r, bal_col))
            if v is None:
                continue
            key = cell(r, num_col) or cell(r, name_col) or "all"
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append((v, r))
        for key in order:
            vals = groups[key]
            total = sum(v for v, _ in vals)
            kind, l4, heading = kind_and_label(vals[0][1])
            ok, why = is_sane_balance(total)
            raw = mask_account_numbers(f"{key}: {len(vals)} holding rows summed")
            if not ok:
                res.rejected.append(Rejected(value=total, phrase=f"sum of '{bal_col}'",
                                             raw_line=raw, reason=why))
                continue
            candidates.append(Candidate(
                institution=res.institution, account_kind=kind,
                account_label=_label(kind, l4, heading), account_last4=l4,
                ending_balance=total, statement_date=res.statement_date,
                matched_phrase=f"sum of column '{bal_col}' over {len(vals)} rows",
                raw_line=raw, confidence=0.60,
                target=default_target(kind, heading),
                notes=["A positions export lists one row per holding, so the "
                       "rows were summed. Check the total includes the cash "
                       "position and no pending-activity row was dropped."]))

    else:
        # One row per account.
        for r in rows:
            v = parse_money(cell(r, bal_col))
            if v is None:
                continue
            kind, l4, heading = kind_and_label(r)
            if _is_liability_line(heading):
                res.rejected.append(Rejected(
                    value=v, phrase=f"column '{bal_col}'",
                    raw_line=mask_account_numbers(delim.join(r)),
                    reason="a credit card or loan row: money owed, not an asset"))
                continue
            ok, why = is_sane_balance(v)
            raw = mask_account_numbers(delim.join(r))
            if not ok:
                res.rejected.append(Rejected(value=v, phrase=f"column '{bal_col}'",
                                             raw_line=raw, reason=why))
                continue
            conf = bal_conf - (0.10 if kind == KIND_UNKNOWN else 0.0)
            candidates.append(Candidate(
                institution=res.institution, account_kind=kind,
                account_label=_label(kind, l4, heading), account_last4=l4,
                ending_balance=v, statement_date=res.statement_date,
                matched_phrase=f"column '{bal_col}'", raw_line=raw,
                confidence=max(0.05, min(0.98, conf)),
                target=default_target(kind, heading)))

    res.accounts = candidates
    if not res.accounts and not res.rejected:
        res.warnings.append(f"A '{bal_col}' column was found but no row in it "
                            f"held a readable amount.")
    return res


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------

def extract_pdf_text(data: bytes) -> str:
    """
    Text layer of a PDF, read from memory. Raises PDFSupportMissing when pypdf
    is not installed and StatementFormatError when the file cannot be read.
    A scanned statement has no text layer and comes back empty.
    """
    try:
        from pypdf import PdfReader
    except ImportError as e:                       # pragma: no cover
        raise PDFSupportMissing(
            "PDF reading needs the 'pypdf' package, which is not installed. "
            "Paste the statement text instead, or download a CSV from the "
            "bank.") from e
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                raise StatementFormatError(
                    "This PDF is password-protected. Open it in a viewer, "
                    "copy the text and paste it instead.")
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                pages.append("")
        return "\n".join(pages)
    except StatementFormatError:
        raise
    except Exception as e:
        raise StatementFormatError(f"That PDF could not be read: {e}") from e


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("latin-1", errors="replace")


def _looks_like_csv(text: str) -> bool:
    head = [ln for ln in text.splitlines()[:10] if ln.strip()]
    if len(head) < 2:
        return False
    counts = [ln.count(",") + ln.count("\t") + ln.count(";") for ln in head]
    return min(counts) >= 1 and sum(1 for c in counts if c >= 2) >= len(head) // 2 + 1


def parse(data, filename: str = "") -> ParseResult:
    """
    Read a statement in whatever form it arrived and propose balances.

    `data` is bytes from an upload or a str that was pasted. The file name,
    if known, picks the reader; otherwise the content does. PDF needs pypdf
    (raises PDFSupportMissing if absent -- the page turns that into advice,
    not a crash).
    """
    name = (filename or "").lower()
    if isinstance(data, bytes):
        if name.endswith(".pdf") or data[:5] == b"%PDF-":
            text = extract_pdf_text(data)
            if not text.strip():
                res = ParseResult(source_kind=SOURCE_PDF)
                res.warnings.append(
                    "The PDF has no text layer -- it is probably a scan. Paste "
                    "the figures as text, or use a CSV download from the bank.")
                return res
            return parse_text(text, filename, source_kind=SOURCE_PDF)
        text = _decode(data)
    else:
        text = str(data or "")

    if name.endswith((".csv", ".tsv")) or (not name.endswith(".txt")
                                            and _looks_like_csv(text)):
        res = parse_csv(text, filename)
        if res.ok or name.endswith((".csv", ".tsv")):
            return res
        # Looked like a CSV but was not; fall through to text.
    return parse_text(text, filename)


# --------------------------------------------------------------------------
# Applying to the Household -- the only thing here that changes anything
# --------------------------------------------------------------------------

@dataclass
class Decision:
    """What the member chose for one candidate on the page."""
    candidate: Candidate
    target: str = TARGET_CASH
    value: float | None = None       # override; None means candidate's figure

    @property
    def amount(self) -> float:
        return float(self.candidate.ending_balance if self.value is None
                     else self.value)


@dataclass
class Change:
    target: str = ""
    label: str = ""
    before: float = 0.0
    after: float = 0.0
    sources: list = field(default_factory=list)     # account labels


MODE_REPLACE = "replace"
MODE_ADD = "add"


def _field(h, target: str):
    owner, attr = TARGET_FIELDS[target]
    return (h if owner == "household" else h.member), attr


def plan_changes(h, decisions: list, mode: str = MODE_REPLACE) -> list[Change]:
    """
    What Apply would do, without doing it. Several accounts aimed at the same
    field (checking + savings -> cash) are summed. In replace mode the field
    becomes that sum; in add mode the sum is added to whatever is there.
    """
    grouped: dict[str, Change] = {}
    for d in decisions:
        if d.target == TARGET_SKIP or d.target not in TARGET_FIELDS:
            continue
        ok, _ = is_sane_balance(d.amount)
        if not ok:
            continue
        if d.target not in grouped:
            obj, attr = _field(h, d.target)
            before = float(getattr(obj, attr))
            grouped[d.target] = Change(target=d.target,
                                       label=TARGET_LABELS[d.target],
                                       before=before,
                                       after=before if mode == MODE_ADD else 0.0)
        ch = grouped[d.target]
        ch.after += d.amount
        ch.sources.append(d.candidate.account_label)
    return list(grouped.values())


def apply_to_household(h, decisions: list, mode: str = MODE_REPLACE) -> list[Change]:
    """
    Write the chosen balances into the Household. Returns what changed.

    The caller (the page) is responsible for mark_dirty() and invalidate();
    this module knows nothing about Streamlit. Only the final numbers are
    written -- no statement text, no account numbers, no institution name.
    """
    changes = plan_changes(h, decisions, mode)
    for ch in changes:
        obj, attr = _field(h, ch.target)
        setattr(obj, attr, float(ch.after))
    return changes
