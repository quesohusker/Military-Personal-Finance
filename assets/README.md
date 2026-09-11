# assets

## `crest.png` — the app's crest, shown on the Start page

**Not in the repo.** Save the artwork here as `crest.png` and the Start page
picks it up with no code change. Until then the page says the file is missing
rather than showing a broken image, and everything else on it still works.

- A wide transparent-background PNG works best — the page scales it to the
  column width, so its own margins become the page's spacing.
- `pages/00_Start.py` is the only thing that reads it, via
  `Path(__file__).parent.parent / "assets" / "crest.png"`. Replacing the
  artwork never means editing Python.

To use it as the browser tab icon as well, pass it to the router's existing
`st.set_page_config(page_icon=...)` in `Military_Finance.py`. Anchor the path
with `Path(__file__).parent` — `mpf.sh` does not guarantee the working
directory.
