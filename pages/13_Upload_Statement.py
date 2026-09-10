import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import hashlib
import streamlit as st
import pandas as pd

from ui.panel import (wkey, get_household, page_header, two_pane, input_card,
                      section, metric_row, fmt_money, esc, md_money,
                      mark_dirty, invalidate)
from engine.ingest import statements as S

# PRIVACY. A statement carries a name, an address and account numbers. The
# upload is held in memory for this session only: it is never written to disk
# and never sent anywhere, because this app has no server side. What is kept
# in session state is the parser's result -- matched lines with account
# numbers already reduced to their last four digits -- not the document. The
# only thing that reaches the plan is a balance the member chose to apply.

h = get_household()

page_header("🏦 Read a bank or brokerage statement",
            "Pull the closing balances off a statement you already have, instead "
            "of reading them off the page and typing them in. Nothing changes "
            "until you press Apply.")

RESULT_KEY = wkey("stmt_result")      # a ParseResult; masked lines only
SOURCE_KEY = wkey("stmt_source")      # fingerprint of what was parsed
ERROR_KEY = wkey("stmt_error")
APPLIED_KEY = wkey("stmt_applied")

MODES = {"Replace the current value": S.MODE_REPLACE,
         "Add to the current value": S.MODE_ADD}


def _confidence_word(conf: float) -> str:
    if conf >= 0.85:
        return "high"
    if conf >= S.PRESELECT_THRESHOLD:
        return "good"
    if conf >= 0.50:
        return "low"
    return "very low"


inputs, results = two_pane()

# ==========================================================================
# Left: the statement, and how to apply it.
# ==========================================================================
data, name, source_id = None, "", None

with inputs:
    with input_card("Your statement"):
        how = st.radio("How will you provide it?",
                       ["Upload a file", "Paste the text"],
                       key=wkey("stmt_how"), horizontal=True)
        if how == "Upload a file":
            up = st.file_uploader("PDF, CSV or text file", type=["pdf", "csv", "tsv", "txt"],
                                  key=wkey("stmt_file"),
                                  help="A statement PDF from the bank or brokerage, "
                                       "or a CSV download of accounts, positions or "
                                       "transactions.")
            if up is not None:
                data, name = up.getvalue(), up.name
                source_id = f"file:{name}:{hashlib.sha1(data).hexdigest()[:16]}"
        else:
            pasted = st.text_area("Paste the statement text",
                                  key=wkey("stmt_text"), height=240,
                                  placeholder="Beginning Balance      $1,234.56\n"
                                              "Ending Balance         $1,834.44",
                                  help="Open the PDF, select all, copy, paste. "
                                       "The summary block is enough; the "
                                       "transaction list is not needed.")
            if pasted.strip():
                data, name = pasted, ""
                source_id = "text:" + hashlib.sha1(pasted.encode("utf-8")).hexdigest()[:16]

        st.caption("**Read in memory only.** Nothing is written to disk or sent "
                   "anywhere — this app has no server. Account numbers are shown "
                   "as their last four digits, and only the balances you apply "
                   "are kept in the plan.")

    with input_card("How to apply it"):
        mode_label = st.radio("When a balance is applied",
                              list(MODES), key=wkey("stmt_mode"),
                              help="Replace if this statement covers everything "
                                   "in that field — all your cash, or all your "
                                   "brokerage. Add if you are entering one "
                                   "institution at a time.")
        mode = MODES[mode_label]
        st.caption("Checking, savings, money market and CDs go to **Cash and "
                   "savings**; a brokerage account goes to **Taxable "
                   "brokerage**. Change the destination on any row — a "
                   "savings account at a brokerage may be your emergency fund, "
                   "and a brokerage account may be a Roth IRA you hold there.")

# --------------------------------------------------------------------------
# Parse on selection. Memoised on a fingerprint of the input so a rerun does
# not re-read the file; a new file or edited text is parsed afresh.
# --------------------------------------------------------------------------
if data is None:
    for k in (RESULT_KEY, SOURCE_KEY, ERROR_KEY, APPLIED_KEY):
        st.session_state.pop(k, None)
elif st.session_state.get(SOURCE_KEY) != source_id:
    res, err = None, ""
    try:
        res = S.parse(data, name)
    except S.PDFSupportMissing as e:
        err = str(e)
    except S.StatementFormatError as e:
        err = str(e)
    except Exception as e:                     # never crash the page
        err = f"That could not be read: {e}"
    st.session_state[RESULT_KEY] = res
    st.session_state[SOURCE_KEY] = source_id
    st.session_state[ERROR_KEY] = err
    st.session_state.pop(APPLIED_KEY, None)

res = st.session_state.get(RESULT_KEY)
err = st.session_state.get(ERROR_KEY, "")

# ==========================================================================
# Right: what was found, where it will go, and the Apply button.
# ==========================================================================
with results:
    if err:
        st.error(esc(err), icon="🚨")

    if res is None:
        with section("What this reads"):
            st.markdown(
                "A **PDF** statement with a text layer, a **CSV** download "
                "(accounts, positions or transactions), or text **pasted** "
                "from either. One statement can carry several accounts — a "
                "combined checking-and-savings statement comes out as one row "
                "per account.")
            st.markdown(
                "The parser looks only for the **closing figure**: *ending "
                "balance*, *closing balance*, *balance as of*, *total account "
                "value*, *ending value* and their relatives. It refuses "
                "anything qualified by *beginning*, *opening*, *previous* or "
                "*change in*, ignores each holding's market value on a "
                "brokerage statement, and rejects a negative or absurd "
                "figure. Where several figures survive, all of them are shown "
                "and you choose.")
            st.markdown(
                "**Nothing is applied automatically.** Each row shows the line "
                "it came from and how confident the reading is; low-confidence "
                "rows are shown unticked. You pick the destination and press "
                "Apply.")
        with section("Privacy"):
            st.markdown(
                "The file is read in memory and never written to disk. Nothing "
                "is uploaded anywhere — there is no server behind this page. "
                "Account numbers are masked to their last four digits in "
                "everything shown here, and no statement text is stored in "
                "your plan: only the balances you choose to apply.")
        with section("If nothing is found"):
            st.markdown(
                "A scanned PDF has no text to read — paste the figures instead. "
                "A statement that uses other words for its closing balance will "
                "not match; type the balance on the **What I am worth** page.")

    else:
        with section("What was read"):
            metric_row([("Institution", res.institution),
                        ("Statement date", res.statement_date or "not found"),
                        ("Accounts found", str(len(res.accounts))),
                        ("Read as", res.source_kind.upper())])
            for w in res.warnings:
                st.warning(esc(w), icon="⚠️")
            if not res.accounts and not res.warnings:
                st.info("No account balance was recognised.", icon="ℹ️")
            elif res.accounts:
                n_pre = len(res.preselected)
                st.caption(f"{n_pre} of {len(res.accounts)} account(s) ticked "
                           f"automatically. Check every figure against the "
                           f"statement — the line it was read from is shown "
                           f"under each one.")

        decisions = []
        for i, c in enumerate(res.accounts):
            opts = c.all_values()
            with st.container(border=True):
                head = st.columns([2.2, 1.3])
                with head[0]:
                    include = st.checkbox(
                        # The masked number is asterisks; bare, they close the bold early.
                        f"**{c.account_label.replace('*', chr(92) + '*')}** — {c.institution}",
                        value=c.preselected, key=wkey(f"stmt_use_{i}"))
                    st.caption(f"{c.account_kind} · confidence "
                               f"{_confidence_word(c.confidence)} "
                               f"({c.confidence:.2f}) · matched "
                               f"“{c.matched_phrase}”")
                with head[1]:
                    st.metric("Read as", fmt_money(c.ending_balance))

                row = st.columns([1.4, 1.2, 1.2])
                with row[0]:
                    if len(opts) > 1:
                        pick = st.selectbox(
                            "Which figure?", list(range(len(opts))),
                            format_func=lambda j, o=opts: f"{fmt_money(o[j][0])} — {o[j][1]}",
                            key=wkey(f"stmt_pick_{i}"),
                            help="Other figures on the statement that matched a "
                                 "closing-balance phrase. The first is the "
                                 "parser's choice.")
                    else:
                        pick = 0
                        st.caption("Only one closing figure was found.")
                value, phrase, raw = opts[pick]
                with row[1]:
                    amount = st.number_input(
                        "Amount to apply", value=float(value), min_value=0.0,
                        max_value=S.MAX_BALANCE, step=100.0, format="%.2f",
                        key=wkey(f"stmt_amt_{i}_{pick}"),
                        help="Correct it here if the parser misread the line.")
                with row[2]:
                    target = st.selectbox(
                        "Put it in", S.TARGETS, index=S.TARGETS.index(c.target),
                        format_func=lambda t: S.TARGET_LABELS[t],
                        key=wkey(f"stmt_tgt_{i}"))

                st.caption(esc(f"Read from: “{raw}”"))
                for n in c.notes:
                    st.caption(esc(n))

                if include and target != S.TARGET_SKIP:
                    decisions.append(S.Decision(c, target, value=float(amount)))

        if res.rejected:
            with st.expander(f"{len(res.rejected)} figure(s) seen and not offered"):
                for r in res.rejected:
                    st.markdown(esc(f"- **{fmt_money(r.value)}** ({r.phrase}) — "
                                    f"{r.reason}. Line: “{r.raw_line}”"))

        if res.accounts:
            changes = S.plan_changes(h, decisions, mode)
            with section("Before you apply"):
                if not changes:
                    st.info("Tick at least one account and give it a destination "
                            "other than *Do not import*.", icon="ℹ️")
                else:
                    rows = [{"Field": ch.label, "Now": fmt_money(ch.before),
                             "After": fmt_money(ch.after),
                             "From": ", ".join(ch.sources)} for ch in changes]
                    st.dataframe(pd.DataFrame(rows), use_container_width=True,
                                 hide_index=True)
                    if any(len(ch.sources) > 1 for ch in changes):
                        st.caption("Several accounts aimed at the same field are "
                                   "added together.")
                    if mode == S.MODE_ADD:
                        st.caption("Adding to what is already there. Press Apply "
                                   "once — pressing it twice adds the statement "
                                   "twice.")

                if st.button("Apply these balances", type="primary",
                             key=wkey("stmt_apply"), disabled=not changes,
                             use_container_width=True):
                    applied = S.apply_to_household(h, decisions, mode)
                    mark_dirty(); invalidate()
                    st.session_state[APPLIED_KEY] = "; ".join(
                        f"{ch.label}: {fmt_money(ch.before)} → {fmt_money(ch.after)}"
                        for ch in applied)
                    st.rerun()

                if st.session_state.get(APPLIED_KEY):
                    st.success(esc(f"Applied — {st.session_state[APPLIED_KEY]}. "
                                   f"The plan has unsaved changes; download it "
                                   f"from the sidebar when you are done."),
                               icon="✅")

        with st.expander("How it decides"):
            strong = [p for p, c, _ in S.BALANCE_PHRASES if c >= 0.85]
            weak = [p for p, c, _ in S.BALANCE_PHRASES if c < 0.85]
            st.markdown(
                "**Taken as a closing figure:** " + ", ".join(f"*{p}*" for p in strong)
                + ".  \n**Offered, but not ticked without you:** "
                + ", ".join(f"*{p}*" for p in weak)
                + ".  \n**Never taken:** anything qualified by "
                + ", ".join(f"*{q}*" for q in S.NEGATIVE_QUALIFIERS[:12])
                + " and the like; any row of a holdings table; any figure on a "
                  "credit card or loan section; anything negative or above "
                + md_money(S.MAX_BALANCE) + ".")
