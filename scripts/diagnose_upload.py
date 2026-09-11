"""
Report what the importers make of a real document, without printing the money.

HANDOFF: "Neither has ever seen a real document -- DFAS is a .mil host. Paul's
first real upload is the actual test." This is the instrument for that test.

The app itself already shows what it read and lets you tick what to accept, so
run this only when something goes wrong and you want to say WHAT went wrong
without mailing your pay statement to anybody.

Everything it prints is document STRUCTURE -- which labels the parser keyed
off, what it found, what it went looking for and missed. **No dollar figures,
no account numbers, no raw lines.** That output is safe to paste into a chat.
Pass --show-values to include the parsed numbers, which you should only do if
you are comfortable with where the text is going.

    python3 scripts/diagnose_upload.py ~/Downloads/*.pdf
    python3 scripts/diagnose_upload.py --show-values ~/Downloads/ras.pdf

Nothing is written to your plan. This reads and reports.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.ingest import les as LES          # noqa: E402
from engine.ingest import statements as STMT  # noqa: E402

HIDDEN = "«value hidden»"

# Notes are free prose written by the parser and several of them quote a
# figure they derived -- the SBP note states an implied base amount, for one.
# Hiding the value field while printing the note in full would leak exactly
# what this script exists to keep back, so notes are masked too.
_MONEY = re.compile(r"\$\s?[\d,]+(?:\.\d+)?|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b")


def _mask(text: str, show: bool) -> str:
    """Free text with any money-shaped run removed, unless values are wanted."""
    return text if show else _MONEY.sub("«figure»", text or "")


def _rule(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def _value(finding, show: bool) -> str:
    if not show:
        return HIDDEN if finding.value is not None else "«nothing parsed»"
    return finding.display or repr(finding.value)


def diagnose_pay_statement(text: str, path: pathlib.Path, show: bool) -> None:
    doc_type, confidence, markers = LES.detect_doc_type(text)
    print(f"Document type : {doc_type} (confidence {confidence})")
    print(f"Recognised    : {', '.join(markers) if markers else 'no known markers'}")

    if doc_type == LES.DOC_UNKNOWN:
        print("\n  The parser could not tell whether this is an LES or an RAS.")
        print("  That is the first thing to report: it means the headings on")
        print("  your statement differ from the ones it looks for.")

    result = LES.parse(text, doc_type)
    print(f"Lines of text : {result.n_lines}")

    _rule("Found")
    if not result.findings:
        print("  nothing at all")
    for f in result.findings:
        flag = "ticked" if f.preselect else "      "
        print(f"  [{flag}] {f.label}")
        print(f"           field={f.field or '(informational)'} "
              f"confidence={f.confidence} status={f.status}")
        print(f"           keyed off: {f.matched_on!r}")
        print(f"           value: {_value(f, show)}")
        if f.note:
            print(f"           note: {_mask(f.note, show)}")

    _rule("Went looking for and did not find")
    for m in result.missing:
        print(f"  {m.label}  (you would type it on {m.where})" if m.where
              else f"  {m.label}")
    if not result.missing:
        print("  nothing missing")

    if result.warnings:
        _rule("Warnings")
        for w in result.warnings:
            print(f"  {_mask(str(w), show)}")


def diagnose_statement(data: bytes, path: pathlib.Path, show: bool) -> None:
    result = STMT.parse(data, path.name)
    print(f"Institution   : {result.institution}")
    print(f"Statement date: {result.statement_date or 'not found'}")
    print(f"Read as       : {result.source_kind}")
    print(f"Lines of text : {result.n_lines}")

    _rule("Accounts found")
    if not result.accounts:
        print("  none -- this is the failure to report")
    for c in result.accounts:
        flag = "ticked" if c.preselected else "      "
        print(f"  [{flag}] {c.account_label or c.account_kind}")
        print(f"           kind={c.account_kind} confidence={c.confidence:.2f} "
              f"suggested target={c.target}")
        print(f"           keyed off: {c.matched_phrase!r}")
        print(f"           balance: "
              f"{f'{c.ending_balance:,.2f}' if show else HIDDEN}")
        if c.alternates:
            print(f"           {len(c.alternates)} other number(s) on the same line")
        for n in c.notes:
            print(f"           note: {_mask(n, show)}")

    if result.rejected:
        _rule("Numbers seen and rejected")
        for r in result.rejected:
            why = getattr(r, "reason", "") or getattr(r, "why", "")
            print(f"  {_mask(str(why or r), show)}")

    if result.warnings:
        _rule("Warnings")
        for w in result.warnings:
            print(f"  {_mask(str(w), show)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="+", type=pathlib.Path)
    ap.add_argument("--show-values", action="store_true",
                    help="include the parsed numbers (they are hidden by default)")
    ap.add_argument("--balances", action="store_true",
                    help="force the bank/brokerage parser instead of the pay parser")
    args = ap.parse_args()

    for path in args.paths:
        print("\n" + "=" * 68)
        print(path.name)
        print("=" * 68)

        if not path.exists():
            print("  no such file")
            continue

        data = path.read_bytes()

        # A pay statement and a brokerage statement are different parsers. Try
        # the pay one first unless told otherwise, and fall through when the
        # document plainly is not one.
        if args.balances:
            diagnose_statement(data, path, args.show_values)
            continue

        try:
            text = LES.read_upload(data, path.name)
        except LES.IngestError as exc:
            print(f"\n  Could not get text out of it: {exc}")
            print("\n  If that says the PDF has no text layer, it is a scan or a")
            print("  photo. The paste box on the page is the fallback.")
            continue

        doc_type, _, _ = LES.detect_doc_type(text)
        if doc_type == LES.DOC_UNKNOWN:
            print("\n(not recognised as an LES or RAS -- also trying the "
                  "bank/brokerage parser)")
            diagnose_pay_statement(text, path, args.show_values)
            _rule("As a bank or brokerage statement")
            diagnose_statement(data, path, args.show_values)
        else:
            diagnose_pay_statement(text, path, args.show_values)

    print("\nNothing was written to any plan.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
