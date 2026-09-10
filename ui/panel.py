"""
Shared Streamlit UI: the save/load bar that appears at the top of every page,
plus input helpers that write straight back into the Household object.

The Household lives in st.session_state and is mutated in place, so a change on
one page is immediately visible on every other.
"""

from __future__ import annotations
import streamlit as st

from engine.profile import Household
from engine import storage

PROFILE_KEY = "household"
DIRTY_KEY = "unsaved_changes"
VERSION_KEY = "plan_version"

RESULT_KEYS = ("waterfall", "balance_sheet", "payoff", "projection",
               "comparison", "mc_summary", "bracket_sweep", "scenario_sweep")


def wkey(name: str) -> str:
    """
    Namespace a widget key to the currently loaded plan.

    Streamlit keeps a keyed widget's value in session_state across reruns, and
    it protects any widget instantiated during the current run -- so deleting
    the key is not enough to refresh a widget sitting on the same page as the
    Load button. Versioning the key sidesteps it: loading a plan bumps the
    version, every widget becomes a new widget, and each initialises from the
    freshly loaded data.
    """
    return f"{name}__v{st.session_state.get(VERSION_KEY, 0)}"


def get_household() -> Household:
    if PROFILE_KEY not in st.session_state:
        st.session_state[PROFILE_KEY] = Household()
    return st.session_state[PROFILE_KEY]


def set_household(h: Household) -> None:
    version = st.session_state.get(VERSION_KEY, 0) + 1
    keep = {PROFILE_KEY, VERSION_KEY, PIN_KEY}
    for k in list(st.session_state.keys()):
        if k not in keep:
            try:
                del st.session_state[k]
            except KeyError:
                pass
    st.session_state[PROFILE_KEY] = h
    st.session_state[VERSION_KEY] = version
    st.session_state[DIRTY_KEY] = False


def mark_dirty() -> None:
    st.session_state[DIRTY_KEY] = True


def invalidate() -> None:
    for k in RESULT_KEYS:
        st.session_state.pop(k, None)


# --------------------------------------------------------------------------
# Save / load, in the sidebar
# --------------------------------------------------------------------------

PIN_KEY = "mpf_sidebar_pinned"
PENDING_UPLOAD = "mpf_pending_upload"


def render_sidebar() -> Household:
    """
    The plan controls, and the pin.

    These used to sit in a bordered box at the top of every page, which cost
    roughly a fifth of the first screen on twelve pages. In the sidebar they
    are visible from everywhere and cost nothing.
    """
    h = get_household()

    with st.sidebar:
        # st.navigation renders its links at the top of the sidebar and there
        # is no way to put anything above them, so these controls sit below.
        st.divider()
        st.toggle("📌 Keep this menu open", key=PIN_KEY,
                  help="Pin the menu so it stays open while you move between "
                       "pages. Unpin it to reclaim the width.")

        st.divider()
        st.markdown('<div class="mpf-side-head">Your plan</div>',
                    unsafe_allow_html=True)

        new_name = st.text_input("Plan name", value=h.profile_name,
                                 key=wkey("planname_side"),
                                 label_visibility="collapsed",
                                 placeholder="Name this plan")
        if new_name and new_name != h.profile_name:
            h.profile_name = new_name

        st.download_button("⬇️  Download plan", data=storage.to_download_bytes(h),
                           file_name=storage.download_filename(h),
                           mime="application/json", key=wkey("dl_side"),
                           use_container_width=True)

        with st.expander("📂  Open a plan", expanded=False):
            _render_open_plan()

        if st.session_state.get(DIRTY_KEY):
            st.caption("⚠️ Unsaved changes — download before you close the tab.")

        st.divider()
        st.caption("An estimator, not advice. Military OneSource gives free "
                   "counselling at 800-342-9647.")

    return h


def _render_open_plan() -> None:
    """
    Pick a file, then click a button. Nothing loads until you say so.

    The uploader used to apply a file the instant it was selected, with no
    confirmation and no way back if you picked the wrong one.
    """
    up = st.file_uploader("Choose a plan file", type=["json"],
                          key=wkey("ul_side"),
                          help="A .mpfplan.json file you downloaded earlier.")

    ready = up is not None
    if ready:
        st.caption(f"Selected: **{up.name}**")
    if st.button("Open this file", key=wkey("ulbtn_side"), type="primary",
                 use_container_width=True, disabled=not ready):
        try:
            set_household(storage.from_upload_bytes(up.getvalue()))
            st.rerun()
        except (ValueError, UnicodeDecodeError) as e:
            st.error(f"That file could not be read: {e}")

    slots = storage.list_slots()
    st.divider()
    st.caption("**Saved on this machine.** These do not survive a restart on a "
               "hosted deployment — download the file instead.")

    save_as = st.text_input("Save as", value=get_household().profile_name,
                            key=wkey("saveas_side"),
                            label_visibility="collapsed",
                            placeholder="Save under this name")
    if st.button("💾  Save to this machine", key=wkey("save_side"),
                 use_container_width=True):
        try:
            p = storage.save_slot(get_household(), save_as
                                  or get_household().profile_name)
            st.session_state[DIRTY_KEY] = False
            st.success(f"Saved {p.name}", icon="✅")
        except OSError as e:
            st.error(f"Could not save: {e}")

    if not slots:
        return

    picked = st.selectbox("Saved plans", [s["name"] for s in slots],
                          key=wkey("load_side"), label_visibility="collapsed")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Open", key=wkey("loadbtn_side"), use_container_width=True):
            try:
                set_household(storage.load_slot(picked))
                st.rerun()
            except (OSError, ValueError) as e:
                st.error(f"Could not open: {e}")
    with c2:
        if st.button("Delete", key=wkey("delbtn_side"), use_container_width=True):
            storage.delete_slot(picked)
            st.rerun()


def render_save_load(page_key: str) -> Household:
    """Backwards-compatible shim. The controls now live in the sidebar."""
    return get_household()


BASE_CSS = """
<style>
  /* ---- Density ------------------------------------------------------- */
  /* Streamlit's fixed toolbar is 60px tall, opaque, and sits at the top of
     the viewport at z-index 999990. Its own default padding-top is 6rem to
     clear it. The density pass cut this to 1.5rem, which slid every page
     title 30px UNDER the toolbar and shaved the tops off the letters.
     4.5rem clears the toolbar with room to spare and is still a third
     tighter than stock. */
  .block-container {padding-top: 4.5rem; padding-bottom: 2rem; max-width: 1500px;}
  .block-container h1 {font-size: 1.7rem; margin-bottom: .1rem;}
  .block-container h2 {font-size: 1.22rem; margin: .5rem 0 .25rem;}
  .block-container h3 {font-size: 1.03rem; margin: .35rem 0 .2rem;}
  .block-container h4 {font-size: .88rem; margin: .15rem 0 .3rem;
                       text-transform: uppercase; letter-spacing: .045em;
                       color: #55666f;}
  div[data-testid="stVerticalBlock"] {gap: .38rem;}
  div[data-testid="stHorizontalBlock"] {gap: .9rem;}
  div[data-testid="stMetric"] {padding: .05rem 0;}
  div[data-testid="stMetricValue"] {font-size: 1.28rem;}
  div[data-testid="stMetricLabel"] p {font-size: .75rem; color: #55666f;}
  hr {margin: .55rem 0;}
  div[data-testid="stCaptionContainer"] p {font-size: .78rem; line-height: 1.35;}
  .stAlert {padding: .5rem .75rem;}
  .stAlert p {margin-bottom: .2rem;}

  /* ---- Input widgets: visible against a white page ------------------- */
  /* Streamlit 1.6x testids, with the older baseweb selectors kept so the
     styling survives on whichever version a host installs. */
  [data-testid="stTextInputRootElement"],
  [data-testid="stNumberInputContainer"],
  [data-testid="stDateInputField"],
  [data-testid="stTextArea"] textarea,
  [data-testid="stSelectbox"] div:has(> input[role="combobox"]),
  div[data-baseweb="input"],
  div[data-baseweb="select"] > div {
      background-color: #ffffff !important;
      border: 1px solid #9db0be !important;
      border-radius: 6px !important;
      box-shadow: 0 1px 1.5px rgba(16, 42, 60, .07) !important;
  }
  [data-testid="stTextInputRootElement"]:focus-within,
  [data-testid="stNumberInputContainer"]:focus-within,
  [data-testid="stSelectbox"] div:has(> input[role="combobox"]):focus-within {
      border-color: #1f6f8b !important;
      box-shadow: 0 0 0 2px rgba(31, 111, 139, .20) !important;
  }
  label[data-testid="stWidgetLabel"] p {
      font-size: .79rem; font-weight: 600; color: #2f434e; margin-bottom: .08rem;}

  /* ---- The input card ------------------------------------------------ */
  /* A column of questions should read as one object, not as widgets loose
     on a white page. Marked with .mpf-inputs so only these cards are tinted. */
  div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mpf-inputs),
  div[data-testid="stVerticalBlockBorderWrapper"]:has(.mpf-inputs):not(:has(div[data-testid="stVerticalBlockBorderWrapper"])) {
      background: #dfe9f2 !important;
      border: 1px solid #a3bacd !important;
      border-radius: 9px;
  }
  /* No rule under the title: the card tint already groups the fields, and the
     negative top margin this used to carry made the border render underneath
     the first widget's label rather than above it. */
  .mpf-inputs {
      font-size: .77rem; font-weight: 700; letter-spacing: .06em;
      text-transform: uppercase; color: #33505f;
      margin: 0 0 .45rem;
  }

  /* ---- Sidebar ------------------------------------------------------- */
  .mpf-brand {font-size: .98rem; font-weight: 700; line-height: 1.25;
              color: #1f3d4c; margin: .1rem 0 .45rem;}
  .mpf-side-head {font-size: .72rem; font-weight: 700; letter-spacing: .07em;
                  text-transform: uppercase; color: #5c7280; margin-bottom: .2rem;}
  section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] {gap: .3rem;}
  section[data-testid="stSidebar"] ul {margin-bottom: .3rem;}
</style>
"""

PINNED_CSS = """
<style>
  /* Pinned: the menu cannot be collapsed away by a stray click. */
  section[data-testid="stSidebar"] {
      transform: none !important; visibility: visible !important;
      min-width: 17rem !important;}
  div[data-testid="stSidebarCollapseButton"],
  button[data-testid="stBaseButton-headerNoPadding"] {display: none !important;}
  section[data-testid="stSidebar"]::after {
      content: "📌"; position: absolute; top: .55rem; right: .6rem;
      font-size: .8rem; opacity: .5;}
</style>
"""

# Kept for pages that still import the old name.
COMPACT_CSS = BASE_CSS


def inject_css() -> None:
    """Called once by the router, before any page runs."""
    st.markdown(BASE_CSS, unsafe_allow_html=True)
    if st.session_state.get(PIN_KEY):
        st.markdown(PINNED_CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str = "") -> None:
    st.title(title)
    if subtitle:
        st.caption(subtitle)


class section:
    """
    A bordered, titled panel.

    Used as a context manager so a page reads as a set of distinct boxes rather
    than one long scroll:

        with section("Basic pay"):
            ...
    """

    def __init__(self, title: str = "", caption: str = ""):
        self.title, self.caption = title, caption
        self._ctx = None

    def __enter__(self):
        self._ctx = st.container(border=True)
        self._ctx.__enter__()
        if self.title:
            st.markdown(f"#### {self.title}")
        if self.caption:
            st.caption(self.caption)
        return self

    def __exit__(self, *exc):
        return self._ctx.__exit__(*exc)


def two_pane(ratio=(1, 2.3), gap: str = "large"):
    """
    A narrow stacked column of inputs on the left, results on the right.

    Three-across input rows looked tidy on a wide monitor and left most of the
    page empty. Questions read better in one narrow column you work down; the
    width belongs to the answers.

        inputs, results = two_pane()
        with inputs, input_card():
            ...
        with results:
            ...
    """
    return st.columns(list(ratio), gap=gap)


class input_card:
    """The tinted panel that holds a stacked column of inputs."""

    def __init__(self, title: str = "Your answers"):
        self.title = title
        self._ctx = None

    def __enter__(self):
        self._ctx = st.container(border=True)
        self._ctx.__enter__()
        st.markdown(f'<div class="mpf-inputs">{esc(self.title)}</div>',
                    unsafe_allow_html=True)
        return self

    def __exit__(self, *exc):
        return self._ctx.__exit__(*exc)


def metric_row(items, columns: int = 0):
    """A compact row of metrics from (label, value) or (label, value, delta)."""
    if not items:
        return
    cols = st.columns(columns or len(items))
    for col, item in zip(cols, items):
        label, value, *rest = item
        col.metric(label, value, rest[0] if rest else None)


# --------------------------------------------------------------------------
# Inputs bound to an object
# --------------------------------------------------------------------------

def money(label, obj, attr, key, help=None, step=100.0, min_value=0.0,
          max_value=None, disabled=False):
    val = float(getattr(obj, attr))
    new = st.number_input(label, value=val, step=step, min_value=min_value,
                          max_value=max_value, format="%.2f", key=key,
                          help=help, disabled=disabled)
    if abs(new - val) > 1e-9:
        setattr(obj, attr, float(new)); mark_dirty(); invalidate()
    return new


def pct(label, obj, attr, key, help=None, step=0.5, min_value=0.0,
        max_value=100.0, decimals=2, disabled=False):
    val = float(getattr(obj, attr)) * 100.0
    new = st.number_input(label, value=round(val, decimals), step=step,
                          min_value=min_value, max_value=max_value,
                          format=f"%.{decimals}f", key=key, help=help,
                          disabled=disabled)
    if abs(new - val) > 1e-9:
        setattr(obj, attr, new / 100.0); mark_dirty(); invalidate()
    return new / 100.0


def number(label, obj, attr, key, help=None, min_value=0.0, max_value=None,
           step=1.0, fmt="%.1f", disabled=False):
    val = float(getattr(obj, attr))
    new = st.number_input(label, value=val, min_value=min_value,
                          max_value=max_value, step=step, format=fmt, key=key,
                          help=help, disabled=disabled)
    if abs(new - val) > 1e-9:
        setattr(obj, attr, float(new)); mark_dirty(); invalidate()
    return new


def integer(label, obj, attr, key, help=None, min_value=0, max_value=200, step=1):
    val = int(getattr(obj, attr))
    new = st.number_input(label, value=val, min_value=min_value,
                          max_value=max_value, step=step, key=key, help=help)
    if new != val:
        setattr(obj, attr, int(new)); mark_dirty(); invalidate()
    return new


def text(label, obj, attr, key, help=None, placeholder=""):
    val = getattr(obj, attr) or ""
    new = st.text_input(label, value=val, key=key, help=help,
                        placeholder=placeholder)
    if new != val:
        setattr(obj, attr, new); mark_dirty(); invalidate()
    return new


def toggle(label, obj, attr, key, help=None):
    val = bool(getattr(obj, attr))
    new = st.toggle(label, value=val, key=key, help=help)
    if new != val:
        setattr(obj, attr, new); mark_dirty(); invalidate()
    return new


def choice(label, obj, attr, options, key, help=None, format_func=str):
    val = getattr(obj, attr)
    idx = options.index(val) if val in options else 0
    new = st.selectbox(label, options, index=idx, key=key, help=help,
                       format_func=format_func)
    if new != val:
        setattr(obj, attr, new); mark_dirty(); invalidate()
    return new


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------

def fmt_money(x: float) -> str:
    """Plain text, for st.metric and dataframes, which do not parse markdown."""
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.0f}"


def esc(t: str) -> str:
    """Streamlit reads a pair of unescaped '$' as LaTeX. Escape for markdown."""
    return (t or "").replace("$", r"\$")


def md_money(x: float) -> str:
    return esc(fmt_money(x))


def fmt_pct(x: float, decimals: int = 0) -> str:
    return f"{x * 100:.{decimals}f}%"


SEV_ICON = {"good": "✅", "warn": "⚠️", "bad": "🚨", "info": "💡"}


def render_findings(findings) -> None:
    """Render (severity, headline, detail) triples as bordered cards."""
    for sev, headline, detail in findings:
        with st.container(border=True):
            st.markdown(f"**{SEV_ICON.get(sev, '•')} {esc(headline)}**")
            if detail:
                st.markdown(esc(detail))
