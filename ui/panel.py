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
    keep = {PROFILE_KEY, VERSION_KEY}
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
# Save / load bar
# --------------------------------------------------------------------------

def render_save_load(page_key: str) -> Household:
    """Render the save/load bar. Call this FIRST on every page."""
    h = get_household()

    with st.container(border=True):
        st.markdown("#### 💾 Save / Load your plan")
        name_col, save_col, load_col = st.columns([2.2, 1, 1.6])

        with name_col:
            new_name = st.text_input(
                "Plan name", value=h.profile_name, key=wkey(f"planname_{page_key}"),
                label_visibility="collapsed", placeholder="Name this plan")
            if new_name and new_name != h.profile_name:
                h.profile_name = new_name

        with save_col:
            if st.button("Save", key=wkey(f"save_{page_key}"), type="primary",
                         use_container_width=True):
                try:
                    p = storage.save_slot(h, h.profile_name)
                    st.session_state[DIRTY_KEY] = False
                    st.success(f"Saved to {p.name}", icon="✅")
                except OSError as e:
                    st.error(f"Could not save: {e}")

        with load_col:
            slots = storage.list_slots()
            options = ["— load a saved plan —"] + [s["name"] for s in slots]
            picked = st.selectbox("Load", options, key=wkey(f"load_{page_key}"),
                                  label_visibility="collapsed")
            if picked != options[0]:
                if st.button(f"Load '{picked}'", key=wkey(f"loadbtn_{page_key}"),
                             use_container_width=True):
                    try:
                        set_household(storage.load_slot(picked))
                        st.rerun()
                    except (OSError, ValueError) as e:
                        st.error(f"Could not load: {e}")

        with st.expander("Import / export a plan file", expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                st.download_button(
                    "⬇️ Download this plan",
                    data=storage.to_download_bytes(h),
                    file_name=storage.download_filename(h),
                    mime="application/json", key=wkey(f"dl_{page_key}"),
                    use_container_width=True)
                st.caption("Plain JSON on your own machine. Nothing is uploaded "
                           "anywhere. **On a hosted deployment this is the only "
                           "storage that survives a restart** — download before "
                           "you close the tab.")
            with c2:
                up = st.file_uploader("⬆️ Load a plan file", type=["json"],
                                      key=wkey(f"ul_{page_key}"))
                if up is not None:
                    try:
                        set_household(storage.from_upload_bytes(up.getvalue()))
                        st.rerun()
                    except (ValueError, UnicodeDecodeError) as e:
                        st.error(f"That file could not be read: {e}")

            if slots:
                st.divider()
                d1, d2 = st.columns([2, 1])
                with d1:
                    victim = st.selectbox("Delete a saved plan",
                                          [s["name"] for s in slots],
                                          key=wkey(f"del_{page_key}"))
                with d2:
                    st.write("")
                    if st.button("Delete", key=wkey(f"delbtn_{page_key}"),
                                 use_container_width=True):
                        storage.delete_slot(victim)
                        st.rerun()

        if st.session_state.get(DIRTY_KEY):
            st.caption("⚠️ You have unsaved changes.")

    return h


COMPACT_CSS = """
<style>
  /* Streamlit's defaults are generous with vertical space. On a page that is
     mostly dense numeric input, that generosity turns into scrolling. */
  .block-container {padding-top: 2.2rem; padding-bottom: 2rem; max-width: 1400px;}
  .block-container h1 {font-size: 1.9rem; margin-bottom: .15rem;}
  .block-container h2 {font-size: 1.3rem; margin: .55rem 0 .3rem;}
  .block-container h3 {font-size: 1.08rem; margin: .4rem 0 .25rem;}
  .block-container h4 {font-size: .95rem; margin: .2rem 0 .35rem;
                       text-transform: uppercase; letter-spacing: .04em;
                       color: #5a6b73;}
  div[data-testid="stVerticalBlockBorderWrapper"] {
      background: #fbfcfc; border-radius: 8px;}
  div[data-testid="stVerticalBlock"] {gap: .45rem;}
  div[data-testid="stHorizontalBlock"] {gap: .7rem;}
  div[data-testid="stMetric"] {padding: .1rem 0;}
  div[data-testid="stMetricValue"] {font-size: 1.35rem;}
  div[data-testid="stMetricLabel"] p {font-size: .78rem; color: #5a6b73;}
  hr {margin: .7rem 0;}
  div[data-testid="stCaptionContainer"] p {font-size: .8rem; line-height: 1.35;}
  .stAlert {padding: .55rem .8rem;}
  .stAlert p {margin-bottom: .25rem;}
</style>
"""


def page_header(title: str, subtitle: str = "") -> None:
    st.markdown(COMPACT_CSS, unsafe_allow_html=True)
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
