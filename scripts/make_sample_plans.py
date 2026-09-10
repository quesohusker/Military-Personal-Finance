#!/usr/bin/env python3
"""
Generate the two sample plan files in samples/.

They are built through the app's own dataclasses and serialiser, so the files
cannot drift from the schema. Regenerate with:

    python scripts/make_sample_plans.py

Every figure a service member would read off an LES, a Retiree Account
Statement or a VA award letter is a PLACEHOLDER here. These files exist to
exercise the app, not to describe anyone.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from engine.profile import Household, ServiceMember, ACTIVE, RETIRED
from engine.income.spouse import SpouseIncome, CAREER_LOCAL
from engine.debt.payoff import Debt
from engine import storage

OUT = pathlib.Path(__file__).resolve().parent.parent / "samples"


def e5_six_years() -> Household:
    """
    An E-5 with 6 years, BRS, at Fort Bragg, deployed to a combat zone.

    Chosen to light up as much of the app as possible: BRS means there is a
    TSP match to miss, the DIEMS date makes that automatic rather than a
    choice, the combat-zone deployment turns on CZTE and SDP, the pre-service
    credit card is SCRA-eligible at 6%, and Texas residency against North
    Carolina duty exercises the domicile comparison.
    """
    h = Household(profile_name="Sample — E-5, 6 years, BRS, Fort Bragg")
    h.member = ServiceMember(
        name="", birth_year=1999, component=ACTIVE, branch="Army",
        grade="E-5", years_of_service=6.0, time_in_grade_years=1.5,
        diems_date="2020-06-01",          # after 1 Jan 2018 -> BRS, automatically
        duty_zip="28310",                 # Fort Bragg / Fayetteville MHA
        has_dependents=True,
        lives_in_government_housing=False,
        # Deployed, in a combat zone, drawing hostile fire pay. This gates
        # CZTE and makes the SDP the top of the priority waterfall.
        is_deployed=True, months_deployed_this_year=7,
        in_combat_zone=True, drawing_hostile_fire_pay=True,
        special_pay_monthly=675.0,        # HFP/IDP plus family separation
        special_pay_taxable=False,        # excluded while in the combat zone
        tsp_contribution_pct=0.03,        # below the 5% that earns the full match
        tsp_roth_share=1.0,
        tsp_traditional_balance=9_000.0, tsp_roth_balance=14_000.0,
        ira_roth_balance=4_500.0, ira_contributed_this_year=1_200.0,
        sdp_balance=2_500.0,
        sgli_coverage=500_000.0,
    )
    h.has_spouse = True
    h.n_dependents = 2
    h.spouse_income = SpouseIncome(
        employed=True, career_type=CAREER_LOCAL, annual_income=38_000.0,
        retirement_contribution_pct=0.02, employer_match_pct=0.02,
    )
    h.state_of_legal_residence = "Texas"
    h.current_state = "North Carolina"
    h.cash_savings = 3_500.0
    h.monthly_expenses = 4_200.0
    h.vehicles_value = 21_000.0
    h.debts = [
        # Taken out before entering service, so the SCRA 6% cap applies to it.
        Debt("Visa", 6_800.0, 0.2249, 180.0, "Credit card",
             incurred_before_service=True),
        Debt("Truck loan", 24_500.0, 0.0899, 520.0, "Auto loan"),
        Debt("Furniture, on-post lot", 2_400.0, 0.1799, 95.0, "Retail"),
    ]
    return h


def retired_ltc_26_years() -> Household:
    """
    A retired O-5 with 26 years and a 100% permanent-and-total VA rating.

    Retired pay: an O-5's basic pay tops out at the over-22 step, so all 36
    months of the high-3 sit at that rate — $12,394.80 a month in 2026 terms.
    Under High-3, 26 years gives a 65% multiplier, so 0.65 x $12,394.80 =
    $8,056.62 a month, $96,679 a year. DIEMS in 1999 with no CSB/REDUX
    election means High-3, not REDUX and not BRS.
    """
    high_three = 12_394.80
    multiplier = 0.025 * 26          # High-3: 2.5% a year
    h = Household(profile_name="Sample — Retired O-5, 26 years, 100% P&T")
    h.member = ServiceMember(
        name="", birth_year=1975, component=RETIRED, branch="Army",
        grade="O-5", years_of_service=26.0, time_in_grade_years=4.0,
        diems_date="1999-05-15",         # High-3 era
        took_csb_redux=False, opted_into_brs=False,
        has_dependents=True,
        retired_pay_monthly=round(high_three * multiplier, 2),
        va_disability_monthly=4_050.0,   # 100% with a spouse — replace from your award letter
        va_rating=100, va_rating_permanent_total=True,
        crdp_applies=True,               # 20+ years and a 50%+ rating
        sbp_elected=True,
        tsp_traditional_balance=700_000.0, tsp_roth_balance=100_000.0,
        ira_traditional_balance=180_000.0, ira_roth_balance=45_000.0,
        civilian_wages_annual=95_000.0,  # second career
        sgli_coverage=0.0,               # SGLI ended at separation
    )
    h.has_spouse = True
    h.n_dependents = 2
    h.spouse_income = SpouseIncome(
        employed=True, career_type=CAREER_LOCAL, annual_income=52_000.0,
        retirement_contribution_pct=0.06, employer_match_pct=0.03,
    )
    h.state_of_legal_residence = "Michigan"
    h.current_state = "Michigan"
    h.cash_savings = 60_000.0
    h.monthly_expenses = 9_000.0
    h.taxable_brokerage = 250_000.0
    h.home_value = 420_000.0
    h.mortgage_balance = 280_000.0
    h.vehicles_value = 46_000.0
    h.debts = []
    return h


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for stem, build in (("e5_6yrs_brs", e5_six_years),
                        ("retired_o5_26yrs", retired_ltc_26_years)):
        h = build()
        path = OUT / f"{stem}{storage.SUFFIX}"
        path.write_bytes(storage.to_download_bytes(h))

        # Round-trip through the same reader the uploader uses.
        back = storage.from_upload_bytes(path.read_bytes())
        assert back.to_dict() == h.to_dict(), f"{path.name} did not round-trip"
        print(f"{path.relative_to(OUT.parent)}  "
              f"({path.stat().st_size:,} bytes)  "
              f"{back.member.grade} {back.member.component}, "
              f"{back.member.years_of_service:g} yrs, "
              f"{back.member.retirement_system}")


if __name__ == "__main__":
    main()
