"""
Tests for reading an LES or an RAS.

EVERY DOCUMENT IN THIS FILE IS SYNTHETIC. It was typed by hand to look like the
DFAS layouts described in engine/ingest/les.py. There is no real name, no real
SSN, no real account number and no real pay in any of it -- the SSN-shaped
strings exist only so the redaction can be tested against them.

The point of these tests is not that the parser reads a clean statement. It is
that it REFUSES: refuses a number outside the plausible range, refuses to be
confident when the grade and the basic pay contradict each other, refuses to
invent anything out of a document it does not recognise, and refuses to echo
back an SSN. A pay parser that is merely usually right is worse than no parser
at all, because the user stops checking.
"""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import re

import pytest

from engine.ingest import les as L
from engine.pay import basepay as BP
from engine.profile import Household


# ==========================================================================
# Synthetic documents
# ==========================================================================
# Columns matter: the identity band is a table, so the value row below has to
# line up with the heading row above it, exactly as it does on the real form.
SYNTHETIC_LES = (
    "                    DEFENSE FINANCE AND ACCOUNTING SERVICE\n"
    "                        LEAVE AND EARNINGS STATEMENT\n"
    "\n"
    "NAME (LAST, FIRST, MI)      SOC. SEC. NO.  GRADE   PAY DATE  YRS SVC  ETS\n"
    "SYNTHETIC, SAMPLE A         ***-**-6789    E-5     200612    6        280930\n"
    "\n"
    "ENTITLEMENTS              DEDUCTIONS                ALLOTMENTS\n"
    "BASE PAY        4110.00   FEDERAL TAXES     310.20  SUPPORT      500.00\n"
    "BAS              476.95   FICA-SOC SEC      254.82  USAA         150.00\n"
    "BAH             1854.00   FICA-MEDICARE      59.60\n"
    "FSA              250.00   SGLI               31.00\n"
    "HFP/IDP          225.00   TSP               205.50\n"
    "                          MID-MONTH-PAY    2100.00\n"
    "TOT ENT         6915.95   TOT DED          2961.12  TOT ALMT     650.00\n"
    "\n"
    "                              SUMMARY\n"
    "+AMT FWD   +TOT ENT   -TOT DED   -TOT ALMT   =NET AMT   -CR FWD   =EOM PAY\n"
    "    0.00    6915.95    2961.12      650.00    3304.83      0.00    3304.83\n"
    "\n"
    "THRIFT SAVINGS PLAN (TSP)\n"
    "BASE PAY RATE   5%   BASE PAY CURRENT   205.50   SPECIAL PAY RATE   0%\n"
    "TSP YTD DEDUCTION  1027.50\n"
    "\n"
    "REMARKS:\n"
    "BAH BASED ON W/DEP, ZIP 28310\n"
    "SDP BALANCE  3500.00\n"
)

SYNTHETIC_RAS = (
    "              DEFENSE FINANCE AND ACCOUNTING SERVICE\n"
    "                   RETIREE ACCOUNT STATEMENT\n"
    "\n"
    "NAME: SYNTHETIC, SAMPLE B          SSN: XXX-XX-4321\n"
    "PAY EFFECTIVE DATE: 01 JAN 2026\n"
    "\n"
    "GROSS PAY                    4,512.00\n"
    "SBP COSTS                      293.28\n"
    "VA WAIVER                    1,100.00\n"
    "CRDP                           950.00\n"
    "FEDERAL TAX WITHHELD           410.00\n"
    "NET PAY                      2,758.72\n"
)

GARBLED = (
    "Grocery list for the weekend\n"
    "milk 2 gallons, eggs one dozen, coffee\n"
    "call the plumber about the upstairs tap\n"
    "library books due on the 14th\n"
    "%PDF fragment 0000000 obj endobj xref trailer\n"
)


def _les_with(replacement_of: str, replacement: str) -> str:
    assert replacement_of in SYNTHETIC_LES
    return SYNTHETIC_LES.replace(replacement_of, replacement)


@pytest.fixture(scope="module")
def table():
    """The installed basic pay table, injected so the cross-check is testable."""
    return BP.load()


# ==========================================================================
# A clean LES
# ==========================================================================
def test_clean_les_is_recognised_as_an_les():
    r = L.parse(SYNTHETIC_LES)
    assert r.doc_type == L.DOC_LES
    assert r.doc_type_confidence == L.HIGH


def test_clean_les_reads_the_pay_figures(table):
    r = L.parse(SYNTHETIC_LES, table=table)

    assert r.get("basic_pay_monthly_override").value == pytest.approx(4110.00)
    assert r.get("bah_monthly_override").value == pytest.approx(1854.00)
    assert r.get("bas_monthly_override").value == pytest.approx(476.95)
    # The TSP rate is stored as a fraction of basic pay, not as "5".
    assert r.get("tsp_contribution_pct").value == pytest.approx(0.05)
    assert r.get("sdp_balance").value == pytest.approx(3500.00)


def test_clean_les_reads_the_identity_table_by_column(table):
    """GRADE and YRS SVC are headings with values on the row beneath."""
    r = L.parse(SYNTHETIC_LES, table=table)
    assert r.get("grade").value == "E-5"
    assert r.get("years_of_service").value == pytest.approx(6.0)


def test_clean_les_reads_dependents_and_the_bah_zip(table):
    r = L.parse(SYNTHETIC_LES, table=table)
    assert r.get("has_dependents").value is True
    assert r.get("duty_zip").value == "28310"
    # Neither is certain enough to tick on the user's behalf.
    assert not r.get("has_dependents").preselect
    assert not r.get("duty_zip").preselect


def test_special_pay_sums_only_the_other_entitlements(table):
    """
    FSA and HFP/IDP, and nothing from the deductions column beside them.

    Federal tax, FICA, SGLI and the TSP deduction all sit on the same physical
    lines. Summing them in would be silent and enormous.
    """
    r = L.parse(SYNTHETIC_LES, table=table)
    f = r.get("special_pay_monthly")
    assert f.value == pytest.approx(475.00)          # 250.00 + 225.00
    assert "FSA" in f.raw and "HFP/IDP" in f.raw
    assert "FEDERAL" not in f.raw.upper()
    assert "SGLI" not in f.raw.upper()
    # A judgement call about which lines belong is never high confidence.
    assert f.confidence != L.HIGH
    assert not f.preselect


def test_year_to_date_lines_are_never_taken_as_monthly(table):
    """The YTD twin of every figure is the failure that does real damage."""
    r = L.parse(SYNTHETIC_LES, table=table)
    for f in r.findings:
        assert "YTD" not in (f.raw or "").upper()
    assert r.get("basic_pay_monthly_override").value < 10_000


def test_the_tsp_block_is_not_mistaken_for_basic_pay(table):
    """BASE PAY RATE and BASE PAY CURRENT are not basic pay."""
    r = L.parse(SYNTHETIC_LES, table=table)
    pay = r.get("basic_pay_monthly_override")
    assert pay.value == pytest.approx(4110.00)
    assert "RATE" not in pay.raw.upper()


def test_a_clean_les_ticks_the_certain_fields_only(table):
    r = L.parse(SYNTHETIC_LES, table=table)
    ticked = set(r.preselected_fields)
    assert "basic_pay_monthly_override" in ticked
    assert "bah_monthly_override" in ticked
    assert "grade" in ticked
    # Inferred or summed values are shown, but the user has to tick them.
    assert "special_pay_monthly" not in ticked
    assert "has_dependents" not in ticked
    assert "duty_zip" not in ticked


def test_applying_writes_only_what_was_asked_for(table):
    r = L.parse(SYNTHETIC_LES, table=table)
    h = Household()
    h.member.grade = "E-1"
    h.member.special_pay_monthly = 0.0

    changed = L.apply_findings(r, h, ["grade", "basic_pay_monthly_override"])

    assert h.member.grade == "E-5"
    assert h.member.basic_pay_monthly_override == pytest.approx(4110.00)
    assert h.member.special_pay_monthly == 0.0        # not asked for, not written
    assert h.member.bah_monthly_override == 0.0
    assert len(changed) == 2


def test_applying_nothing_changes_nothing(table):
    r = L.parse(SYNTHETIC_LES, table=table)
    h = Household()
    before = h.to_json()
    assert L.apply_findings(r, h, []) == []
    assert h.to_json() == before


# ==========================================================================
# A clean RAS
# ==========================================================================
def test_clean_ras_is_recognised_and_read():
    r = L.parse(SYNTHETIC_RAS)
    assert r.doc_type == L.DOC_RAS
    assert r.get("retired_pay_monthly").value == pytest.approx(4512.00)
    assert r.get("va_disability_monthly").value == pytest.approx(1100.00)


def test_ras_gross_pay_is_taken_and_not_net_pay():
    """A retiree quoting their own statement will quote the net."""
    r = L.parse(SYNTHETIC_RAS)
    assert r.get("retired_pay_monthly").value != pytest.approx(2758.72)


def test_ras_sbp_cost_turns_the_election_on_and_reports_the_premium():
    r = L.parse(SYNTHETIC_RAS)
    assert r.get("sbp_elected").value is True

    premium = [f for f in r.informational if "SBP premium" in f.label]
    assert len(premium) == 1
    assert premium[0].value == pytest.approx(293.28)
    assert not premium[0].applicable          # this app has no field for it
    # 6.5% of the base amount, so the base amount implied here is the full
    # gross pay -- worth saying, because it is the number the app does ask for.
    assert "4,512" in premium[0].note


def test_ras_crdp_line_sets_the_flag_and_reports_the_amount():
    r = L.parse(SYNTHETIC_RAS)
    assert r.get("crdp_applies").value is True
    amounts = [f for f in r.informational if "CRDP restored" in f.label]
    assert amounts and amounts[0].value == pytest.approx(950.00)


def test_ras_crsc_absent_is_not_reported_as_missing():
    r = L.parse(SYNTHETIC_RAS)
    assert not any("CRSC" in m.label for m in r.missing)


def test_a_va_waiver_larger_than_gross_pay_is_flagged():
    text = SYNTHETIC_RAS.replace("VA WAIVER                    1,100.00",
                                 "VA WAIVER                    5,100.00")
    r = L.parse(text)
    assert any("waiver" in w.lower() for w in r.warnings)
    assert not r.get("retired_pay_monthly").preselect
    assert not r.get("va_disability_monthly").preselect


# ==========================================================================
# Garbled input yields nothing, not nonsense
# ==========================================================================
def test_garbled_input_yields_no_values_at_all():
    r = L.parse(GARBLED)
    assert r.doc_type == L.DOC_UNKNOWN
    assert r.applicable == []
    assert r.found_nothing
    assert any("does not look like" in w for w in r.warnings)


def test_garbled_input_still_says_what_it_could_not_find():
    r = L.parse(GARBLED)
    labels = " | ".join(m.label for m in r.missing)
    for expected in ("Basic pay", "BAH", "BAS", "Pay grade", "Years of service"):
        assert expected in labels
    assert all(m.where for m in r.missing)


def test_empty_input_is_not_an_error():
    r = L.parse("")
    assert r.found_nothing
    assert r.applicable == []


def test_an_unidentified_document_is_never_confident(table):
    """A pasted fragment can still be read, but nothing gets ticked for you."""
    fragment = "BASE PAY 4110.00\nBAH 1854.00\n"
    r = L.parse(fragment, table=table)
    assert r.doc_type == L.DOC_UNKNOWN
    assert r.get("basic_pay_monthly_override").value == pytest.approx(4110.00)
    assert r.preselected_fields == []


# ==========================================================================
# Out-of-range values are reported, never offered
# ==========================================================================
def test_a_decimal_slip_in_bas_is_refused(table):
    """$47,695 is a misplaced decimal point, not a subsistence allowance."""
    text = _les_with("BAS              476.95", "BAS            47695.00")
    r = L.parse(text, table=table)
    f = r.get("bas_monthly_override")
    assert f.status == L.SUSPECT
    assert f.value is None
    assert not f.applicable and not f.preselect
    assert "47,695" in f.display
    assert "outside" in f.note


def test_a_year_to_date_basic_pay_is_refused(table):
    """Twelve months of basic pay in the basic pay slot must not be applied."""
    text = _les_with("BASE PAY        4110.00", "BASE PAY       49320.00")
    r = L.parse(text, table=table)
    f = r.get("basic_pay_monthly_override")
    assert f.status == L.SUSPECT
    assert f.value is None
    assert "basic_pay_monthly_override" not in r.preselected_fields


def test_an_impossible_tsp_percentage_is_refused(table):
    text = _les_with("BASE PAY RATE   5%", "BASE PAY RATE  205%")
    r = L.parse(text, table=table)
    f = r.get("tsp_contribution_pct")
    assert f.status == L.SUSPECT and f.value is None


def test_a_refused_value_cannot_be_applied_even_if_asked_for(table):
    text = _les_with("BAS              476.95", "BAS            47695.00")
    r = L.parse(text, table=table)
    h = Household()
    assert L.apply_findings(r, h, ["bas_monthly_override"]) == []
    assert h.member.bas_monthly_override == 0.0


# ==========================================================================
# The grade / basic pay cross-check
# ==========================================================================
def test_grade_and_basic_pay_agree_on_a_clean_les(table):
    agrees, message, expected = L.cross_check_grade_and_pay("E-5", 6.0, 4110.00,
                                                            table=table)
    assert agrees is True
    assert expected == pytest.approx(4110.00)


def test_the_cross_check_fires_when_grade_and_basic_pay_disagree(table):
    """An E-5 with six years is not paid $9,999 a month, whatever the page says."""
    text = _les_with("BASE PAY        4110.00", "BASE PAY        9999.00")
    r = L.parse(text, table=table)

    assert any("E-5" in w and "9,999" in w for w in r.warnings)
    pay = r.get("basic_pay_monthly_override")
    grade = r.get("grade")
    assert pay.status == L.CONFLICT and grade.status == L.CONFLICT
    # In range, so still offered -- but never ticked on the user's behalf.
    assert pay.applicable and not pay.preselect
    assert not grade.preselect


def test_the_cross_check_fires_when_the_grade_is_misread(table):
    """The same disagreement, arrived at from the other side."""
    text = _les_with("E-5     200612", "O-6     200612")
    r = L.parse(text, table=table)
    assert r.get("grade").value == "O-6"
    assert any("O-6" in w for w in r.warnings)


def test_the_cross_check_works_without_years_of_service(table):
    """With no YRS SVC the grade's whole scale is the test."""
    agrees, message, _ = L.cross_check_grade_and_pay("E-5", None, 4110.00,
                                                     table=table)
    assert agrees is True
    agrees, message, _ = L.cross_check_grade_and_pay("E-5", None, 17_500.00,
                                                     table=table)
    assert agrees is False
    assert "E-5" in message


def test_the_cross_check_declines_rather_than_guesses_without_a_table():
    agrees, message, _ = L.cross_check_grade_and_pay("E-5", 6.0, 4110.00, table=None)
    # Either there is no table installed (agrees is None) or there is one and
    # it agrees. What must never happen is a false disagreement.
    assert agrees in (None, True)


def test_bas_paid_at_the_wrong_rate_for_the_grade_is_noted(table):
    """
    Enlisted BAS is the HIGHER of the two rates. An officer showing the
    enlisted rate is worth a sentence, not a rejection -- BAS II and a
    part-month both produce legitimate mismatches.
    """
    text = _les_with("E-5     200612", "O-3     200612")
    r = L.parse(text, table=table)
    f = r.get("bas_monthly_override")
    assert f.value == pytest.approx(476.95)      # still offered
    assert f.confidence != L.HIGH
    assert "enlisted" in f.note.lower()


# ==========================================================================
# Privacy
# ==========================================================================
@pytest.mark.parametrize("line, leak", [
    ("SOC. SEC. NO. 123-45-6789", "6789"),
    ("SSN ***-**-6789", "6789"),
    ("SOC SEC NO XXX-XX-6789", "6789"),
    ("ID 123456789 GRADE E-5", "123456789"),
    ("SSN: 6789", "6789"),
    ("DOD ID 1234567890", "1234567890"),
])
def test_redact_removes_anything_ssn_shaped(line, leak):
    out = L.redact(line)
    assert leak not in out
    assert L.REDACTED in out


def test_redact_leaves_pay_figures_alone():
    line = "BASE PAY 4110.00  BAH 1,854.00  PAY DATE 20060612"
    assert L.redact(line) == line


def test_redaction_does_not_eat_the_social_security_deduction():
    """
    FICA-SOC SEC is a deduction label, not an SSN label.

    Over-redacting here is not harmless: the excerpt is the only thing the user
    has to check the parser against, and blanking half of it hides the error we
    are asking them to look for.
    """
    line = "BAS              476.95   FICA-SOC SEC      254.82"
    assert L.redact(line) == line


def test_nothing_ssn_shaped_survives_into_a_finding(table):
    r = L.parse(SYNTHETIC_LES, table=table)
    for f in r.findings:
        blob = f"{f.raw} {f.note} {f.display} {f.matched_on}"
        assert "6789" not in blob
        assert "***-**" not in blob


def test_the_members_name_is_never_echoed_back(table):
    """The identity band is read by column, so only the cell is quoted."""
    r = L.parse(SYNTHETIC_LES, table=table)
    for f in r.findings:
        assert "SAMPLE" not in (f.raw or "").upper()
        assert "SYNTHETIC" not in (f.raw or "").upper()


def test_the_result_keeps_no_copy_of_the_document(table):
    """
    Nothing that reaches a saved plan may carry the statement's text.

    The whole document is 25 lines; the excerpts a ParseResult carries must add
    up to a small fraction of it, and none of them may be the identity band.
    """
    r = L.parse(SYNTHETIC_LES, table=table)
    carried = sum(len(f.raw) for f in r.findings)
    assert carried < len(SYNTHETIC_LES) / 2
    assert not hasattr(r, "text")


# ==========================================================================
# Getting text out of an upload
# ==========================================================================
def test_a_text_upload_is_decoded_not_written_to_disk():
    text = L.read_upload(SYNTHETIC_LES.encode("utf-8"), "les.txt")
    assert "BASE PAY" in text


def test_a_latin1_paste_still_decodes():
    assert "BASE PAY" in L.read_upload("BASE PAY 4110.00\n".encode("cp1252"),
                                       "les.txt")


def test_an_empty_file_fails_with_a_message_not_a_traceback():
    with pytest.raises(L.IngestError):
        L.read_upload(b"", "les.pdf")


def test_a_broken_pdf_fails_with_a_message_not_a_traceback():
    """Whatever pypdf throws, the user sees a sentence telling them to paste."""
    with pytest.raises(L.IngestError) as exc:
        L.read_upload(b"%PDF-1.4 this is not really a pdf", "les.pdf")
    assert "paste" in str(exc.value).lower()


def test_doc_type_can_be_forced_when_the_caller_knows(table):
    r = L.parse(SYNTHETIC_RAS, doc_type=L.DOC_RAS)
    assert r.doc_type == L.DOC_RAS
    r = L.parse(SYNTHETIC_LES, doc_type=L.DOC_LES, table=table)
    assert r.doc_type == L.DOC_LES


# ==========================================================================
# Tolerance of how the same statement can arrive
# ==========================================================================
@pytest.mark.parametrize("line", [
    "BASE PAY 4110.00",
    "BASE PAY  4,110.00",
    "base pay      4110.00",
    "BASE PAY....... $4,110.00",
    "BASE PAY\t4110.00",
])
def test_basic_pay_is_read_however_it_is_spaced_and_cased(line, table):
    r = L.parse(f"LEAVE AND EARNINGS STATEMENT\nENTITLEMENTS\n{line}\n",
                table=table)
    assert r.get("basic_pay_monthly_override").value == pytest.approx(4110.00)


def test_bas_is_not_matched_inside_base_pay(table):
    """The three letters collide, and getting this wrong makes BAS $4,110."""
    r = L.parse("LEAVE AND EARNINGS STATEMENT\nENTITLEMENTS\nBASE PAY 4110.00\n",
                table=table)
    assert r.get("bas_monthly_override") is None
    assert any("BAS" in m.label for m in r.missing)


def test_bah_diff_is_not_mistaken_for_bah(table):
    """BAH-DIFF is child-support related and is a couple of hundred dollars."""
    r = L.parse("LEAVE AND EARNINGS STATEMENT\nENTITLEMENTS\n"
                "BAH-DIFF          123.30\n", table=table)
    f = r.get("bah_monthly_override")
    assert f is None or f.value != pytest.approx(123.30)


def test_a_zip_in_the_remarks_is_never_read_as_a_housing_allowance(table):
    """
    A remarks ZIP is a five-digit number sitting right after the word BAH.

    Most ZIPs are out of range and get caught, but an east-coast one -- 02138,
    say -- reads as $2,138 a month and is entirely believable.
    """
    text = _les_with("ZIP 28310", "ZIP 02138")
    r = L.parse(text, table=table)
    assert r.get("bah_monthly_override").value == pytest.approx(1854.00)
    assert r.get("bah_monthly_override").confidence == L.HIGH
    assert r.get("duty_zip").value == "02138"


# ==========================================================================
# When the PDF throws the column spacing away
# ==========================================================================
def _collapsed(text: str) -> str:
    """What plain text extraction does to a three-column form."""
    return "\n".join(re.sub(r" {2,}", " ", ln) for ln in text.split("\n"))


def test_a_collapsed_layout_still_reads_the_entitlements_column(table):
    """
    With the spacing gone the column offsets are meaningless.

    Slicing on them anyway cuts an amount in half -- $1,854.00 becomes $1.8 --
    so the line has to be read whole and only its leftmost pair taken.
    """
    r = L.parse(_collapsed(SYNTHETIC_LES), table=table)
    assert r.get("basic_pay_monthly_override").value == pytest.approx(4110.00)
    assert r.get("bah_monthly_override").value == pytest.approx(1854.00)
    assert r.get("special_pay_monthly").value == pytest.approx(475.00)
    # Nothing from the deductions or allotments columns is in the sum.
    assert "SGLI" not in r.get("special_pay_monthly").raw.upper()
    assert "SUPPORT" not in r.get("special_pay_monthly").raw.upper()


def test_a_collapsed_layout_recovers_the_grade_but_says_it_is_unsure(table):
    r = L.parse(_collapsed(SYNTHETIC_LES), table=table)
    grade = r.get("grade")
    assert grade.value == "E-5"
    assert grade.confidence == L.MEDIUM
    assert not grade.preselect


def test_a_collapsed_layout_gives_up_on_years_of_service(table):
    """
    Nothing distinguishes YRS SVC from the other bare numbers on that row.

    Reporting it as not found is the right answer. Guessing at it is how a
    retirement projection quietly moves by a decade.
    """
    r = L.parse(_collapsed(SYNTHETIC_LES), table=table)
    assert r.get("years_of_service") is None
    assert any("Years of service" in m.label for m in r.missing)


def test_a_stacked_entitlements_block_is_read_too(table):
    """Some renderings list the entitlements down the page instead."""
    text = ("LEAVE AND EARNINGS STATEMENT\n"
            "ENTITLEMENTS\n"
            "BASE PAY        4110.00\n"
            "BAS              476.95\n"
            "BAH             1854.00\n"
            "FLIGHT PAY       250.00\n"
            "DEDUCTIONS\n"
            "FEDERAL TAXES    310.20\n"
            "SGLI              31.00\n")
    r = L.parse(text, table=table)
    f = r.get("special_pay_monthly")
    assert f.value == pytest.approx(250.00)
    assert "FLIGHT PAY" in f.raw
    assert "FEDERAL" not in f.raw.upper()


# ==========================================================================
# Forcing the document type
# ==========================================================================
def test_forcing_the_type_is_believed_and_not_downgraded(table):
    """If the user says it is their LES, stop second-guessing the fragment."""
    fragment = "BASE PAY 4110.00\nBAH 1854.00\n"
    loose = L.parse(fragment, table=table)
    told = L.parse(fragment, doc_type=L.DOC_LES, table=table)
    assert loose.preselected_fields == []
    assert "basic_pay_monthly_override" in told.preselected_fields


def test_forcing_the_wrong_type_finds_nothing_rather_than_inventing(table):
    """An LES read as an RAS has none of the RAS's fields on it."""
    r = L.parse(SYNTHETIC_LES, doc_type=L.DOC_RAS, table=table)
    assert r.applicable == []
    assert any("retired pay" in m.label.lower() for m in r.missing)


# ==========================================================================
# The PDF path, end to end
# ==========================================================================
def _synthetic_pdf(lines) -> bytes:
    """
    The smallest well-formed PDF that carries a page of text.

    Written by hand rather than fetched: it exercises read_upload() against a
    genuine PDF, which is the only way to know that the column positions the
    identity band depends on survive text extraction.
    """
    body = ["BT", "/F1 10 Tf", "12 TL", "40 740 Td"]
    for line in lines:
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        body.append(f"({escaped}) Tj T*")
    body.append("ET")
    stream = "\n".join(body).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources "
        b"<< /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += (b"trailer\n<< /Size " + str(len(objects) + 1).encode()
            + b" /Root 1 0 R >>\nstartxref\n" + str(xref_at).encode() + b"\n%%EOF\n")
    return bytes(out)


@pytest.fixture(scope="module")
def pdf_available():
    try:
        import pypdf  # noqa: F401
        return True
    except ImportError:
        try:
            import PyPDF2  # noqa: F401
            return True
        except ImportError:
            return False


def test_a_real_pdf_is_read_and_parsed(pdf_available, table):
    if not pdf_available:
        pytest.skip("no PDF library installed; the paste path covers this build")
    data = _synthetic_pdf(SYNTHETIC_LES.split("\n"))
    text = L.read_upload(data, "myLES.pdf")
    r = L.parse(text, table=table)

    assert r.doc_type == L.DOC_LES
    assert r.get("basic_pay_monthly_override").value == pytest.approx(4110.00)
    # The identity band only survives if the extractor kept the columns.
    assert r.get("grade").value == "E-5"
    assert r.get("years_of_service").value == pytest.approx(6.0)


def test_a_pdf_is_detected_by_signature_even_if_the_name_lies(pdf_available):
    if not pdf_available:
        pytest.skip("no PDF library installed")
    data = _synthetic_pdf(SYNTHETIC_LES.split("\n"))
    assert "BASE PAY" in L.read_upload(data, "les.txt")


def test_a_pdf_with_no_text_layer_says_so(pdf_available):
    """A scan or a photo of an LES has nothing in it to read."""
    if not pdf_available:
        pytest.skip("no PDF library installed")
    data = _synthetic_pdf([""])
    with pytest.raises(L.IngestError) as exc:
        L.read_upload(data, "scan.pdf")
    assert "paste" in str(exc.value).lower()
