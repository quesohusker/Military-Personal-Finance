"""
Import Pay Statement — upload the LES or RAS instead of retyping it.

Nothing on this page writes into the profile until the user presses the button.
The parser was written without a real LES in front of it (see
engine/ingest/les.py), so the page's whole job is to show its working: the
value, the line of text it came from, and how sure it is. Anything it is not
sure of is shown unticked.

TO PUT THIS PAGE IN THE MENU, add one line to the MENU dict in
Military_Finance.py, under "General":

    _page("pages/12_Upload_LES.py", "Import Pay Statement", "📄"),

st.navigation only routes the pages it is handed, so until that line exists
this page is reachable only by running it directly.
"""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st

from ui.panel import (wkey, get_household, page_header, two_pane, input_card,
                      section, metric_row, esc, mark_dirty, invalidate)
from engine.ingest import les as ING
from engine.pay import basepay as BP

h = get_household()

page_header("📄 Import Pay Statement",
            "Upload your LES or RAS and let the app read the figures off it, "
            "rather than copying them across by hand. Nothing is applied until "
            "you say so.")

CONF_ICON = {ING.HIGH: "✅", ING.MEDIUM: "🟡", ING.LOW: "⚠️"}
CONF_WORD = {ING.HIGH: "Confident", ING.MEDIUM: "Fairly sure", ING.LOW: "Unsure"}

inputs, results = two_pane()

# ==========================================================================
# Left: give it the document.
# ==========================================================================
text = ""
error = ""

with inputs:
    with input_card("Give me the statement"):
        kind = st.radio("Which statement is it?",
                        ["Work it out", "LES (active duty)", "RAS (retiree)"],
                        key=wkey("dockind"), horizontal=False,
                        help="Leave it on 'Work it out' unless the app guesses "
                             "wrong. The two documents have different fields.")

        up = st.file_uploader("Upload the PDF from myPay, or a text file",
                              type=["pdf", "txt", "csv"],
                              key=wkey("lesup"),
                              help="The file is read in memory. It is never "
                                   "written to disk and never leaves this "
                                   "machine.")

        pasted = st.text_area("…or paste the text of the statement here",
                              key=wkey("lespaste"), height=170,
                              placeholder="BASE PAY        4110.00\n"
                                          "BAS              476.95\n"
                                          "BAH             1854.00",
                              help="Open the LES, select all, copy, paste. This "
                                   "works when a PDF will not.")

    with input_card("Privacy"):
        st.caption("Your LES has your name and the last four of your SSN on it. "
                   "This app has no server and nothing is uploaded anywhere — "
                   "the file is read from memory, is never written to disk, and "
                   "the raw text is never stored in your plan or in a saved "
                   "file. Only the short excerpts shown on the right are kept "
                   "while this page is open, and anything SSN-shaped is "
                   "stripped out of those before they are displayed.")
        st.caption("Clear the upload box and the paste box when you are done "
                   "and nothing from the document remains.")

# Read the document. A failure here is a message, never a traceback.
if up is not None:
    try:
        text = ING.read_upload(up.getvalue(), up.name)
    except ING.IngestError as e:
        error = str(e)
    except Exception as e:                      # a surprise must not kill the page
        error = (f"That file could not be read ({type(e).__name__}). Copy the "
                 f"text out of your statement and paste it into the box instead.")
elif pasted and pasted.strip():
    text = pasted

forced = {"LES (active duty)": ING.DOC_LES,
          "RAS (retiree)": ING.DOC_RAS}.get(kind, "")

# ==========================================================================
# Right: what it read, and nothing applied until the button is pressed.
# ==========================================================================
with results:
    if error:
        st.error(esc(error), icon="🚨")

    if not text:
        with section("Nothing loaded yet"):
            st.markdown("Upload a statement on the left, or paste one in.")
            st.caption("**LES** — the monthly Leave and Earnings Statement from "
                       "myPay. Gives your grade, years of service, basic pay, "
                       "BAH, BAS, your special pays and your TSP percentage.")
            st.caption("**RAS** — the Retiree Account Statement. Gives gross "
                       "retired pay, the VA waiver, your SBP cost and CRDP or "
                       "CRSC.")
            st.caption("This reader has never been tested against a real "
                       "statement — DFAS is a .mil site and this app cannot "
                       "reach it. Treat every line it produces as a proposal to "
                       "check, not as an answer. That is why nothing is applied "
                       "automatically.")
    else:
        result = ING.parse(text, doc_type=forced, table=BP.load())

        # ------------------------------------------------------------------
        # What kind of document, and how sure are we
        # ------------------------------------------------------------------
        named = {ING.DOC_LES: "Leave and Earnings Statement",
                 ING.DOC_RAS: "Retiree Account Statement"}.get(
                     result.doc_type, "Not recognised")
        metric_row([
            ("Document", named),
            ("Fields read", str(len(result.applicable))),
            ("Needs a look", str(len(result.suspect) + len(result.missing))),
        ])

        for w in result.warnings:
            st.warning(esc(w), icon="⚠️")

        # ------------------------------------------------------------------
        # The proposals
        # ------------------------------------------------------------------
        offered = [f for f in result.findings if f.applicable]
        if offered:
            with section("What it found",
                         "Tick what you want to keep. Anything the reader is "
                         "not sure of starts unticked on purpose — check it "
                         "against the paper before you tick it."):
                chosen = []
                for f in offered:
                    c1, c2 = st.columns([1, 2.1], gap="medium")
                    with c1:
                        # Streamlit keeps a keyed widget's value across reruns and
                        # ignores `value` once the key exists. If the same field
                        # comes back from a different document as a doubtful
                        # read, a box the user ticked earlier would stay ticked --
                        # exactly the thing this page exists to prevent. Folding
                        # the verdict into the key makes it a new widget, which
                        # re-reads preselect.
                        keep = st.checkbox(
                            f"{CONF_ICON.get(f.confidence, '•')}  {f.label}",
                            value=f.preselect,
                            key=wkey(f"pick_{f.field}_{f.status}_{f.confidence}"))
                        st.markdown(f"### {esc(f.display)}")
                    with c2:
                        st.caption(f"**{CONF_WORD.get(f.confidence, '')}** · "
                                   f"matched on the words "
                                   f"{esc(f.matched_on)}")
                        st.caption("Read from: " + esc(f.raw))
                        if f.note:
                            st.caption(esc(f.note))
                    if keep:
                        chosen.append(f.field)
                    st.divider()

                if st.button("Apply the ticked values to my plan",
                             key=wkey("applyles"), type="primary",
                             use_container_width=True, disabled=not chosen):
                    applied = ING.apply_findings(result, h, chosen)
                    if applied:
                        mark_dirty()
                        invalidate()
                        st.success(esc("Applied: " + "; ".join(applied)), icon="✅")
                        st.caption("Open the other pages to see the effect. "
                                   "Download your plan from the sidebar before "
                                   "you close the tab.")
                    else:
                        st.info("Nothing was applied.", icon="ℹ️")
        else:
            with section("Nothing could be read from this"):
                st.markdown("No figure on this document was clear enough to "
                            "offer. Either it is not an LES or an RAS, or the "
                            "PDF came out as one run-on line.")
                st.caption("Try pasting the text instead of uploading the PDF — "
                           "copying out of the myPay viewer usually keeps the "
                           "layout better than the download does.")

        # ------------------------------------------------------------------
        # Found, but wrong
        # ------------------------------------------------------------------
        if result.suspect:
            with section("Found, but it looks wrong",
                         "These are not offered as values. A figure outside its "
                         "plausible range is usually a misplaced decimal point "
                         "or a year-to-date column read as a monthly one."):
                for f in result.suspect:
                    st.markdown(f"**🚫 {esc(f.label)} — read as "
                                f"{esc(f.display)}**")
                    st.caption("From: " + esc(f.raw))
                    st.caption(esc(f.note))

        # ------------------------------------------------------------------
        # Read, but this app has nowhere to put it
        # ------------------------------------------------------------------
        if result.informational:
            with section("Worth knowing",
                         "Read off the statement, but this app has no field for "
                         "it. Noted here so you can use it elsewhere."):
                for f in result.informational:
                    st.markdown(f"**💡 {esc(f.label)}: {esc(f.display)}**")
                    st.caption(esc(f.note))

        # ------------------------------------------------------------------
        # What it could not find, by name
        # ------------------------------------------------------------------
        if result.missing:
            with section("What it could not find",
                         "These are still yours to type in. The reader looked "
                         "for each one by name and did not see it."):
                for miss in result.missing:
                    st.markdown(f"- **{esc(miss.label)}** — {esc(miss.where)}")

        if result.markers:
            st.caption("Recognised on the page: "
                       + esc(", ".join(result.markers)))
        st.caption(f"Read {result.n_lines} lines of text. Nothing from this "
                   f"document has been written to disk.")
