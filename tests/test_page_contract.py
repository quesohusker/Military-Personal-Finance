"""
Rules every page has to keep, because the app frame depends on them.

The router draws the Save / Load file row AFTER the page has run, so that
Save writes the plan including the edit the page just applied (draw it first
and Save would silently write the plan as it was one edit ago). That only
works if a page lets control return to the router.
"""
import sys, pathlib, re
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

PAGES = sorted((pathlib.Path(__file__).resolve().parent.parent / "pages").glob("*.py"))


def _code(path):
    """Source with comments stripped, so a comment explaining a rule passes."""
    return "\n".join(line.split("#", 1)[0] for line in path.read_text().splitlines())


def test_there_are_pages_to_check():
    assert len(PAGES) >= 20


def test_no_page_calls_st_stop():
    """
    st.stop() registers a stop request on the runner; nothing renders after
    it, so the page loses its Save and Load buttons. Call
    ui.panel.end_page() instead -- same effect on the page, and the router
    catches it.
    """
    offenders = [p.name for p in PAGES if re.search(r"\bst\.stop\(\)", _code(p))]
    assert not offenders, f"st.stop() in {offenders} -- call end_page() instead"


def test_no_page_sets_its_own_page_config():
    """The router owns st.set_page_config; a page calling it raises."""
    offenders = [p.name for p in PAGES if "set_page_config" in _code(p)]
    assert not offenders, offenders
