"""
Save and Load: two buttons at the top of every page, behaving like any desktop app.

    Save       opens the system's Save window and writes the plan where you
               choose. Every press asks, like Save As, so nothing is ever
               written somewhere you did not pick.
    Load file  opens the system's Open window. Pick a plan, press Open, and it
               is loaded. That press is the confirmation -- there is no second
               button to click inside the app.

Why a custom component rather than st.download_button and st.file_uploader:
a download only shows a Save window if the browser happens to be set to ask,
and the uploader wraps the Open window in a drop zone, an expander and a
confirm button. Both are the confusion this replaces.

BROWSER SUPPORT. The Save window uses the File System Access API, which
Chrome and Edge have and Safari and Firefox do not. In those two, Save falls
back to an ordinary download, which shows a Save window only if the browser
is set to "Ask where to save each file". The Open window works everywhere.

This runs as an st.components.v2 component, which executes in the page
itself rather than in an iframe. That matters: the Save window is refused
inside a cross-origin iframe, which is where a v1 component would put it.

The plan's JSON reaches the JavaScript as DATA and is only ever written into
a Blob, never into markup, so nothing in a plan file is rendered as HTML.
"""

from __future__ import annotations

import streamlit as st

from engine import storage

TOOLBAR_KEY = "mpf_plan_file"
LAST_FILE_KEY = "mpf_last_file_name"   # what Save suggests next time
FLASH_KEY = "mpf_plan_file_flash"      # a message that must survive a rerun

_HTML = """
<div class="bar" role="toolbar" aria-label="Plan file">
  <button id="mpf-save" type="button" title="Save this plan to a file on your computer">💾&nbsp; Save</button>
  <button id="mpf-load" type="button" title="Open a plan file you saved earlier">📂&nbsp; Load file</button>
  <span id="mpf-status" class="status" hidden>● Unsaved changes</span>
  <input id="mpf-picker" type="file" accept=".json,application/json" hidden>
</div>
"""

_CSS = """
.bar { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap;
       font-family: "Source Sans Pro", "Source Sans 3", -apple-system,
                    BlinkMacSystemFont, "Segoe UI", sans-serif; }
button { font: inherit; font-size: .875rem; line-height: 1.4;
         padding: .38rem .9rem; border-radius: .5rem; cursor: pointer;
         border: 1px solid #9db0be;
         background: var(--st-background-color, #ffffff);
         color: var(--st-text-color, #16232b);
         box-shadow: 0 1px 1.5px rgba(16, 42, 60, .07); }
button:hover { border-color: var(--st-primary-color, #1f4e5f);
               color: var(--st-primary-color, #1f4e5f); }
button:focus-visible { outline: 2px solid var(--st-primary-color, #1f4e5f);
                       outline-offset: 1px; }
.status { font-size: .8rem; font-weight: 600; color: #9a6700;
          margin-left: .35rem; }
.status[hidden], input[hidden] { display: none; }
"""

_JS = """
const PLAN_TYPES = [{
  description: "Military Personal Finance plan",
  accept: { "application/json": [".json"] },
}];

function download(blob, name) {
  // Fallback for browsers without the Save window (Safari, Firefox).
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

export default function (component) {
  const { data, setTriggerValue, parentElement } = component;
  const root = parentElement;
  const save = root.querySelector("#mpf-save");
  const load = root.querySelector("#mpf-load");
  const picker = root.querySelector("#mpf-picker");
  const status = root.querySelector("#mpf-status");
  if (!save || !load || !picker || !data) return;

  // Re-run on every render with the latest data; assigning handlers is
  // idempotent, so nothing stacks up.
  status.hidden = !data.dirty;

  save.onclick = async () => {
    const blob = new Blob([data.json], { type: "application/json" });
    if (typeof window.showSaveFilePicker === "function") {
      try {
        const handle = await window.showSaveFilePicker({
          suggestedName: data.filename, types: PLAN_TYPES,
        });
        const out = await handle.createWritable();
        await out.write(blob);
        await out.close();
        setTriggerValue("saved", { name: handle.name, method: "picker" });
      } catch (err) {
        if (err && err.name === "AbortError") return;   // pressed Cancel
        download(blob, data.filename);
        setTriggerValue("saved", { name: data.filename, method: "download" });
      }
      return;
    }
    download(blob, data.filename);
    setTriggerValue("saved", { name: data.filename, method: "download" });
  };

  // The Open window comes from an ordinary file input: it is the system's
  // own dialog in every browser, and choosing a file there is the confirm.
  load.onclick = () => picker.click();
  picker.onchange = async () => {
    const file = picker.files && picker.files[0];
    if (!file) return;
    const text = await file.text();
    picker.value = "";          // so the same file can be chosen twice
    setTriggerValue("loaded", { name: file.name, text: text });
  };
}
"""

_PLAN_FILE = st.components.v2.component(
    "mpf_plan_file", html=_HTML, css=_CSS, js=_JS)


def _noop() -> None:
    """Trigger callbacks exist only to make a button press rerun the app."""


def apply_loaded(payload) -> str | None:
    """
    Load a plan from the file the user opened. Returns an error message, or
    None on success (in which case the caller reruns).
    """
    # Imported here: ui.panel imports this module.
    from ui.panel import set_household

    if not isinstance(payload, dict) or not payload.get("text"):
        return "That file was empty."
    name = str(payload.get("name") or "plan file")
    try:
        h = storage.from_upload_bytes(str(payload["text"]).encode("utf-8"))
    except (ValueError, UnicodeDecodeError, TypeError) as e:
        return f"{name} is not a plan file this app can read ({e})."
    set_household(h)                       # clears session state, so set
    st.session_state[LAST_FILE_KEY] = name  # these two afterwards
    st.session_state[FLASH_KEY] = f"Loaded {name}"
    return None


def apply_saved(payload) -> None:
    """Record a completed save: clear the unsaved flag, remember the name."""
    from ui.panel import DIRTY_KEY

    if not isinstance(payload, dict):
        return
    name = str(payload.get("name") or "")
    st.session_state[DIRTY_KEY] = False
    if payload.get("method") == "picker":
        st.session_state[LAST_FILE_KEY] = name
        st.session_state[FLASH_KEY] = f"Saved as {name}"
    else:
        st.session_state[FLASH_KEY] = (f"Downloaded {name} -- it is in your "
                                       f"Downloads folder.")


def render_plan_toolbar() -> None:
    """The Save / Load file row. Called once by the router, above every page."""
    from ui.panel import get_household, DIRTY_KEY

    flash = st.session_state.pop(FLASH_KEY, None)
    if flash:
        st.toast(flash, icon="💾" if flash.startswith(("Saved", "Downloaded"))
                 else "📂")

    h = get_household()
    data = {
        "json": storage.to_download_bytes(h).decode("utf-8"),
        "filename": (st.session_state.get(LAST_FILE_KEY)
                     or storage.download_filename(h)),
        "dirty": bool(st.session_state.get(DIRTY_KEY)),
    }
    result = _PLAN_FILE(data=data, key=TOOLBAR_KEY,
                        on_saved_change=_noop, on_loaded_change=_noop)

    loaded = getattr(result, "loaded", None)
    if loaded:
        err = apply_loaded(loaded)
        if err:
            st.error(err, icon="🚫")
        else:
            st.rerun()

    saved = getattr(result, "saved", None)
    if saved:
        apply_saved(saved)
        # The toolbar was drawn with the flag still set; redraw it cleared.
        st.rerun()
