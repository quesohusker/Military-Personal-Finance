"""
Shared Streamlit UI: the save/load panel that appears at the top of every page,
plus input helpers that write straight back into the Profile object.

The Profile lives in st.session_state and is mutated in place, so any widget
change is immediately visible to every other page.
"""

from __future__ import annotations
import streamlit as st

from engine.roth_profile import Profile, validate
from engine import storage


PROFILE_KEY = "profile"
DIRTY_KEY = "unsaved_changes"
VERSION_KEY = "profile_version"


def wkey(name: str) -> str:
    """
    Namespace a widget key to the currently loaded plan.

    Streamlit keeps a keyed widget's value in session_state across reruns, and
    it protects the state of any widget instantiated during the current run --
    so deleting the key is not enough to refresh a widget that lives on the
    same page as the Load button. Versioning the key sidesteps that entirely:
    loading a plan bumps the version, every widget becomes a NEW widget with no
    prior state, and each one initialises from the freshly loaded profile.
    """
    return f"{name}__v{st.session_state.get(VERSION_KEY, 0)}"


# --------------------------------------------------------------------------
# Session state
# --------------------------------------------------------------------------

def get_profile() -> Profile:
    if PROFILE_KEY not in st.session_state:
        st.session_state[PROFILE_KEY] = Profile()
    return st.session_state[PROFILE_KEY]


RESULT_KEYS = ("comparison", "mc_summary", "bracket_sweep", "scenario_sweep")


def set_profile(p: Profile) -> None:
    """
    Install a freshly loaded plan.

    Every widget on every page is keyed, and Streamlit keeps a keyed widget's
    value in session_state across reruns. If those keys survive a load, each
    page still shows the PREVIOUS plan's numbers -- and, worse, writes them
    back into the new profile on the next rerun, silently corrupting it. So
    loading a plan clears all widget state and lets the widgets rebuild
    themselves from the new profile.
    """
    version = st.session_state.get(VERSION_KEY, 0) + 1
    keep = {PROFILE_KEY, VERSION_KEY}
    for k in list(st.session_state.keys()):
        if k not in keep:
            try:
                del st.session_state[k]
            except KeyError:
                pass

    st.session_state[PROFILE_KEY] = p
    st.session_state[VERSION_KEY] = version
    st.session_state[DIRTY_KEY] = False


def mark_dirty() -> None:
    st.session_state[DIRTY_KEY] = True


def invalidate_results() -> None:
    """Any change to an input makes the cached projections stale."""
    for k in RESULT_KEYS:
        st.session_state.pop(k, None)


# --------------------------------------------------------------------------
# The save / load panel
# --------------------------------------------------------------------------

def render_save_load(page_key: str) -> Profile:
    """
    Render the save/load bar. Call this FIRST on every page.

    Returns the active Profile.
    """
    p = get_profile()

    with st.container(border=True):
        st.markdown("#### 💾 Save / Load your plan")

        name_col, save_col, load_col = st.columns([2.2, 1, 1.6])

        with name_col:
            new_name = st.text_input(
                "Plan name",
                value=p.profile_name,
                key=wkey(f"planname_{page_key}"),
                label_visibility="collapsed",
                placeholder="Name this plan",
            )
            if new_name and new_name != p.profile_name:
                p.profile_name = new_name

        with save_col:
            if st.button("Save", key=wkey(f"save_{page_key}"), use_container_width=True,
                         type="primary"):
                try:
                    path = storage.save_slot(p, p.profile_name)
                    st.session_state[DIRTY_KEY] = False
                    st.success(f"Saved to {path.name}", icon="✅")
                except OSError as e:
                    st.error(f"Could not save: {e}")

        with load_col:
            slots = storage.list_slots()
            options = ["— load a saved plan —"] + [s["name"] for s in slots]
            picked = st.selectbox(
                "Load", options, key=wkey(f"load_{page_key}"),
                label_visibility="collapsed",
            )
            if picked != options[0]:
                if st.button(f"Load '{picked}'", key=wkey(f"loadbtn_{page_key}"),
                             use_container_width=True):
                    try:
                        set_profile(storage.load_slot(picked))
                        st.success(f"Loaded '{picked}'", icon="📂")
                        st.rerun()
                    except (OSError, ValueError) as e:
                        st.error(f"Could not load: {e}")

        with st.expander("Import / export a plan file", expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                st.download_button(
                    "⬇️ Download this plan",
                    data=storage.to_download_bytes(p),
                    file_name=storage.download_filename(p),
                    mime="application/json",
                    key=wkey(f"dl_{page_key}"),
                    use_container_width=True,
                )
                st.caption(
                    "A plain JSON file on your own machine. Nothing is uploaded "
                    "anywhere."
                )
            with c2:
                up = st.file_uploader(
                    "⬆️ Load a plan file", type=["json"], key=wkey(f"ul_{page_key}"),
                    label_visibility="visible",
                )
                if up is not None:
                    try:
                        set_profile(storage.from_upload_bytes(up.getvalue()))
                        st.success("Plan loaded.", icon="📂")
                        st.rerun()
                    except (ValueError, UnicodeDecodeError) as e:
                        st.error(f"That file could not be read: {e}")

            if slots:
                st.divider()
                dc1, dc2 = st.columns([2, 1])
                with dc1:
                    to_delete = st.selectbox(
                        "Delete a saved plan", [s["name"] for s in slots],
                        key=wkey(f"del_{page_key}"),
                    )
                with dc2:
                    st.write("")
                    if st.button("Delete", key=wkey(f"delbtn_{page_key}"),
                                 use_container_width=True):
                        storage.delete_slot(to_delete)
                        st.rerun()

        if st.session_state.get(DIRTY_KEY):
            st.caption("⚠️ You have unsaved changes.")

    return p


def page_header(title: str, subtitle: str = "") -> None:
    st.title(title)
    if subtitle:
        st.caption(subtitle)


def show_validation(p: Profile) -> None:
    issues = validate(p)
    if issues:
        with st.expander(f"⚠️ {len(issues)} thing(s) to check", expanded=False):
            for i in issues:
                st.warning(i)


# --------------------------------------------------------------------------
# Input helpers -- each writes back into the Profile immediately
# --------------------------------------------------------------------------

def money(label, obj, attr, key, help=None, step=1000.0, min_value=0.0,
          max_value=None, fmt="%.0f", disabled=False):
    val = float(getattr(obj, attr))
    new = st.number_input(
        label, value=val, step=step, min_value=min_value,
        max_value=max_value, format=fmt, key=key, help=help, disabled=disabled,
    )
    if new != val:
        setattr(obj, attr, float(new))
        mark_dirty(); invalidate_results()
    return new


def pct(label, obj, attr, key, help=None, step=0.1, min_value=-100.0,
        max_value=100.0, decimals=2, disabled=False):
    """Percentage input. Stored as a decimal, shown as a percent."""
    val = float(getattr(obj, attr)) * 100.0
    new = st.number_input(
        label, value=round(val, decimals), step=step, min_value=min_value,
        max_value=max_value, format=f"%.{decimals}f", key=key, help=help,
        disabled=disabled,
    )
    if abs(new - val) > 1e-9:
        setattr(obj, attr, new / 100.0)
        mark_dirty(); invalidate_results()
    return new / 100.0


def number(label, obj, attr, key, help=None, min_value=0.0, max_value=None,
           step=1.0, fmt="%.1f", disabled=False):
    """Plain float input, for things that are neither money nor a percentage."""
    val = float(getattr(obj, attr))
    new = st.number_input(
        label, value=val, min_value=min_value, max_value=max_value, step=step,
        format=fmt, key=key, help=help, disabled=disabled,
    )
    if abs(new - val) > 1e-9:
        setattr(obj, attr, float(new))
        mark_dirty(); invalidate_results()
    return new


def integer(label, obj, attr, key, help=None, min_value=0, max_value=200,
            step=1, disabled=False):
    val = int(getattr(obj, attr))
    new = st.number_input(
        label, value=val, min_value=min_value, max_value=max_value, step=step,
        key=key, help=help, disabled=disabled,
    )
    if new != val:
        setattr(obj, attr, int(new))
        mark_dirty(); invalidate_results()
    return new


def text(label, obj, attr, key, help=None, placeholder=""):
    val = getattr(obj, attr)
    new = st.text_input(label, value=val, key=key, help=help,
                        placeholder=placeholder)
    if new != val:
        setattr(obj, attr, new)
        mark_dirty(); invalidate_results()
    return new


def toggle(label, obj, attr, key, help=None):
    val = bool(getattr(obj, attr))
    new = st.toggle(label, value=val, key=key, help=help)
    if new != val:
        setattr(obj, attr, new)
        mark_dirty(); invalidate_results()
    return new


def choice(label, obj, attr, options, key, help=None, format_func=str):
    val = getattr(obj, attr)
    idx = options.index(val) if val in options else 0
    new = st.selectbox(label, options, index=idx, key=key, help=help,
                       format_func=format_func)
    if new != val:
        setattr(obj, attr, new)
        mark_dirty(); invalidate_results()
    return new


def fmt_money(x: float) -> str:
    """Plain text. Use in st.metric and dataframes, which do NOT parse markdown."""
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.0f}"


def esc(text: str) -> str:
    """
    Escape dollar signs for Streamlit markdown.

    Streamlit reads a pair of unescaped '$' as inline LaTeX, so "$5 to $9"
    silently renders as math. Everything routed through st.markdown, st.caption,
    st.info, st.success, st.warning or st.error must pass through here.
    """
    return text.replace("$", r"\$")


def md_money(x: float) -> str:
    """Markdown-safe money. Use everywhere text is rendered as markdown."""
    return esc(fmt_money(x))


def fmt_pct(x: float, decimals: int = 0) -> str:
    return f"{x * 100:.{decimals}f}%"


def delta_color(x: float, good_is_positive: bool = True) -> str:
    if abs(x) < 1:
        return "off"
    return "normal" if good_is_positive else "inverse"
