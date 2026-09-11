"""
Reading a Leave and Earnings Statement, or a Retiree Account Statement.

Every figure this app needs about a serving member's pay is already printed on
one page they get every month. Typing it in again is where the errors come
from: people transcribe the year-to-date column, or the mid-month net, or they
give up at "special pays" and enter nothing. So this module reads the document.

WHAT THE TWO DOCUMENTS ARE

    LES   DFAS Form 702, issued monthly to anyone on active duty, Guard or
          Reserve. Four bands: an identity table across the top, then three
          side-by-side columns -- ENTITLEMENTS, DEDUCTIONS, ALLOTMENTS --
          then a SUMMARY band, then leave, tax and TSP blocks and remarks.
    RAS   The retiree's statement, issued when something changes and each
          December. It is a short list: GROSS PAY down through SBP COSTS,
          VA WAIVER, taxes, to NET PAY.

THE TRAPS, WHICH ARE WHAT THIS MODULE IS ACTUALLY FOR

  1. EVERY AMOUNT HAS A YEAR-TO-DATE TWIN. The summary band and the tax and
     TSP blocks repeat the same labels against YTD totals. A YTD figure is six
     to twelve times the monthly one and looks entirely plausible -- an E-5
     whose "basic pay" comes back as $49,320 has had their retirement
     projection multiplied by twelve and nothing on screen will look wrong. Any
     line mentioning YTD is refused outright, and every number is range-checked
     afterwards, because that is the failure that does real damage.

  2. THE TOP BAND IS A TABLE, NOT PROSE. GRADE and YRS SVC are column headings
     with their values on the row beneath, aligned by character position. PDF
     text extraction that does not preserve columns turns that into two
     unrelated lines and adjacency parsing gets nothing -- or worse, pairs
     GRADE with whatever happens to follow it. Handled positionally first, by
     adjacency second, and abandoned rather than guessed.

  3. THREE COLUMNS RUN SIDE BY SIDE. TSP, SGLI and federal tax are DEDUCTIONS,
     not entitlements. Summing every dollar sign on the page produces a number
     that means nothing. "Other entitlements" is taken from the entitlements
     column only, and every line that went into the sum is shown back.

  4. LABELS COLLIDE. "BASE PAY" begins with the letters BAS. BAH also appears
     as BAH-DIFF (paid to a member in quarters who pays child support -- a
     couple of hundred dollars, not a housing allowance) and as BAH RC/T. The
     TSP block contains the words BASE PAY RATE and BASE PAY CURRENT, neither
     of which is basic pay.

  5. ON A RAS, GROSS PAY IS BEFORE THE VA WAIVER AND THE SBP COST; NET PAY is
     after both. "Retired pay" in this app means gross, and a member reading
     their own statement will usually quote the net.

  6. THIS PARSER WAS WRITTEN WITHOUT A SPECIMEN IN HAND. DFAS is a .mil host.
     Field labels differ between the printed LES and the myPay web LES, between
     branches, and between active and reserve formats. So this module does not
     get to be confident: it PROPOSES values, shows the line of text each one
     came from, marks the ones it is unsure of, and a person presses the
     button. Nothing here writes into a profile on its own -- see
     apply_findings(), which only touches what it is handed.

PRIVACY

An LES carries a name and at least the last four of an SSN. The document is
read from bytes in memory and never written to disk; this app has no server, so
nothing is uploaded anywhere. The raw text is deliberately NOT kept on the
ParseResult and must never be stored in a Household or a saved plan -- only
short, redacted excerpts of the lines a value came from survive parsing, and
redact() runs over every one of them.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
import io
import re

from engine.pay import grades as G
from engine.pay import basepay as BP
from engine.pay import bas as BAS_TABLE

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------
DOC_LES = "LES"
DOC_RAS = "RAS"
DOC_UNKNOWN = "UNKNOWN"

HIGH = "high"
MEDIUM = "medium"
LOW = "low"

OK = "ok"                 # in range, offer it
SUSPECT = "suspect"       # found, but outside the plausible range: never offered
CONFLICT = "conflict"     # in range, but disagrees with something else we read
INFO = "info"             # read and worth saying, but this app has no field for it

TARGET_MEMBER = "member"
TARGET_HOUSEHOLD = "household"

# --------------------------------------------------------------------------
# Plausible ranges. A number outside its range is reported as "found but looks
# wrong" and is never offered as a value -- a decimal slip or a YTD column that
# slipped past the label filters lands here.
# --------------------------------------------------------------------------
# 2026 basic pay spans $2,225.70 (E-1) to $18,999.90 (O-10 at 38+). The bounds
# are deliberately a little wider than the table so a future raise does not
# start rejecting real statements.
RANGE_BASIC_PAY = (2_000.0, 20_000.0)
RANGE_BAH = (0.0, 6_000.0)
# 2026 BAS is $476.95 enlisted, $328.48 officer, $953.90 for BAS II. Note the
# direction: ENLISTED BAS IS THE HIGHER OF THE TWO, which is the reverse of
# what people expect, so the band has to cover both and the officer/enlisted
# check below is advisory only.
RANGE_BAS = (200.0, 1_200.0)
RANGE_SPECIAL_PAY = (0.0, 10_000.0)
RANGE_TSP_PCT = (0.0, 100.0)
RANGE_YOS = (0.0, 45.0)
RANGE_SDP = (0.0, 25_000.0)
RANGE_RETIRED_PAY = (100.0, 25_000.0)
RANGE_VA = (0.0, 12_000.0)
RANGE_SBP_PREMIUM = (0.0, 2_000.0)
RANGE_CRSC = (0.0, 6_000.0)
RANGE_CRDP = (0.0, 25_000.0)

# How far the LES basic pay may sit from the published table before we call it
# a disagreement. A stale table year is worth a few percent; twelve percent is
# never a rounding difference.
BASIC_PAY_TOLERANCE = 0.05

SBP_PREMIUM_RATE = 0.065          # of the elected base amount


# --------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------
_SSN_PATTERNS = [
    # 123-45-6789, ***-**-6789, XXX-XX-6789, 123 45 6789
    re.compile(r"\b(?:\d|[*xX#]){3}[-\s]?(?:\d|[*xX#]){2}[-\s]?\d{4}\b"),
    # A bare nine-digit run. Nothing in military pay is a nine-digit number.
    re.compile(r"\b\d{9}\b"),
    # A labelled last-four: "SSN: 6789", "SOC SEC NO: 6789". The separator or a
    # run of mask characters is REQUIRED. Without it this pattern eats
    # "FICA-SOC SEC   254.82" off the deductions column, which is both a
    # useless redaction and a hole in the only line the user can check us by --
    # so the leading hyphen is excluded outright.
    re.compile(r"(?i)(?<!-)\b(?:SSN|S\.?S\.?N\.?|SOC\.?\s*SEC\.?(?:\s*NO\.?)?)"
               r"\s*[:#=]\s*[-*xX#\s]*\d{3,4}\b"),
    re.compile(r"(?i)(?<!-)\b(?:SSN|S\.?S\.?N\.?|SOC\.?\s*SEC\.?(?:\s*NO\.?)?)"
               r"\s*[-*xX#]{2,}[-\s]*\d{3,4}\b"),
    # DoD ID / EDIPI is not an SSN but is just as identifying.
    re.compile(r"(?i)\b(?:DOD\s*ID|DODID|EDIPI)\s*[:#]?\s*\d{6,12}\b"),
]

REDACTED = "[redacted]"


def redact(text: str) -> str:
    """
    Strip anything SSN-shaped out of text before it is shown back to the user.

    Applied to every excerpt that leaves this module. It is deliberately
    aggressive: a nine-digit run has no legitimate meaning on a pay statement,
    so removing one costs nothing and leaving one in a screenshot costs a lot.
    """
    out = text or ""
    for pat in _SSN_PATTERNS:
        out = pat.sub(REDACTED, out)
    return out


def _excerpt(text: str, limit: int = 110) -> str:
    """One short, redacted, whitespace-collapsed line, safe to display."""
    clean = re.sub(r"\s+", " ", redact(text or "")).strip()
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "\u2026"


# --------------------------------------------------------------------------
# Result model
# --------------------------------------------------------------------------
@dataclass
class Finding:
    """
    One thing the parser believes it read.

    A Finding is a PROPOSAL. `applicable` is the only thing that says a value is
    fit to write, and `preselect` is the only thing that says the parser is
    confident enough to tick the box for the user.
    """
    field: str = ""                  # ServiceMember / Household attribute, "" for INFO
    label: str = ""                  # what to call it on screen
    value: object = None             # normalised, ready to assign
    display: str = ""                # value formatted for a table cell
    raw: str = ""                    # the redacted line it came from
    matched_on: str = ""             # the literal label text we keyed off
    confidence: str = LOW
    status: str = OK
    note: str = ""
    target: str = TARGET_MEMBER

    @property
    def applicable(self) -> bool:
        return bool(self.field) and self.status in (OK, CONFLICT) and self.value is not None

    @property
    def preselect(self) -> bool:
        """Unsure means shown but not ticked. Only a clean, high-confidence,
        in-range, non-conflicting read gets ticked for the user."""
        return self.applicable and self.status == OK and self.confidence == HIGH


@dataclass
class Missing:
    """A field we went looking for and did not find, and where to type it."""
    label: str = ""
    where: str = ""

    def __str__(self) -> str:
        return f"{self.label} — type it on {self.where}" if self.where else self.label


@dataclass
class ParseResult:
    """
    What one document yielded. Carries NO raw document text by design.
    """
    doc_type: str = DOC_UNKNOWN
    doc_type_confidence: str = LOW
    markers: list = dc_field(default_factory=list)
    findings: list = dc_field(default_factory=list)
    missing: list = dc_field(default_factory=list)
    warnings: list = dc_field(default_factory=list)
    n_lines: int = 0

    # ------------------------------------------------------------------
    @property
    def applicable(self) -> list:
        return [f for f in self.findings if f.applicable]

    @property
    def suspect(self) -> list:
        return [f for f in self.findings if f.status == SUSPECT]

    @property
    def informational(self) -> list:
        return [f for f in self.findings if f.status == INFO]

    @property
    def preselected_fields(self) -> list:
        return [f.field for f in self.findings if f.preselect]

    def get(self, field_name: str):
        for f in self.findings:
            if f.field == field_name:
                return f
        return None

    @property
    def found_nothing(self) -> bool:
        return not self.findings


# --------------------------------------------------------------------------
# Turning an upload into text
# --------------------------------------------------------------------------
class IngestError(Exception):
    """A file that could not be turned into text. The message is user-facing."""


PDF_MISSING_MESSAGE = (
    "This build cannot read PDFs — the pypdf library is not installed. "
    "Open the LES in myPay or a PDF viewer, select all the text, copy it, and "
    "paste it into the box instead. That works just as well."
)
PDF_NO_TEXT_MESSAGE = (
    "That PDF has no text in it — it is almost certainly a scan or a picture of "
    "an LES rather than the myPay download. Nothing can be read out of an "
    "image here. Open the original, copy the text, and paste it into the box."
)
PDF_UNREADABLE_MESSAGE = (
    "That PDF could not be opened. If it is password-protected, remove the "
    "password first; otherwise copy the text out of it and paste it into the "
    "box instead."
)


def read_upload(data: bytes, filename: str = "") -> str:
    """
    Bytes in, text out. Nothing is written to disk at any point.

    Accepts a PDF (by extension or by the %PDF signature) or any text encoding
    people actually paste from. Raises IngestError with a message meant to be
    shown verbatim -- the caller must catch it, not let it reach a traceback.
    """
    if not data:
        raise IngestError("That file is empty.")
    name = (filename or "").lower()
    if name.endswith(".pdf") or data[:5] == b"%PDF-":
        return _pdf_text(data)
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise IngestError("That file is not text and does not look like a PDF. "
                      "Paste the text of your statement into the box instead.")


def _pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader          # the pre-rename package name
        except ImportError:
            raise IngestError(PDF_MISSING_MESSAGE)

    try:
        reader = PdfReader(io.BytesIO(data))
        if getattr(reader, "is_encrypted", False):
            try:
                reader.decrypt("")
            except Exception:
                raise IngestError(PDF_UNREADABLE_MESSAGE)
        pages = [_page_text(p) for p in reader.pages]
    except IngestError:
        raise
    except Exception as exc:                       # a malformed or truncated file
        raise IngestError(f"{PDF_UNREADABLE_MESSAGE} ({type(exc).__name__})")

    text = "\n".join(pages)
    if len(re.sub(r"\s", "", text)) < 40:
        raise IngestError(PDF_NO_TEXT_MESSAGE)
    return text


def _page_text(page) -> str:
    """
    Layout mode keeps the columns, which is what makes the top band of an LES
    readable at all. It is not available on every pypdf version, and it throws
    on some files, so plain extraction is the fallback.
    """
    try:
        return page.extract_text(extraction_mode="layout") or ""
    except Exception:
        pass
    try:
        return page.extract_text() or ""
    except Exception:
        return ""


# --------------------------------------------------------------------------
# Text plumbing
# --------------------------------------------------------------------------
def _lines(text: str) -> list:
    """
    Normalised lines with HORIZONTAL POSITION PRESERVED.

    Nothing here collapses runs of spaces: the character offsets are the only
    thing tying a column heading to the value underneath it.
    """
    cleaned = (text or "").replace("\u00a0", " ").replace("\u2007", " ")
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    return [ln.expandtabs(8).rstrip() for ln in cleaned.split("\n")]


_MONEY = re.compile(r"""
    (?P<open>[-(])?\s*
    \$?\s*
    (?P<num>\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)
    (?P<close>[-)])?
""", re.VERBOSE)


@dataclass
class _Token:
    value: float
    raw: str
    start: int
    end: int


def _money_tokens(segment: str) -> list:
    """Every number-shaped thing in a slice of a line, in order, with offsets."""
    out = []
    for m in _MONEY.finditer(segment or ""):
        num = m.group("num").replace(",", "")
        try:
            value = float(num)
        except ValueError:
            continue
        negative = m.group("open") in ("-", "(") or m.group("close") in ("-", ")")
        out.append(_Token(value=-value if negative else value,
                          raw=m.group(0).strip(), start=m.start(), end=m.end()))
    return out


def _in_range(value: float, bounds) -> bool:
    lo, hi = bounds
    return lo <= value <= hi


def _fmt_money(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.2f}"


# --------------------------------------------------------------------------
# Which document is this?
# --------------------------------------------------------------------------
_LES_MARKERS = [
    r"LEAVE\s+AND\s+EARNINGS\s+STATEMENT", r"\bDFAS\s+FORM\s+702\b",
    r"\bENTITLEMENTS\b", r"\bALLOTMENTS\b", r"\bYRS\s*SVC\b", r"\bPAY\s+DATE\b",
    r"\bADSN\b", r"\bPERIOD\s+COVERED\b", r"\bTHRIFT\s+SAVINGS\s+PLAN\b",
    r"\bBASE\s+PAY\b", r"\bBAQ\b", r"\bLEAVE\b.{0,12}\bBAL\b", r"\bTOT\s*ENT\b",
    r"\bCR\s*FWD\b", r"\bEOM\s+PAY\b", r"\bMID[-\s]?MONTH[-\s]?PAY\b",
]
_RAS_MARKERS = [
    r"RETIREE\s+ACCOUNT\s+STATEMENT", r"\bGROSS\s+PAY\b", r"\bVA\s+WAIVER\b",
    r"\bSBP\s+COSTS?\b", r"\bRETIRED\s+PAY\b", r"\bSURVIVOR\s+BENEFIT\s+PLAN\b",
    r"\bCRDP\b", r"\bCRSC\b", r"\bRETIREMENT\s+PAY\b", r"\bNET\s+PAY\b",
    r"\bCOST\s+OF\s+LIVING\b",
]


def detect_doc_type(text: str) -> tuple:
    """(doc type, confidence, the marker phrases that were actually present)."""
    upper = (text or "").upper()
    les = [p for p in _LES_MARKERS if re.search(p, upper)]
    ras = [p for p in _RAS_MARKERS if re.search(p, upper)]

    # A named title settles it outright.
    if re.search(r"RETIREE\s+ACCOUNT\s+STATEMENT", upper):
        return DOC_RAS, HIGH, _pretty_markers(ras)
    if re.search(r"LEAVE\s+AND\s+EARNINGS\s+STATEMENT", upper):
        return DOC_LES, HIGH, _pretty_markers(les)

    if len(les) >= 3 and len(les) > len(ras):
        return DOC_LES, MEDIUM if len(les) >= 5 else LOW, _pretty_markers(les)
    if len(ras) >= 3 and len(ras) > len(les):
        return DOC_RAS, MEDIUM if len(ras) >= 5 else LOW, _pretty_markers(ras)
    if len(les) >= 2 and len(les) > len(ras):
        return DOC_LES, LOW, _pretty_markers(les)
    if len(ras) >= 2 and len(ras) > len(les):
        return DOC_RAS, LOW, _pretty_markers(ras)
    return DOC_UNKNOWN, LOW, _pretty_markers(les + ras)


def _pretty_markers(patterns) -> list:
    out = []
    for p in patterns:
        word = re.sub(r"\\s\+|\\s\*|\.\{0,\d+\}", " ", p)
        word = re.sub(r"\\b|\[-\\s\]\?", "", word)
        out.append(re.sub(r"\s+", " ", word).strip())
    return out


# --------------------------------------------------------------------------
# Label rules for the plain "label then amount on the same line" fields
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class _Rule:
    field: str
    label: str
    patterns: tuple
    bounds: tuple
    where: str                       # the page that asks for it by hand
    exclude: tuple = ()
    kind: str = "money"              # money | percent
    target: str = TARGET_MEMBER
    optional: bool = False           # not reported as missing when absent


# Any line carrying one of these is a total or a year-to-date figure, never a
# current-month entitlement. This is trap 1 and it is the important one.
_PERIOD_NOISE = (r"\bYTD\b", r"YEAR\s*TO\s*DATE", r"\bY-T-D\b", r"\bTOTAL\b",
                 r"\bTOT\s*ENT\b", r"\bTOT\s*DED\b", r"\bWAGE\s*PERIOD\b")

_LES_RULES = (
    _Rule(field="basic_pay_monthly_override", label="Basic pay (monthly)",
          patterns=(r"\bBASE\s+PAY\b", r"\bBASIC\s+PAY\b"),
          bounds=RANGE_BASIC_PAY, where="the 'Income' page",
          # The TSP block prints BASE PAY RATE and BASE PAY CURRENT. Neither is
          # basic pay and both sit next to a number.
          exclude=_PERIOD_NOISE + (r"\bRATE\b", r"\bCURRENT\b", r"\bTSP\b",
                                   r"\bHIGH[-\s]?3\b", r"\bRETIRED\b")),
    _Rule(field="bah_monthly_override", label="BAH (housing allowance)",
          # BAH-DIFF and BAH RC/T are different, much smaller entitlements.
          patterns=(r"\bBAH\b(?!\s*[-/]?\s*(?:DIFF|RC|II|TYPE))",
                    r"\bBASIC\s+ALLOWANCE\s+FOR\s+HOUSING\b", r"\bBAQ\b"),
          bounds=RANGE_BAH, where="the 'Income' page",
          # A remarks line -- "BAH BASED ON W/DEP, ZIP 02138" -- offers a
          # five-digit number that reads perfectly well as a housing allowance.
          exclude=_PERIOD_NOISE + (r"\bRATE\b", r"\bTSP\b", r"\bDIFF\b",
                                   r"\bPARTIAL\b", r"\bZIP\b", r"\bBASED\s+ON\b")),
    _Rule(field="bas_monthly_override", label="BAS (subsistence allowance)",
          patterns=(r"\bBAS\b", r"\bBAS\s*II\b",
                    r"\bBASIC\s+ALLOWANCE\s+FOR\s+SUBSISTENCE\b"),
          bounds=RANGE_BAS, where="the 'Income' page",
          exclude=_PERIOD_NOISE + (r"\bRATE\b", r"\bTSP\b")),
    _Rule(field="tsp_contribution_pct", label="TSP contribution (% of basic pay)",
          patterns=(r"\bTSP\b[^\n]{0,24}?\bBASE\s+PAY\s+RATE\b",
                    r"\bBASE\s+PAY\s+RATE\b",
                    r"\bTSP\s+(?:CONTRIBUTION\s+)?(?:RATE|PCT|PERCENT)\b",
                    r"\bTHRIFT\s+SAVINGS[^\n]{0,40}?\bRATE\b"),
          bounds=RANGE_TSP_PCT, kind="percent",
          where="the 'Deployment' page",
          exclude=_PERIOD_NOISE),
    _Rule(field="sdp_balance", label="Savings Deposit Program balance",
          patterns=(r"\bSDP\b", r"\bSAVINGS\s+DEPOSIT(?:\s+PROGRAM)?\b"),
          bounds=RANGE_SDP, where="the 'Profile' page", optional=True,
          exclude=(r"\bYTD\b", r"YEAR\s*TO\s*DATE")),
)

_RAS_RULES = (
    _Rule(field="retired_pay_monthly", label="Gross retired pay (monthly)",
          patterns=(r"\bGROSS\s+PAY\b", r"\bGROSS\s+RETIRED\s+PAY\b",
                    r"\bMONTHLY\s+GROSS\b", r"\bRETIRED\s+PAY\s+GROSS\b"),
          bounds=RANGE_RETIRED_PAY, where="the 'Profile' page",
          exclude=_PERIOD_NOISE + (r"\bNET\b", r"\bTAXABLE\b")),
    _Rule(field="va_disability_monthly", label="VA compensation (the VA waiver)",
          patterns=(r"\bVA\s+WAIVER\b", r"\bWAIVER\s+FOR\s+VA\b",
                    r"\bVA\s+DISABILITY(?:\s+COMPENSATION)?\b",
                    r"\bVA\s+COMPENSATION\b"),
          bounds=RANGE_VA, where="the 'Profile' page", exclude=_PERIOD_NOISE),
    _Rule(field="crsc_monthly", label="CRSC (combat-related special compensation)",
          patterns=(r"\bCRSC\b",
                    r"\bCOMBAT[-\s]RELATED\s+SPECIAL\s+COMPENSATION\b"),
          bounds=RANGE_CRSC, where="the 'Profile' page", optional=True,
          exclude=_PERIOD_NOISE),
)


@dataclass
class _Candidate:
    value: float
    raw: str
    matched_on: str
    line_no: int
    pattern_rank: int


def _scan_rule(lines: list, rule: _Rule) -> list:
    """Every place in the document this rule's label appears with a number after it."""
    out = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        upper = line.upper()
        if any(re.search(x, upper) for x in rule.exclude):
            continue
        for rank, pattern in enumerate(rule.patterns):
            m = re.search(pattern, upper)
            if not m:
                continue
            tokens = _money_tokens(line[m.end():])
            if not tokens:
                continue
            tok = tokens[0]           # the first number AFTER the label, not the line's
            out.append(_Candidate(value=tok.value, raw=line,
                                  matched_on=line[m.start():m.end()].strip(),
                                  line_no=i, pattern_rank=rank))
            break
    return out


def _finding_from_candidates(cands: list, rule: _Rule) -> Finding | None:
    """
    Pick one candidate, or report that everything found was implausible.

    In-range beats out-of-range; an earlier pattern (the more specific label)
    beats a later one; a disagreement between two in-range candidates costs
    confidence and is said out loud rather than resolved silently.
    """
    if not cands:
        return None

    scale = 100.0 if rule.kind == "percent" else 1.0
    good = [c for c in cands if _in_range(c.value, rule.bounds)]

    if not good:
        worst = min(cands, key=lambda c: c.pattern_rank)
        lo, hi = rule.bounds
        unit = "%" if rule.kind == "percent" else ""
        shown = (f"{worst.value:g}{unit}" if rule.kind == "percent"
                 else _fmt_money(worst.value))
        band = (f"{lo:g}{unit} to {hi:g}{unit}" if rule.kind == "percent"
                else f"{_fmt_money(lo)} to {_fmt_money(hi)}")
        return Finding(
            field=rule.field, label=rule.label, value=None, display=shown,
            raw=_excerpt(worst.raw), matched_on=worst.matched_on,
            confidence=LOW, status=SUSPECT, target=rule.target,
            note=(f"Read {shown} next to \"{worst.matched_on}\", which is outside "
                  f"the plausible range of {band}. Not offered — check the "
                  f"statement and type it in by hand."))

    good.sort(key=lambda c: (c.pattern_rank, c.line_no))
    best = good[0]
    distinct = {round(c.value, 2) for c in good}

    confidence = HIGH
    note = ""
    if len(distinct) > 1:
        others = ", ".join(sorted(_fmt_money(v) if rule.kind == "money" else f"{v:g}%"
                                  for v in distinct if round(v, 2) != round(best.value, 2)))
        confidence = MEDIUM
        note = (f"The document has more than one figure against this label "
                f"({others} as well). Taking the first. Check it.")

    value = best.value / scale
    display = (f"{best.value:g}%" if rule.kind == "percent"
               else _fmt_money(best.value))
    if rule.kind == "money" and best.value == 0.0:
        confidence = MEDIUM
        note = (note + " " if note else "") + \
            "Read as zero. This app treats a zero override as \"look it up\", " \
            "so applying it will not pin the figure."

    return Finding(field=rule.field, label=rule.label, value=value,
                   display=display, raw=_excerpt(best.raw),
                   matched_on=best.matched_on, confidence=confidence,
                   status=OK, note=note, target=rule.target)


# --------------------------------------------------------------------------
# The top band: GRADE and YRS SVC, which are a table and not a sentence
# --------------------------------------------------------------------------
_HEADER_LABELS = (
    (r"PERIOD\s+COVERED", "PERIOD COVERED"),
    (r"SOC\.?\s*SEC\.?\s*NO\.?", "SSN"),
    (r"ADSN\s*/?\s*DSSN", "ADSN"),
    (r"\bPAY\s+DATE\b", "PAY DATE"),
    (r"\bYRS\s*SVC\b", "YRS SVC"),
    (r"\bYEARS\s+SERVICE\b", "YRS SVC"),
    (r"\bGRADE\b", "GRADE"),
    (r"\bBRANCH\b", "BRANCH"),
    (r"\bNAME\b", "NAME"),
    (r"\bETS\b", "ETS"),
    (r"\bSSN\b", "SSN"),
)

_GRADE_TOKEN = re.compile(r"\b([EWO])\s*-?\s*(\d{1,2})\s*(E?)\b")

# Where _header_cells stashes the whole identity row, for the collapsed-PDF
# fallback. Not a column name, so it cannot collide with one.
ROW_KEY = "__row__"


def _grade_from(text: str) -> str | None:
    """A pay grade this app recognises, or nothing. Never a guess."""
    if not text:
        return None
    for m in _GRADE_TOKEN.finditer(text.upper()):
        candidate = f"{m.group(1)}-{int(m.group(2))}{m.group(3)}"
        try:
            return G.get(candidate).label
        except KeyError:
            continue
    return None


def _header_cells(lines: list) -> dict:
    """
    Read the LES identity table by character position.

    A heading row with three or more known labels gives the column boundaries;
    the row beneath is sliced on them. If the PDF lost its spacing the slices
    come back empty and this returns nothing, which is the right answer -- the
    caller then falls back to same-line adjacency and, failing that, reports the
    field as not found.
    """
    for i, line in enumerate(lines):
        upper = line.upper()
        hits = []
        for pattern, name in _HEADER_LABELS:
            for m in re.finditer(pattern, upper):
                hits.append((m.start(), m.end(), name))
        if len({n for _, _, n in hits}) < 3:
            continue
        # Drop overlaps (SOC. SEC. NO. also contains no bare SSN, but ADSN/DSSN
        # contains "DSSN" and "SSN"); keep the leftmost, longest.
        hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
        spans, last_end = [], -1
        for start, end, name in hits:
            if start < last_end:
                continue
            spans.append((start, name))
            last_end = end

        value_line = ""
        for j in range(i + 1, min(i + 4, len(lines))):
            if lines[j].strip():
                value_line = lines[j]
                break
        if not value_line:
            continue

        cells = {}
        for k, (start, name) in enumerate(spans):
            stop = spans[k + 1][0] if k + 1 < len(spans) else len(value_line) + 200
            cells.setdefault(name, value_line[start:stop].strip())
        # The whole row is kept so a caller can fall back to searching it when
        # the slices came back as nonsense, which is what a collapsed PDF does.
        cells[ROW_KEY] = value_line
        if any(cells.get(n) for n in ("GRADE", "YRS SVC")):
            return cells
    return {}


def _read_grade(lines: list, cells: dict) -> tuple:
    """(Finding or None, how it was read)."""
    cell = cells.get("GRADE", "")
    grade = _grade_from(cell)
    if grade:
        return Finding(field="grade", label="Pay grade", value=grade,
                       display=grade, raw=_excerpt(f"GRADE column: {cell}"),
                       matched_on="GRADE", confidence=HIGH, status=OK), "column"

    for i, line in enumerate(lines):
        upper = line.upper()
        m = re.search(r"\b(?:PAY\s+)?GRADE\b\s*[:.]?", upper)
        if not m:
            continue
        grade = _grade_from(line[m.end():m.end() + 24])
        if grade:
            return Finding(field="grade", label="Pay grade", value=grade,
                           display=grade, raw=_excerpt(line),
                           matched_on=line[m.start():m.end()].strip(),
                           confidence=HIGH, status=OK), "adjacent"

    # Last resort, for a PDF whose columns collapsed to single spaces: the row
    # under the heading still has the grade in it somewhere. Only taken when the
    # row yields exactly ONE grade this app recognises -- two candidates means
    # something else on the row is grade-shaped, and a coin toss between them is
    # exactly the kind of quiet wrong answer this module exists to avoid.
    row = cells.get(ROW_KEY, "")
    if row:
        seen = []
        for mm in _GRADE_TOKEN.finditer(row.upper()):
            try:
                label = G.get(f"{mm.group(1)}-{int(mm.group(2))}{mm.group(3)}").label
            except KeyError:
                continue
            if label not in seen:
                seen.append(label)
        if len(seen) == 1:
            return Finding(field="grade", label="Pay grade", value=seen[0],
                           display=seen[0],
                           raw=_excerpt(f"identity row, grade token: {seen[0]}"),
                           matched_on="GRADE", confidence=MEDIUM, status=OK), "row"
    return None, ""


def _read_yos(lines: list, cells: dict) -> Finding | None:
    cell = cells.get("YRS SVC", "")
    m = re.search(r"\d{1,2}(?:\.\d)?", cell or "")
    if m:
        value = float(m.group(0))
        if _in_range(value, RANGE_YOS):
            return Finding(field="years_of_service", label="Years of service",
                           value=value, display=f"{value:g}",
                           raw=_excerpt(f"YRS SVC column: {cell}"),
                           matched_on="YRS SVC", confidence=HIGH, status=OK)

    for line in lines:
        upper = line.upper()
        m = re.search(r"\bYRS\s*(?:OF\s*)?SVC\b|\bYEARS\s+(?:OF\s+)?SERVICE\b", upper)
        if not m:
            continue
        tail = re.search(r"\d{1,2}(?:\.\d)?", line[m.end():m.end() + 20])
        if not tail:
            continue
        value = float(tail.group(0))
        if not _in_range(value, RANGE_YOS):
            return Finding(field="years_of_service", label="Years of service",
                           value=None, display=f"{value:g}", raw=_excerpt(line),
                           matched_on=line[m.start():m.end()].strip(),
                           confidence=LOW, status=SUSPECT,
                           note=(f"Read {value:g} years, which is outside 0–45. "
                                 f"Not offered."))
        return Finding(field="years_of_service", label="Years of service",
                       value=value, display=f"{value:g}", raw=_excerpt(line),
                       matched_on=line[m.start():m.end()].strip(),
                       confidence=MEDIUM, status=OK,
                       note="Read by adjacency rather than from the column, so "
                            "check it.")
    return None


# --------------------------------------------------------------------------
# The entitlements column, and what is left in it after base pay, BAH and BAS
# --------------------------------------------------------------------------
_NOT_SPECIAL_PAY = (
    r"\bBASE\s+PAY\b", r"\bBASIC\s+PAY\b", r"\bBAS\b", r"\bBAH\b", r"\bBAQ\b",
    r"\bVHA\b", r"\bTOT", r"\bTOTAL\b", r"\bENTITLEMENTS?\b", r"\bYTD\b",
    r"\bAMT\s*FWD\b", r"\bCR\s*FWD\b", r"\bEOM\b", r"\bMID[-\s]?MONTH\b",
)
_ENT_STOP = re.compile(r"^\s*(?:SUMMARY|TOT(?:AL)?\b|LEAVE\b|FED\s+TAXES|"
                       r"FICA|TAXES|RETIREMENT\s+PLAN|THRIFT|REMARKS|={3,}|-{5,})")


def _entitlement_rows(lines: list) -> tuple:
    """
    (rows, layout) where rows are (label, amount, raw line).

    Three layouts, and telling them apart is the whole job:

      columnar   ENTITLEMENTS and DEDUCTIONS are headings on one line with real
                 space between them. Every following line is sliced to the
                 entitlements column before a number is taken, or federal tax
                 gets added to someone's flight pay.
      collapsed  The same three headings, but the extractor threw the spacing
                 away and they are one space apart. The column offsets now mean
                 NOTHING, and slicing on them cuts amounts in half -- $1,854.00
                 becomes $1.8. So the line is read whole and only the FIRST
                 label-and-amount pair is taken, because the entitlements
                 column is the leftmost one.
      stacked    ENTITLEMENTS stands alone and its entries simply follow it.
    """
    for i, line in enumerate(lines):
        upper = line.upper()
        m = re.search(r"\bENTITLEMENTS\b", upper)
        if not m:
            continue
        neighbours = [x.start() for x in
                      re.finditer(r"\bDEDUCTIONS\b|\bALLOTMENTS\b|\bSUMMARY\b", upper)
                      if x.start() > m.start()]
        left = 0 if not line[:m.start()].strip() else m.start()

        if not neighbours:
            layout, right = "stacked", None
        elif min(neighbours) - m.end() < 3:
            layout, right = "collapsed", None
        else:
            layout, right = "columnar", min(neighbours)

        rows = []
        blanks = 0
        for j in range(i + 1, min(i + 45, len(lines))):
            raw = lines[j]
            segment = raw[left:right] if right is not None else raw
            if not segment.strip():
                blanks += 1
                if blanks >= 3 or (layout != "columnar" and blanks >= 2):
                    break
                continue
            blanks = 0
            if _ENT_STOP.match(segment.upper()):
                break
            if layout != "columnar" and re.search(
                    r"\bDEDUCTIONS\b|\bALLOTMENTS\b", segment.upper()):
                break
            tokens = _money_tokens(segment)
            if not tokens:
                continue
            # Inside a sliced column the amount is the rightmost number; on a
            # whole collapsed line it is the first, and everything after it
            # belongs to the deductions and allotments columns.
            tok = tokens[0] if layout == "collapsed" else tokens[-1]
            label = segment[:tok.start].strip(" .:")
            if not label:
                continue
            rows.append((label, tok.value, raw))
        return rows, layout
    return [], ""


def _read_special_pay(lines: list) -> Finding | None:
    rows, layout = _entitlement_rows(lines)
    if not rows:
        return None

    kept = []
    for label, amount, raw in rows:
        upper = label.upper()
        if any(re.search(x, upper) for x in _NOT_SPECIAL_PAY):
            continue
        if amount <= 0:
            continue
        kept.append((label, amount))
    if not kept:
        return None

    total = sum(a for _, a in kept)
    detail = "; ".join(f"{lbl} {_fmt_money(amt)}" for lbl, amt in kept)

    if not _in_range(total, RANGE_SPECIAL_PAY):
        return Finding(
            field="special_pay_monthly", label="Special and incentive pays",
            value=None, display=_fmt_money(total),
            raw=_excerpt(detail), matched_on="ENTITLEMENTS",
            confidence=LOW, status=SUSPECT,
            note=(f"The other entitlements add to {_fmt_money(total)}, outside "
                  f"the plausible range. Something in that column was misread."))

    return Finding(
        field="special_pay_monthly", label="Special and incentive pays",
        value=total, display=_fmt_money(total), raw=_excerpt(detail),
        matched_on="ENTITLEMENTS",
        # Never high: which lines belong in this sum is a judgement, and the
        # columnar slice is a positional guess on top of that.
        confidence=MEDIUM if layout == "stacked" else LOW, status=OK,
        note=(f"Sum of {len(kept)} entitlement line(s) that are not basic pay, "
              f"BAH or BAS. Read the list and drop anything that does not "
              f"belong before you apply it."))


# --------------------------------------------------------------------------
# Dependency status and the BAH ZIP
# --------------------------------------------------------------------------
_WITHOUT_DEP = re.compile(r"W\s*/?\s*O\s*DEP|WITHOUT\s+DEP|\bSINGLE\s+RATE\b")
_WITH_DEP = re.compile(r"W\s*/\s*DEP|WITH\s+DEP|\bW[-\s]DEP\b")


def _read_dependents(lines: list) -> Finding | None:
    for line in lines:
        upper = line.upper()
        if "BAH" not in upper and "BAQ" not in upper and "DEP" not in upper:
            continue
        if _WITHOUT_DEP.search(upper):
            return Finding(field="has_dependents", label="Dependents for pay purposes",
                           value=False, display="No", raw=_excerpt(line),
                           matched_on="BAH type", confidence=MEDIUM, status=OK,
                           note="Inferred from a without-dependents housing rate.")
        if _WITH_DEP.search(upper):
            return Finding(field="has_dependents", label="Dependents for pay purposes",
                           value=True, display="Yes", raw=_excerpt(line),
                           matched_on="BAH type", confidence=MEDIUM, status=OK,
                           note="Inferred from a with-dependents housing rate.")
    return None


def _read_duty_zip(lines: list) -> Finding | None:
    for line in lines:
        upper = line.upper()
        m = re.search(r"\bZIP(?:\s*CODE)?\b\s*[:#]?\s*(\d{5})\b", upper)
        if not m:
            m = re.search(r"\bBAH\b[^\n]{0,40}?\b(\d{5})\b", upper)
        if not m:
            continue
        zipcode = m.group(1)
        if zipcode == "00000":
            continue
        return Finding(field="duty_zip", label="Duty ZIP code (drives BAH)",
                       value=zipcode, display=zipcode, raw=_excerpt(line),
                       matched_on="ZIP", confidence=MEDIUM, status=OK,
                       note="A five-digit number on a pay statement is not "
                            "always the BAH ZIP. Confirm it before applying.")
    return None


# --------------------------------------------------------------------------
# RAS extras: the SBP cost, and CRDP
# --------------------------------------------------------------------------
def _read_sbp(lines: list) -> list:
    for line in lines:
        upper = line.upper()
        if any(re.search(x, upper) for x in _PERIOD_NOISE):
            continue
        m = re.search(r"\bSBP\s+COSTS?\b|\bSBP\s+PREMIUM\b|"
                      r"\bSURVIVOR\s+BENEFIT\s+PLAN\s+COSTS?\b", upper)
        if not m:
            continue
        tokens = _money_tokens(line[m.end():])
        if not tokens:
            continue
        premium = abs(tokens[0].value)
        if premium <= 0:
            continue
        out = [Finding(field="sbp_elected", label="SBP elected", value=True,
                       display="Yes", raw=_excerpt(line),
                       matched_on=line[m.start():m.end()].strip(),
                       confidence=HIGH if _in_range(premium, RANGE_SBP_PREMIUM) else MEDIUM,
                       status=OK,
                       note="An SBP cost is being deducted, so the election is "
                            "in force.")]
        if _in_range(premium, RANGE_SBP_PREMIUM):
            implied = premium / SBP_PREMIUM_RATE
            out.append(Finding(
                field="", label="SBP premium (monthly)", value=premium,
                display=_fmt_money(premium), raw=_excerpt(line),
                matched_on=line[m.start():m.end()].strip(),
                confidence=MEDIUM, status=INFO,
                note=(f"At the statutory 6.5% this implies an elected base "
                      f"amount of about {_fmt_money(implied)} a month. This app "
                      f"has no field for the premium itself — the base amount "
                      f"is asked for on the 'Survivor Benefits' page.")))
        else:
            out.append(Finding(
                field="", label="SBP premium (monthly)", value=None,
                display=_fmt_money(premium), raw=_excerpt(line),
                matched_on=line[m.start():m.end()].strip(),
                confidence=LOW, status=SUSPECT,
                note="That premium is outside the plausible range, so the "
                     "election flag above is worth double-checking too."))
        return out
    return []


def _read_crdp(lines: list) -> list:
    for line in lines:
        upper = line.upper()
        if any(re.search(x, upper) for x in _PERIOD_NOISE):
            continue
        m = re.search(r"\bCRDP\b|\bCONCURRENT\s+RETIREMENT\s+AND\s+DISABILITY\b",
                      upper)
        if not m:
            continue
        tokens = _money_tokens(line[m.end():])
        amount = abs(tokens[0].value) if tokens else 0.0
        out = [Finding(field="crdp_applies", label="CRDP applies", value=True,
                       display="Yes", raw=_excerpt(line),
                       matched_on=line[m.start():m.end()].strip(),
                       confidence=HIGH, status=OK,
                       note="A CRDP line is on the statement, so concurrent "
                            "receipt is already restoring retired pay.")]
        if amount > 0:
            out.append(Finding(
                field="", label="CRDP restored (monthly)", value=amount,
                display=_fmt_money(amount), raw=_excerpt(line),
                matched_on=line[m.start():m.end()].strip(),
                confidence=MEDIUM,
                status=INFO if _in_range(amount, RANGE_CRDP) else SUSPECT,
                note="CRDP is part of gross retired pay, not an addition to it. "
                     "This app records CRDP as a yes/no, so the amount is here "
                     "for you to check against your gross."))
        return out
    return []


# --------------------------------------------------------------------------
# Cross-checks
# --------------------------------------------------------------------------
def cross_check_grade_and_pay(grade: str, years: float | None,
                              monthly: float, table=None) -> tuple:
    """
    Does the basic pay on the statement match the published table for that grade?

    Returns (agrees, message, table_monthly). `agrees` is None when no check was
    possible. This is the check that catches the two failures a range test
    cannot: a grade read out of the wrong column, and a basic pay figure that is
    really someone's net or their YTD-over-twelve.
    """
    if not grade or monthly is None or monthly <= 0:
        return None, "", 0.0
    table = table if table is not None else BP.load()
    if table is None:
        return None, BP.MISSING_DATA_NOTE, 0.0

    try:
        code = G.get(grade).code
        label = G.get(grade).label
    except KeyError:
        return None, f"{grade!r} is not a pay grade this app knows.", 0.0

    row = table.rates.get(code) or {}
    values = [float(v) for v in row.values() if v]
    if not values:
        return None, f"No {table.year} basic pay is published for {label}.", 0.0

    if years is not None:
        result = BP.lookup(label, float(years), table)
        if result.found:
            expected = result.monthly
            drift = abs(monthly - expected) / expected
            if drift <= BASIC_PAY_TOLERANCE:
                return True, (f"Basic pay agrees with the {table.year} table for "
                              f"{label} at {float(years):g} years "
                              f"({_fmt_money(expected)})."), expected
            return False, (f"The statement says {label} with {float(years):g} years "
                           f"of service, but the {table.year} table pays "
                           f"{_fmt_money(expected)} a month at that point and the "
                           f"basic pay read off the statement is "
                           f"{_fmt_money(monthly)} — {drift * 100:.0f}% away. One "
                           f"of the three was misread. Check all three before "
                           f"applying any of them."), expected

    lo, hi = min(values), max(values)
    if lo * (1 - BASIC_PAY_TOLERANCE) <= monthly <= hi * (1 + BASIC_PAY_TOLERANCE):
        return True, (f"Basic pay sits inside the {table.year} {label} scale "
                      f"({_fmt_money(lo)}–{_fmt_money(hi)})."), 0.0
    return False, (f"The statement reads as {label}, but {label} basic pay runs "
                   f"{_fmt_money(lo)}–{_fmt_money(hi)} a month in {table.year} and "
                   f"the figure read off the statement is {_fmt_money(monthly)}. "
                   f"Either the grade or the pay was misread."), 0.0


def _bas_note(grade: str, monthly: float) -> str:
    """
    Advisory only. Enlisted BAS is the HIGHER of the two rates, which surprises
    people often enough that a mismatch is worth a sentence and never worth
    rejecting a value over -- BAS II, a partial month and a rate change all
    produce a legitimate mismatch.
    """
    if not grade or monthly <= 0:
        return ""
    try:
        officer = G.is_officer(G.get(grade))
    except KeyError:
        return ""
    year = BAS_TABLE.latest_year()
    rates = BAS_TABLE.BAS_RATES[year]
    expected = rates["officer"] if officer else rates["enlisted"]
    other = rates["enlisted"] if officer else rates["officer"]
    if abs(monthly - expected) <= 15.0:
        return ""
    if abs(monthly - other) <= 15.0:
        who = "an officer" if officer else "enlisted"
        return (f"The BAS read here is the {year} "
                f"{'enlisted' if officer else 'officer'} rate "
                f"({_fmt_money(other)}) but the grade reads as {who}. Check which "
                f"of the two was misread.")
    if abs(monthly - rates["bas_ii"]) <= 15.0:
        return f"That is the {year} BAS II rate, not standard BAS."
    return (f"The {year} rate for this grade is {_fmt_money(expected)}; the "
            f"statement reads {_fmt_money(monthly)}. A rate change or a partial "
            f"month explains a small gap, not a large one.")


# --------------------------------------------------------------------------
# The entry point
# --------------------------------------------------------------------------
_LES_MISSING_LABELS = {
    "grade": ("Pay grade", "the 'Profile' page"),
    "years_of_service": ("Years of service", "the 'Profile' page"),
    "special_pay_monthly": ("Special and incentive pays", "the 'Income' page"),
    "has_dependents": ("Dependents for pay purposes", "the 'Profile' page"),
    "duty_zip": ("Duty ZIP code (drives BAH)", "the 'Profile' page"),
}

def parse(text: str, doc_type: str = "", table=None) -> ParseResult:
    """
    Read a statement and PROPOSE values. Applies nothing.

    `doc_type` forces LES or RAS when the caller already knows; otherwise it is
    detected. `table` is a basic pay table for the cross-check, injected so the
    tests do not depend on what is installed.
    """
    lines = _lines(text)
    detected, confidence, markers = detect_doc_type(text)
    forced = bool(doc_type)
    kind = (doc_type or detected).upper() or DOC_UNKNOWN
    if forced:
        # The caller looked at the document and said what it is. Believe them.
        confidence = HIGH

    result = ParseResult(doc_type=kind, doc_type_confidence=confidence,
                         markers=markers[:8],
                         n_lines=sum(1 for ln in lines if ln.strip()))

    if kind == DOC_UNKNOWN:
        result.warnings.append(
            "This does not look like an LES or a Retiree Account Statement. "
            "Anything read out of it is a guess and nothing is ticked for you. "
            "If you pasted only part of a statement, that is fine — check each "
            "line below against the document.")

    if kind == DOC_RAS:
        _parse_ras(lines, result)
    else:
        _parse_les(lines, result, table=table)

    # A weakly identified document cannot support a confident field. A document
    # the caller has identified for us is a different matter.
    if not forced and (confidence == LOW or kind == DOC_UNKNOWN):
        for f in result.findings:
            if f.confidence == HIGH:
                f.confidence = MEDIUM
                f.note = (f.note + " " if f.note else "") + \
                    "Downgraded because the document itself was not clearly " \
                    "identified as an LES or an RAS."

    return result


def _parse_les(lines: list, result: ParseResult, table=None) -> None:
    cells = _header_cells(lines)

    grade_finding, how = _read_grade(lines, cells)
    if grade_finding:
        if how == "adjacent":
            grade_finding.note = ("Read from a GRADE label rather than from the "
                                  "identity table.")
        elif how == "row":
            grade_finding.note = ("The identity table's columns did not survive "
                                  "extraction, so this was taken from the only "
                                  "grade-shaped token on the row. Check it.")
        result.findings.append(grade_finding)
    yos_finding = _read_yos(lines, cells)
    if yos_finding:
        result.findings.append(yos_finding)

    for rule in _LES_RULES:
        f = _finding_from_candidates(_scan_rule(lines, rule), rule)
        if f:
            result.findings.append(f)
        elif not rule.optional:
            result.missing.append(Missing(rule.label, rule.where))

    special = _read_special_pay(lines)
    if special:
        result.findings.append(special)
    else:
        result.missing.append(Missing(*_LES_MISSING_LABELS["special_pay_monthly"]))

    for reader, key in ((_read_dependents, "has_dependents"),
                        (_read_duty_zip, "duty_zip")):
        f = reader(lines)
        if f:
            result.findings.append(f)
        else:
            result.missing.append(Missing(*_LES_MISSING_LABELS[key]))

    if not grade_finding:
        result.missing.append(Missing(*_LES_MISSING_LABELS["grade"]))
    if not yos_finding:
        result.missing.append(Missing(*_LES_MISSING_LABELS["years_of_service"]))

    _apply_les_cross_checks(result, table=table)


def _apply_les_cross_checks(result: ParseResult, table=None) -> None:
    grade_f = result.get("grade")
    yos_f = result.get("years_of_service")
    pay_f = result.get("basic_pay_monthly_override")
    bas_f = result.get("bas_monthly_override")

    grade = grade_f.value if (grade_f and grade_f.applicable) else ""
    years = yos_f.value if (yos_f and yos_f.applicable) else None
    monthly = pay_f.value if (pay_f and pay_f.applicable) else 0.0

    if grade and monthly:
        agrees, message, _expected = cross_check_grade_and_pay(
            grade, years, monthly, table=table)
        if agrees is False:
            result.warnings.append(message)
            for f in (grade_f, yos_f, pay_f):
                if f is not None and f.applicable:
                    f.status = CONFLICT
                    f.confidence = LOW
                    f.note = (f.note + " " if f.note else "") + \
                        "Grade, years of service and basic pay do not agree " \
                        "with the published table — see the warning above."
        elif agrees is True and message:
            if pay_f is not None:
                pay_f.note = (pay_f.note + " " if pay_f.note else "") + message
        elif message:
            result.warnings.append(message)

    if grade and bas_f is not None and bas_f.applicable:
        note = _bas_note(grade, float(bas_f.value))
        if note:
            bas_f.confidence = MEDIUM
            bas_f.note = (bas_f.note + " " if bas_f.note else "") + note


def _parse_ras(lines: list, result: ParseResult) -> None:
    for rule in _RAS_RULES:
        f = _finding_from_candidates(_scan_rule(lines, rule), rule)
        if f:
            result.findings.append(f)
        elif not rule.optional:
            result.missing.append(Missing(rule.label, rule.where))

    sbp = _read_sbp(lines)
    result.findings.extend(sbp)
    if not sbp:
        result.missing.append(Missing("SBP cost (the survivor benefit premium)",
                                      "the 'Survivor Benefits' page"))

    crdp = _read_crdp(lines)
    result.findings.extend(crdp)

    gross = result.get("retired_pay_monthly")
    va = result.get("va_disability_monthly")
    if (gross and gross.applicable and va and va.applicable
            and float(va.value) > float(gross.value)):
        result.warnings.append(
            f"The VA waiver read here ({_fmt_money(float(va.value))}) is larger "
            f"than the gross retired pay ({_fmt_money(float(gross.value))}). A "
            f"waiver cannot exceed the pay it reduces, so one of the two was "
            f"misread.")
        for f in (gross, va):
            f.status = CONFLICT
            f.confidence = LOW


# --------------------------------------------------------------------------
# Applying, which only ever happens because a person asked for it
# --------------------------------------------------------------------------
def apply_findings(result: ParseResult, household, fields) -> list:
    """
    Write the chosen findings into a Household. Returns what changed, as text.

    Only fields named in `fields` are written, and only if the finding is
    applicable. The caller is responsible for mark_dirty() and invalidate() --
    this module knows nothing about Streamlit.
    """
    wanted = set(fields or ())
    applied = []
    for f in result.findings:
        if not f.applicable or f.field not in wanted:
            continue
        target = household if f.target == TARGET_HOUSEHOLD else household.member
        if not hasattr(target, f.field):
            continue
        before = getattr(target, f.field)
        setattr(target, f.field, f.value)
        changed = _differs(before, f.value)
        applied.append(f"{f.label}: {f.display}"
                       + (f" (was {before})" if changed and before not in
                          (None, "", 0, 0.0, False) else ""))
    return applied


def _differs(before, after) -> bool:
    if isinstance(before, (int, float)) and isinstance(after, (int, float)) \
            and not isinstance(before, bool) and not isinstance(after, bool):
        return abs(float(before) - float(after)) > 1e-9
    return before != after
