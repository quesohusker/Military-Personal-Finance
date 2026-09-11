# assets

## The crest

| File | What it is |
|---|---|
| `crest.jpeg` | **The original artwork**, as supplied. Keep it — it is the source to re-cut from if the derived file ever needs regenerating. Not what the app loads. |
| `crest.png` | **What the app shows.** Derived from the JPEG: flat grey field made transparent, trimmed to the artwork, resized and quantised. |

`pages/00_Start.py` takes the first `assets/crest.*` it finds, in the order
`png, jpg, jpeg, webp, svg` — so `crest.png` wins, and dropping in a new
`crest.png` replaces the artwork with no code change.

### Why the PNG exists rather than just using the JPEG

The JPEG carries a flat grey background. On the app's white page that renders
as a grey slab behind the crest, which reads as a screenshot someone pasted in
rather than part of the page. JPEG cannot carry transparency, so the fix has to
be a PNG.

The grey was removed by flood-filling inward **from the border**, not by keying
the colour globally — the ladle is the same family of grey as the background,
and a global key punches a hole straight through it. Anything enclosed by the
crest survives whatever its colour.

It was also 1.8 MB, which shipped on every page load for an image the column
renders at roughly 420px. The derived file is 700px wide and about 650 KB.

To regenerate after replacing `crest.jpeg`, the steps are: sample the corner
colour, flood-fill from the edges within a tolerance of ~26 (JPEG artefacts
smear a flat field), crop to the alpha bounding box, resize to 700px wide, and
quantise to 256 colours **without dithering** — dithering adds noise that PNG
cannot compress, so it makes the file bigger, not smaller.

### The tab icon

To use the crest as the browser tab icon, pass it to the router's existing
`st.set_page_config(page_icon=...)` in `Military_Finance.py`, anchoring the
path with `Path(__file__).parent` — `mpf.sh` does not guarantee the working
directory. Note that a 700px crest is a poor favicon: at 16px this artwork
becomes a yellow smudge. A separate simplified mark would be the right answer
if the tab icon matters.
