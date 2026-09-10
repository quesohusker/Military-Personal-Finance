"""
Statement ingest: the ending balance, and nothing else.

Every statement here is SYNTHETIC -- invented layouts, invented names,
invented account numbers, invented amounts. None of it came from a real
institution's document. The layouts imitate the SHAPES real statements take
(a summary block with beginning and ending lines, a combined statement with
two accounts, a brokerage statement with a holdings table) so the parser can
be tested against the traps those shapes set.
"""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from engine.profile import Household
from engine.ingest import statements as S


# ==========================================================================
# Synthetic statements
# ==========================================================================

CHECKING = """SYNTHETIC SAMPLE BANK -- NOT A REAL STATEMENT
Statement Period: 02/01/2026 - 02/28/2026
Account Number: 0123456789
Jane Q. Sample
123 Any Street, Anytown ST 00000

Free Checking
Beginning Balance                          $1,234.56
Deposits and Other Credits                 $3,500.00
Withdrawals and Other Debits               $2,900.12
Ending Balance                             $1,834.44

Daily Balance Summary
02/03    $4,734.56
02/15    $2,101.09
"""

COMBINED = """USAA FEDERAL SAVINGS BANK  (synthetic layout)
Statement Period: 02/01/2026 - 02/28/2026
Account Summary

USAA CLASSIC CHECKING   Account Number: 0123456789
Beginning Balance   $1,234.56
Ending Balance      $1,834.44

USAA SAVINGS   Account Number: 0987654321
Beginning Balance   $10,000.00
Ending Balance      $10,125.00
"""

SUMMARY_TABLE = """Navy Federal Credit Union (synthetic layout)
Statement of Account   Statement Date: 03/31/2026
Summary of Accounts
Account                 Number      Beginning Balance   Ending Balance
Active Duty Checking    ****1234    1,234.56            1,834.44
Basic Savings           ****5678    10,000.00           10,125.00
Visa Signature          ****9999    500.00              650.00
"""

BROKERAGE = """Fidelity Investments (synthetic layout)
Statement Period  03/01/2026 to 03/31/2026
INDIVIDUAL - TOD   Account Number: Z12-345678

Account Summary                    This Period      Year-to-Date
Beginning Net Account Value        $165,000.00      $150,000.00
Change in Investment Value          $7,345.67       $22,345.67
Ending Net Account Value          $172,345.67      $172,345.67

Holdings
Description        Quantity     Price      Market Value    Cost Basis
VTSAX             1,234.567   $118.50     $146,296.19     $100,000.00
VBTLX             2,000.000     $9.85      $19,700.00      $20,500.00
Total Holdings                              $165,996.19
Core Cash (SPAXX)                            $6,349.48
"""

ROTH = """Vanguard (synthetic layout)
Roth IRA Brokerage Account - 12345678
Balance on 12/31/2025     $40,000.00
Balance on 03/31/2026     $42,500.00
Total account value as of 03/31/2026: $42,500.00
"""

CREDIT_CARD = """Sample Card Services (synthetic layout)
Visa Platinum   Account ending in 4242
Previous Balance        $500.00
New Balance             $650.00
Minimum Payment Due      $25.00
Payment Due Date    04/25/2026
"""

CSV_ACCOUNTS = (
    "Account Name,Account Number,Account Type,Ending Balance\n"
    'Everyday Checking,1234567890,Checking,"$2,345.67"\n'
    'Way2Save Savings,9876543210,Savings,"15,000.00"\n'
    'Platinum Card,4111111111111111,Credit Card,"1,200.00"\n'
)

CSV_TRANSACTIONS = (
    "Date,Description,Amount,Balance\n"
    "03/03/2026,DFAS-CLEVELAND PAY,2500.00,4000.00\n"
    "03/01/2026,RENT,-1500.00,1500.00\n"
    "03/15/2026,DFAS-CLEVELAND PAY,2500.00,6500.00\n"
)

CSV_HOLDINGS = (
    "Account Number,Account Name,Symbol,Description,Quantity,Last Price,Current Value\n"
    'Z12345678,Individual,VTSAX,TOTAL STOCK INDEX,1234.567,118.50,"$146,296.19"\n'
    'Z12345678,Individual,SPAXX,GOVT MONEY MARKET,6349.48,1.00,"$6,349.48"\n'
    "Z12345678,Individual,Pending Activity,,,,\n"
    'Z87654321,Roth IRA,FXAIX,500 INDEX,100,200.00,"$20,000.00"\n'
)

GARBLED = "asdf qwer 12 34 zxcv\n%%%% $$$$ \nlorem ipsum dolor sit amet\n\x00\x01\x02\n"


def _minimal_pdf(lines: list[str]) -> bytes:
    """
    A hand-built one-page PDF with plain Helvetica text, so the PDF path can
    be exercised without any file on disk. Synthetic by construction.
    """
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = ("BT /F1 11 Tf 50 750 Td 14 TL "
               + " ".join(f"({esc(ln)}) Tj T*" for ln in lines) + " ET")
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


# ==========================================================================
# The ending balance, not the opening one
# ==========================================================================

def test_checking_statement_takes_the_ending_balance_only():
    """Opening balance, deposits, withdrawals and daily balances all sit on
    the same page. Only the ending balance may come out."""
    res = S.parse_text(CHECKING)
    assert res.ok and len(res.accounts) == 1
    c = res.accounts[0]
    assert c.ending_balance == pytest.approx(1_834.44)
    assert c.account_kind == S.KIND_CHECKING
    assert c.matched_phrase == "ending balance"
    assert c.target == S.TARGET_CASH
    assert c.preselected
    for value, _, _ in c.all_values():
        assert value not in (1_234.56, 3_500.00, 2_900.12, 4_734.56, 2_101.09)


def test_statement_date_is_the_end_of_the_period():
    res = S.parse_text(CHECKING)
    assert res.statement_date == "2026-02-28"
    assert res.accounts[0].statement_date == "2026-02-28"


def test_header_account_number_is_attached_masked():
    res = S.parse_text(CHECKING)
    c = res.accounts[0]
    assert c.account_last4 == "6789"
    assert "****6789" in c.account_label
    assert "0123456789" not in c.account_label


def test_beginning_and_ending_on_one_line_still_takes_ending():
    res = S.parse_text("Sample Bank\nSavings Account ending in 4321\n"
                       "Beginning Balance $1,000.00 Ending Balance $1,050.00\n")
    assert res.accounts[0].ending_balance == pytest.approx(1_050.00)
    assert res.accounts[0].account_last4 == "4321"


def test_a_previous_label_on_the_same_line_does_not_poison_the_match():
    """'Total Deposits $3,500.00 Ending Balance $1,834.44' on one line."""
    res = S.parse_text("Sample Bank\nChecking ****1234\n"
                       "Total Deposits $3,500.00 Ending Balance $1,834.44\n")
    assert res.accounts[0].ending_balance == pytest.approx(1_834.44)


def test_pdf_extraction_that_squashes_spaces_still_matches():
    res = S.parse_text("Sample Bank\nChecking\nBeginningBalance 100.00\n"
                       "EndingBalance 200.00\n")
    assert res.accounts[0].ending_balance == pytest.approx(200.00)


def test_value_on_the_line_after_the_label_is_found_less_confidently():
    same = S.parse_text("Sample Bank\nChecking ****1111\nEnding Balance $700.00\n")
    below = S.parse_text("Sample Bank\nChecking ****1111\nEnding Balance\n$700.00\n")
    assert below.accounts[0].ending_balance == pytest.approx(700.00)
    assert below.accounts[0].confidence < same.accounts[0].confidence


def test_weak_phrase_is_offered_but_not_preselected():
    res = S.parse_text("Sample Bank\nSavings ****9999\nCurrent Balance $3,000.00\n")
    assert res.ok
    assert res.accounts[0].ending_balance == pytest.approx(3_000.00)
    assert not res.accounts[0].preselected


# ==========================================================================
# Combined statements: one row per account
# ==========================================================================

def test_combined_statement_yields_two_accounts():
    res = S.parse_text(COMBINED)
    assert res.institution == "USAA"
    assert len(res.accounts) == 2
    by_kind = {c.account_kind: c for c in res.accounts}
    assert by_kind[S.KIND_CHECKING].ending_balance == pytest.approx(1_834.44)
    assert by_kind[S.KIND_SAVINGS].ending_balance == pytest.approx(10_125.00)
    assert by_kind[S.KIND_CHECKING].account_last4 == "6789"
    assert by_kind[S.KIND_SAVINGS].account_last4 == "4321"
    assert all(c.target == S.TARGET_CASH for c in res.accounts)


def test_summary_table_reads_the_ending_column_and_skips_the_card():
    """A beginning/ending table: the ending column, per row, and the Visa row
    is a liability so it is not offered at all."""
    res = S.parse_text(SUMMARY_TABLE)
    assert res.institution == "Navy Federal Credit Union"
    assert res.statement_date == "2026-03-31"
    assert len(res.accounts) == 2
    by_kind = {c.account_kind: c for c in res.accounts}
    assert by_kind[S.KIND_CHECKING].ending_balance == pytest.approx(1_834.44)
    assert by_kind[S.KIND_SAVINGS].ending_balance == pytest.approx(10_125.00)
    assert not any(c.ending_balance == 650.00 for c in res.accounts)


def test_two_accounts_aimed_at_cash_are_summed():
    res = S.parse_text(COMBINED)
    h = Household()
    decisions = [S.Decision(c, c.target) for c in res.accounts]
    changes = S.plan_changes(h, decisions)
    assert len(changes) == 1
    assert changes[0].target == S.TARGET_CASH
    assert changes[0].after == pytest.approx(1_834.44 + 10_125.00)
    assert h.cash_savings == 0.0          # planning changes nothing


# ==========================================================================
# Brokerage: the total, never a holding
# ==========================================================================

def test_brokerage_total_is_taken_and_no_holding_is():
    res = S.parse_text(BROKERAGE)
    assert res.institution == "Fidelity"
    assert len(res.accounts) == 1
    c = res.accounts[0]
    assert c.account_kind == S.KIND_BROKERAGE
    assert c.ending_balance == pytest.approx(172_345.67)
    assert c.target == S.TARGET_BROKERAGE
    assert c.preselected
    holdings = (146_296.19, 19_700.00, 100_000.00, 20_500.00, 118.50, 9.85)
    for value, _, _ in c.all_values():
        assert value not in holdings
    # The beginning value and the YTD change are not offered either.
    for value, _, _ in c.all_values():
        assert value not in (165_000.00, 150_000.00, 7_345.67, 22_345.67)


def test_total_holdings_is_only_ever_an_alternate():
    """'Total Holdings' excludes cash. It is reported, ranked below the account
    value, and never chosen over it."""
    res = S.parse_text(BROKERAGE)
    c = res.accounts[0]
    alts = {(a.phrase, round(a.value, 2)) for a in c.alternates}
    assert ("total holdings", 165_996.19) in alts
    assert all(a.confidence < c.confidence for a in c.alternates)


def test_roth_heading_redirects_the_default_target():
    res = S.parse_text(ROTH)
    c = res.accounts[0]
    assert c.ending_balance == pytest.approx(42_500.00)
    assert c.target == S.TARGET_ROTH_IRA
    assert c.account_last4 == "5678"
    # The stale prior-quarter figure is an alternate, not the answer.
    assert any(a.value == pytest.approx(40_000.00) for a in c.alternates)


def test_brokerage_value_table_defaults_to_brokerage():
    text = ("Fidelity (synthetic)\nAccount Summary\n"
            "Account   Number   Beginning Value   Ending Value\n"
            "Individual - TOD   Z12-345678   $165,000.00   $172,345.67\n"
            "Roth IRA   Z98-765432   $40,000.00   $42,500.00\n")
    res = S.parse_text(text)
    assert len(res.accounts) == 2
    vals = sorted(c.ending_balance for c in res.accounts)
    assert vals == pytest.approx([42_500.00, 172_345.67])
    assert all(c.account_kind == S.KIND_BROKERAGE for c in res.accounts)
    targets = {c.account_last4: c.target for c in res.accounts}
    assert targets["5678"] == S.TARGET_BROKERAGE
    assert targets["5432"] == S.TARGET_ROTH_IRA


# ==========================================================================
# CSV
# ==========================================================================

def test_csv_with_a_balance_column_is_the_easy_case():
    res = S.parse(CSV_ACCOUNTS.encode("utf-8"), "accounts.csv")
    assert res.source_kind == S.SOURCE_CSV
    assert len(res.accounts) == 2
    by_kind = {c.account_kind: c for c in res.accounts}
    assert by_kind[S.KIND_CHECKING].ending_balance == pytest.approx(2_345.67)
    assert by_kind[S.KIND_SAVINGS].ending_balance == pytest.approx(15_000.00)
    assert all(c.preselected for c in res.accounts)
    # The credit card row is refused, and says why.
    assert len(res.rejected) == 1
    assert res.rejected[0].value == pytest.approx(1_200.00)
    assert "owed" in res.rejected[0].reason


def test_csv_column_matching_tolerates_case_and_spacing():
    text = ("  ACCOUNT  TYPE , Ending_Balance \n"
            "Savings, 5000.00\n")
    res = S.parse_csv(text)
    assert res.ok
    assert res.accounts[0].ending_balance == pytest.approx(5_000.00)
    assert res.accounts[0].account_kind == S.KIND_SAVINGS


def test_csv_without_a_balance_column_says_which_columns_it_saw():
    res = S.parse_csv("Date,Description,Amount\n03/01/2026,RENT,-1500.00\n")
    assert not res.ok
    assert any("Description" in w for w in res.warnings)


def test_transaction_csv_takes_the_running_balance_on_the_latest_date():
    """Rows are not in date order. The latest-dated row's balance wins, not
    the last row's or the first row's."""
    res = S.parse(CSV_TRANSACTIONS.encode("utf-8"), "chase_checking_export.csv")
    assert len(res.accounts) == 1
    c = res.accounts[0]
    assert c.ending_balance == pytest.approx(6_500.00)
    assert c.statement_date == "2026-03-15"
    assert res.institution == "Chase"
    assert c.account_kind == S.KIND_CHECKING       # from the file name


def test_holdings_csv_is_summed_per_account_not_read_per_row():
    res = S.parse(CSV_HOLDINGS.encode("utf-8"), "Portfolio_Positions.csv")
    assert len(res.accounts) == 2
    by_last4 = {c.account_last4: c for c in res.accounts}
    assert by_last4["5678"].ending_balance == pytest.approx(146_296.19 + 6_349.48)
    assert by_last4["4321"].ending_balance == pytest.approx(20_000.00)
    assert by_last4["4321"].target == S.TARGET_ROTH_IRA
    assert not by_last4["5678"].preselected        # a sum is checked by hand
    assert "Z12345678" not in by_last4["5678"].raw_line


def test_pasted_text_that_is_not_csv_is_parsed_as_text():
    res = S.parse(COMBINED)
    assert res.source_kind == S.SOURCE_TEXT
    assert len(res.accounts) == 2


# ==========================================================================
# PDF
# ==========================================================================

def test_pdf_bytes_are_read_from_memory():
    pytest.importorskip("pypdf")
    pdf = _minimal_pdf(["SYNTHETIC BANK", "Statement Date: 03/31/2026",
                        "Checking Account 0123456789",
                        "Beginning Balance $100.00", "Ending Balance $1,834.44"])
    res = S.parse(pdf, "statement.pdf")
    assert res.source_kind == S.SOURCE_PDF
    assert res.accounts[0].ending_balance == pytest.approx(1_834.44)
    assert res.statement_date == "2026-03-31"
    # Sniffed from the magic bytes too, with no file name at all.
    assert S.parse(pdf).accounts[0].ending_balance == pytest.approx(1_834.44)


def test_a_broken_pdf_raises_a_format_error_not_a_crash():
    pytest.importorskip("pypdf")
    with pytest.raises(S.StatementFormatError):
        S.parse(b"%PDF-1.4\nthis is not really a pdf", "x.pdf")


# ==========================================================================
# Nothing, rather than something wrong
# ==========================================================================

def test_garbled_input_yields_nothing_and_says_so():
    res = S.parse_text(GARBLED)
    assert not res.ok
    assert res.accounts == []
    assert res.warnings
    assert S.parse(b"").accounts == []
    assert S.parse("").accounts == []


def test_out_of_range_value_is_rejected_not_offered():
    res = S.parse_text("Sample Bank\nChecking Account 123456789\n"
                       "Ending Balance $75,000,000.00\n")
    assert res.accounts == []
    assert len(res.rejected) == 1
    assert res.rejected[0].value == pytest.approx(75_000_000.00)
    assert "cap" in res.rejected[0].reason


def test_negative_balance_is_rejected():
    res = S.parse_text("Sample Bank\nChecking Account 123456789\n"
                       "Ending Balance -$150.00\n")
    assert res.accounts == []
    assert res.rejected and res.rejected[0].value == pytest.approx(-150.00)


def test_credit_card_statement_offers_nothing():
    """'New Balance' on a card is what is owed. It must not become cash."""
    res = S.parse_text(CREDIT_CARD)
    assert res.accounts == []
    assert any("owed" in w.lower() for w in res.warnings)
    assert any(r.value == pytest.approx(650.00) for r in res.rejected)


def test_sanity_bounds():
    assert S.is_sane_balance(0.0)[0]
    assert S.is_sane_balance(S.MAX_BALANCE)[0]
    assert not S.is_sane_balance(S.MAX_BALANCE + 1)[0]
    assert not S.is_sane_balance(-0.01)[0]
    assert not S.is_sane_balance(float("nan"))[0]


# ==========================================================================
# Privacy: account numbers never come back whole
# ==========================================================================

def test_account_numbers_are_masked_to_the_last_four():
    masked = S.mask_account_numbers(
        "Account Number: 0123456789  Ending Balance $1,834.44  "
        "SSN 123-45-6789  card 4111-1111-1111-1111  xxxx-xxxx-1234")
    assert "0123456789" not in masked
    assert "****6789" in masked
    assert "123-45-6789" not in masked
    assert "***-**-XXXX" in masked
    assert "4111-1111-1111-1111" not in masked and "****1111" in masked
    assert "****1234" in masked
    # Money is not an account number.
    assert "$1,834.44" in masked


def test_masking_leaves_amounts_without_separators_alone():
    assert "12345678.90" in S.mask_account_numbers("total 12345678.90")
    assert "$12345678" in S.mask_account_numbers("total $12345678")


def test_nothing_echoed_carries_a_full_account_number():
    for text in (CHECKING, COMBINED, SUMMARY_TABLE, BROKERAGE, ROTH):
        res = S.parse_text(text)
        for c in res.accounts:
            for s in [c.raw_line, c.account_label] + [a.raw_line for a in c.alternates]:
                assert "0123456789" not in s and "0987654321" not in s
                assert "12345678" not in s and "345678" not in s
        for r in res.rejected:
            assert "0123456789" not in r.raw_line


def test_last_four_is_read_from_the_usual_forms():
    assert S.last4("Account Number: 0123456789") == "6789"
    assert S.last4("Active Duty Checking ****1234") == "1234"
    assert S.last4("Savings Account ending in 4321") == "4321"
    assert S.last4("Account Z12-345678") == "5678"
    assert S.last4("Checking") == ""


# ==========================================================================
# Money and dates
# ==========================================================================

def test_money_parsing_handles_statement_conventions():
    assert S.parse_money("$1,234.56") == pytest.approx(1_234.56)
    assert S.parse_money("(1,234.56)") == pytest.approx(-1_234.56)
    assert S.parse_money("1,234.56-") == pytest.approx(-1_234.56)
    assert S.parse_money("-$5.00") == pytest.approx(-5.00)
    assert S.parse_money("1234.56") == pytest.approx(1_234.56)
    assert S.parse_money("2026") is None            # a bare year is not money
    assert S.parse_money("03/31/2026") is None      # nor is a date
    assert S.parse_money("1,234.567") is None       # a share count


def test_date_on_a_balance_line_is_not_read_as_an_amount():
    toks = S.money_tokens("Balance as of 03/31/2026 $1,834.44")
    assert [round(v, 2) for v, _, _ in toks] == [1_834.44]


def test_statement_date_forms():
    assert S.detect_statement_date("Statement Period: 02/01/2026 - 02/28/2026") == "2026-02-28"
    assert S.detect_statement_date("Balances as of March 31, 2026") == "2026-03-31"
    assert S.detect_statement_date("Period ending 31 Mar 2026") == "2026-03-31"
    assert S.detect_statement_date("Payment due 04/25/2026") == ""
    assert S.detect_statement_date("nothing here") == ""


def test_institution_from_header_or_file_name():
    assert S.detect_institution("NAVY FEDERAL CREDIT UNION\nStatement") == "Navy Federal Credit Union"
    assert S.detect_institution("Charles Schwab & Co.") == "Charles Schwab"
    assert S.detect_institution("no name", "usaa_statement_2026-02.pdf") == "USAA"
    assert S.detect_institution("no name at all") == "unknown"


# ==========================================================================
# Applying: the only step that changes anything, and only on request
# ==========================================================================

def test_apply_replaces_by_default_and_can_add_instead():
    res = S.parse_text(COMBINED)
    h = Household()
    h.cash_savings = 500.0
    decisions = [S.Decision(c, c.target) for c in res.accounts]

    changes = S.apply_to_household(h, decisions)
    assert h.cash_savings == pytest.approx(1_834.44 + 10_125.00)
    assert changes[0].before == pytest.approx(500.0)

    h.cash_savings = 500.0
    S.apply_to_household(h, decisions, mode=S.MODE_ADD)
    assert h.cash_savings == pytest.approx(500.0 + 1_834.44 + 10_125.00)


def test_apply_honours_overrides_and_skips():
    res = S.parse_text(COMBINED)
    h = Household()
    checking, savings = sorted(res.accounts, key=lambda c: c.account_kind)
    decisions = [
        S.Decision(checking, S.TARGET_BROKERAGE),          # member re-targeted it
        S.Decision(savings, S.TARGET_SKIP),                # and declined this one
    ]
    S.apply_to_household(h, decisions)
    assert h.taxable_brokerage == pytest.approx(1_834.44)
    assert h.cash_savings == 0.0

    S.apply_to_household(h, [S.Decision(savings, S.TARGET_ROTH_IRA, value=9_000.0)])
    assert h.member.ira_roth_balance == pytest.approx(9_000.0)


def test_apply_writes_only_numbers_into_the_household():
    """No statement text, institution or account number may land in the plan."""
    res = S.parse_text(COMBINED)
    h = Household()
    S.apply_to_household(h, [S.Decision(c, c.target) for c in res.accounts])
    dumped = h.to_json()
    assert "USAA" not in dumped
    assert "6789" not in dumped and "4321" not in dumped
    assert "Ending Balance" not in dumped


def test_apply_refuses_an_insane_override():
    res = S.parse_text(COMBINED)
    h = Household()
    S.apply_to_household(h, [S.Decision(res.accounts[0], S.TARGET_CASH,
                                        value=S.MAX_BALANCE * 10)])
    assert h.cash_savings == 0.0


def test_every_target_has_a_label_and_a_field():
    for t in S.TARGETS:
        assert t in S.TARGET_LABELS
        if t != S.TARGET_SKIP:
            owner, attr = S.TARGET_FIELDS[t]
            h = Household()
            obj = h if owner == "household" else h.member
            assert hasattr(obj, attr)
