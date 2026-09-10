import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st

from ui.panel import (wkey, get_household, page_header, two_pane, input_card,
                      section, metric_row, fmt_money, fmt_pct, esc, md_money)
from engine.coach import prime_directive as PD

h = get_household()
page_header("🧭 What to do with my next dollar",
            "Where your next dollar should go, in order, for your situation "
            "specifically — not a generic checklist.")

r = PD.evaluate(h)

inputs, results = two_pane()

# ==========================================================================
# Left: the only thing there is to set on this page.
# ==========================================================================
with inputs:
    with input_card("What do you want to see?"):
        show_na = st.toggle("Show steps that do not apply to you?", value=True,
                            key=wkey("show_na"),
                            help="Steps are marked not applicable with a reason. Those "
                                 "reasons are often the most useful thing on the page — "
                                 "they are where military rules diverge from the "
                                 "civilian advice you will read elsewhere.")

ICON = {PD.DONE: "✅", PD.IN_PROGRESS: "🔵", PD.NOT_STARTED: "⬜",
        PD.NOT_APPLICABLE: "➖"}
LABEL = {PD.DONE: "Done", PD.IN_PROGRESS: "In progress",
         PD.NOT_STARTED: "Not started", PD.NOT_APPLICABLE: "Does not apply"}

# ==========================================================================
# Right: where you are, and the order itself.
# ==========================================================================
with results:
    with section("Where you are"):
        metric_row([("Progress", f"{r.score:.0f}/100"),
                    ("Steps complete", f"{r.completed} of {r.applicable}")])

        st.progress(min(1.0, r.score / 100.0))

        if r.current:
            st.markdown("**Your next action**")
            st.markdown(f"### {esc(r.current.title)}")
            with st.container(border=True):
                st.markdown(f"**{esc(r.current.action)}**")
                if r.current.military_note:
                    st.caption(esc(r.current.military_note))
        else:
            st.success("Every applicable step is complete.", icon="🏆")

    st.markdown("## The full order")

    for s in r.steps:
        if s.status == PD.NOT_APPLICABLE and not show_na:
            continue
        is_next = (r.current is not None and s.key == r.current.key)
        with st.container(border=True):
            head, badge = st.columns([5, 1])
            with head:
                marker = "  ← you are here" if is_next else ""
                st.markdown(f"**{ICON[s.status]} {s.order}. {esc(s.title)}**{marker}")
            with badge:
                st.caption(LABEL[s.status])

            if s.status != PD.NOT_APPLICABLE and s.target > 0 and s.progress < 1:
                st.progress(s.progress)

            st.markdown(esc(s.action))

            if s.status != PD.NOT_APPLICABLE and s.amount_needed > 0:
                st.caption(f"Gap: {esc(fmt_money(s.amount_needed))}")

            with st.expander("Why this step, and what is different for the military"):
                st.markdown(f"**Why:** {esc(s.why)}")
                if s.military_note:
                    st.markdown(f"**Military specifics:** {esc(s.military_note)}")

    with st.expander("Where this differs from civilian advice, and why"):
        st.markdown(esc("""
The civilian financial order of operations is close to right, and wrong in five
specific places. Each is worth money.

**1. The TSP match only exists under BRS.** "Always contribute enough to get
the match" does nothing for a High-3 member — there is no match. Which system
applies is decided by your DIEMS date, not by choice.

**2. The match is computed on basic pay only.** Not BAH, not BAS, not special
pays. "5% of your income" is the wrong instruction.

**3. An HSA is unavailable on active duty.** TRICARE is not a high-deductible
health plan. Civilian lists rank the HSA above maxing your retirement plan; for
you the step does not exist. It becomes real if your spouse is on an employer
high-deductible plan, if you are Guard or Reserve off orders, or after you
separate.

**4. The Savings Deposit Program outranks everything while deployed.** A
guaranteed 10% on up to $10,000, risk-free, with interest continuing 90 days
after redeployment. No civilian equivalent exists, and it beats even the match.

**5. SCRA comes before the debt step, not inside it.** Capping pre-service debt
at 6% can change which debt is actually the expensive one, so invoke it before
you optimise the payoff order — not after.

One more that is not a reordering but a reframing: **the reason to hold an
emergency fund is different.** The civilian case is job loss, which you
effectively do not face. Your case is PCS costs you float for months before
reimbursement, spouse income stopping at every move, and DFAS recouping its own
pay errors out of your paycheck. Three months is defensible while serving; move
toward six as you approach separation, when job-loss risk becomes real.
    """))

    st.caption("Free, confidential financial counselling is available to you and "
               "your family through Military OneSource at 800-342-9647, and through "
               "your installation's Personal Financial Manager. Both are genuinely "
               "good and cost nothing.")
