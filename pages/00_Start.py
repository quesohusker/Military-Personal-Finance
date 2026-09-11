"""
Start — the front door.

One question, asked once: where are you in your service. The answer sets the
funnel (docs/ARCHITECTURE.md §2), and the funnel decides what Intake asks and
what the Scorecard scores.

Deliberately bare. Title, crest, three buttons, and a way back into a saved
plan. No explanatory prose: the three labels ARE the question, and anyone
opening this app already knows which of the three they are. Every other page
carries its subtitle and its help text; this one earns nothing by repeating
them, and a door you have to read is a bad door.

WHY NOT `two_pane()`. Every other page is a form with a result — answers down
the left, what they mean down the right. This page has no result until the
question is answered, so the split would strand the only content in the narrow
side. One centred column instead, with a single width shared by the title, the
crest and all four buttons, so nothing on the page is a different size from
anything else.

THE FUNNEL IS NOT A PERMISSIONS SYSTEM (§2). Choosing one hides no page from
anybody; a serving member deciding whether to stay to 20 needs the retiree
pages to make that decision. It sets defaults, ordering and what gets scored.

The two example plans that used to live here have moved back to Overview,
which still carries its own copies. A door is not the place to browse samples.
"""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pathlib import Path

import streamlit as st
from streamlit.errors import StreamlitAPIException

from ui.panel import (wkey, get_household, set_household, mark_dirty,
                      invalidate)
from engine import storage
from engine.intake import FUNNEL_SPECS, set_funnel

INTAKE_PAGE = "pages/01_Intake.py"

# The crest lives beside the app rather than inside the page, so replacing the
# artwork never means editing Python. Any common image format will do: whoever
# drops the file in should not have to convert it first, or discover by way of
# a blank page that the extension was the problem.
ASSETS = Path(__file__).resolve().parent.parent / "assets"
CREST_FORMATS = ("png", "jpg", "jpeg", "webp", "svg")


def _crest() -> Path | None:
    """The first `assets/crest.*` there is, or None. Missing is not an error."""
    for ext in CREST_FORMATS:
        candidate = ASSETS / f"crest.{ext}"
        if candidate.exists():
            return candidate
    return None

# Short labels. The funnel specs carry fuller names for the rest of the app;
# on a door, two or three words each is the whole question.
SHORT = {"serving": "Currently Serving",
         "veteran": "Veteran",
         "retiree": "Retired"}

h = get_household()

# Only one rule, and only because Streamlit gives no parameter for it: the
# file uploader's dropzone is a shaded block twice a button's height with a
# size limit printed inside it, and on a door of four identical rows it is
# the loudest thing on the page. Everything else here is layout, done with
# columns and use_container_width rather than CSS — page-level CSS in this
# app has a history of dying silently against a changed selector, so the
# page must still look right if this rule stops matching.
st.markdown(
    """
    <style>
      [data-testid="stMain"] [data-testid="stFileUploaderDropzone"] {
        padding: 0; background: transparent; border: none; min-height: 0;
      }
      [data-testid="stMain"] [data-testid="stFileUploaderDropzone"] > span { width: 100%; }
      [data-testid="stMain"] [data-testid="stFileUploaderDropzone"] button { width: 100%; }
      [data-testid="stMain"] [data-testid="stFileUploaderDropzoneInstructions"] { display: none; }
    </style>
    """,
    unsafe_allow_html=True,
)

_, middle, _ = st.columns([1, 2, 1])

with middle:
    # A real heading, not styled prose: it is the page's h1 for a screen
    # reader and for the browser's outline.
    st.title("Soup Sandwich")

    crest = _crest()
    if crest is not None:
        st.image(str(crest), use_container_width=True)
    else:
        # Say where it goes rather than showing nothing: a silent absence
        # reads as a broken image to whoever clones this next.
        st.caption("Crest not found — save it as `assets/crest.png` "
                   "(`.jpg`, `.jpeg`, `.webp` and `.svg` also work).")

    st.write("")

    # The three funnels, in the order engine/funnel.py declares them. Nothing
    # here names a funnel, so a fourth spec would appear without editing this
    # page. The current choice is marked, not described.
    for f in FUNNEL_SPECS:
        if st.button(SHORT.get(f.key, f.label),
                     key=wkey(f"door_{f.key}"),
                     type="primary" if h.funnel == f.key else "secondary",
                     use_container_width=True):
            set_funnel(h, f.key)
            mark_dirty()
            invalidate()
            try:
                st.switch_page(INTAKE_PAGE)
            except StreamlitAPIException:
                # Raised when the page runs outside the router, which is how
                # the tests drive it. The funnel is already set either way.
                st.rerun()

    st.write("")

    # Coming back to a plan you already have. Two steps on purpose: selecting
    # a file must not load it, because there is no way back from the wrong one.
    up = st.file_uploader("Open a saved plan", type=["json"],
                          key=wkey("door_upload"), label_visibility="collapsed")
    if st.button("Open a saved plan", key=wkey("door_open"),
                 use_container_width=True, disabled=up is None):
        try:
            set_household(storage.from_upload_bytes(up.getvalue()))
            st.rerun()
        except (ValueError, UnicodeDecodeError) as exc:
            st.error(f"That file could not be read: {exc}")
