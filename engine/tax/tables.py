"""
Default tax tables for the Roth conversion model.

EVERY value in this file is a *default*. The app exposes all of them as editable
inputs on the Assumptions page. Nothing here is hard-coded into the math -- the
engine reads whatever the user supplies.

All figures are stated in 2026 dollars. The projection runs in real (inflation-
adjusted) terms, so bracket boundaries that Congress indexes to inflation stay
constant across the projection. Thresholds Congress does NOT index -- Social
Security provisional-income thresholds, NIIT thresholds -- are deflated each
year by the engine, which is exactly why they bite harder over time.

Sources are the IRS annual inflation-adjustment revenue procedure and the CMS
Medicare premium notice. Verify against current IRS/CMS publications before
relying on the output for a real decision.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Filing statuses
# --------------------------------------------------------------------------
MFJ = "Married filing jointly"
SINGLE = "Single"
FILING_STATUSES = [MFJ, SINGLE]

# --------------------------------------------------------------------------
# Federal ordinary-income brackets, 2026 (post-OBBBA; TCJA rates made permanent)
# Each entry: (upper bound of the band in taxable income, marginal rate)
# The final band uses float("inf").
# --------------------------------------------------------------------------
FEDERAL_BRACKETS_2026 = {
    MFJ: [
        (24_800, 0.10),
        (100_800, 0.12),
        (211_100, 0.22),
        (402_200, 0.24),
        (510_300, 0.32),
        (765_600, 0.35),
        (float("inf"), 0.37),
    ],
    SINGLE: [
        (12_400, 0.10),
        (50_400, 0.12),
        (105_550, 0.22),
        (201_100, 0.24),
        (255_150, 0.32),
        (640_600, 0.35),
        (float("inf"), 0.37),
    ],
}

# --------------------------------------------------------------------------
# Pre-TCJA rate schedule, restated in 2026 dollars.
# Used by the "rates revert to pre-TCJA law" scenario. The 2017 bracket
# boundaries are inflated to 2026 purchasing power (~1.29x) and paired with the
# pre-TCJA marginal rates of 10/15/25/28/33/35/39.6.
# --------------------------------------------------------------------------
PRE_TCJA_BRACKETS_2026 = {
    MFJ: [
        (24_100, 0.10),
        (97_900, 0.15),
        (197_400, 0.25),
        (300_700, 0.28),
        (537_100, 0.33),
        (606_400, 0.35),
        (float("inf"), 0.396),
    ],
    SINGLE: [
        (12_000, 0.10),
        (48_900, 0.15),
        (118_500, 0.25),
        (247_100, 0.28),
        (537_100, 0.33),
        (539_600, 0.35),
        (float("inf"), 0.396),
    ],
}

# Pre-TCJA deduction regime, in 2026 dollars. The standard deduction was roughly
# half of today's, offset partly by a per-person personal exemption.
PRE_TCJA_STANDARD_DEDUCTION = {MFJ: 16_800, SINGLE: 8_400}
PRE_TCJA_PERSONAL_EXEMPTION = 5_400  # per person

# --------------------------------------------------------------------------
# Standard deduction, 2026
# --------------------------------------------------------------------------
STANDARD_DEDUCTION_2026 = {MFJ: 32_200, SINGLE: 16_100}

# Extra standard deduction for taxpayers age 65+ (per qualifying person)
ADDITIONAL_STD_DEDUCTION_65 = {MFJ: 1_650, SINGLE: 2_050}

# OBBBA "senior deduction": an extra deduction per person age 65+, phasing out
# above the MAGI threshold at the given rate. Scheduled to expire after 2028 --
# the app exposes the expiry year so the user can test extending it.
SENIOR_DEDUCTION_AMOUNT = 6_000
SENIOR_DEDUCTION_PHASEOUT_START = {MFJ: 150_000, SINGLE: 75_000}
SENIOR_DEDUCTION_PHASEOUT_RATE = 0.06
SENIOR_DEDUCTION_EXPIRY_YEAR = 2028

# --------------------------------------------------------------------------
# Long-term capital gains / qualified dividend brackets, 2026
# Entry: (upper bound of taxable income, rate)
# --------------------------------------------------------------------------
LTCG_BRACKETS_2026 = {
    MFJ: [(98_900, 0.00), (613_700, 0.15), (float("inf"), 0.20)],
    SINGLE: [(49_450, 0.00), (545_500, 0.15), (float("inf"), 0.20)],
}

# --------------------------------------------------------------------------
# Social Security taxation. These thresholds have been fixed in nominal dollars
# since 1984 and 1993 and are NOT indexed. The engine deflates them every year.
# --------------------------------------------------------------------------
SS_PROVISIONAL_TIER1 = {MFJ: 32_000, SINGLE: 25_000}
SS_PROVISIONAL_TIER2 = {MFJ: 44_000, SINGLE: 34_000}
SS_MAX_TAXABLE_SHARE = 0.85

# --------------------------------------------------------------------------
# Net Investment Income Tax. Also unindexed since 2013.
# --------------------------------------------------------------------------
NIIT_RATE = 0.038
NIIT_THRESHOLD = {MFJ: 250_000, SINGLE: 200_000}

# --------------------------------------------------------------------------
# Medicare Part B / Part D IRMAA, 2026.
# Surcharges are per person, per month. MAGI is from two years prior.
#
# MILITARY NOTE: TRICARE For Life requires enrollment in Medicare Part B. A
# military retiree at 65 pays Part B premiums and is exposed to IRMAA exactly
# like everyone else. TFL is not an exemption.
#
# Entry: (MAGI upper bound, monthly Part B total, monthly Part D surcharge)
# --------------------------------------------------------------------------
IRMAA_PART_B_STANDARD = 202.90  # monthly, 2026 standard premium

# CHECKED 2026-09-10 against ssa.gov's Medicare Premiums page (browser save;
# ssa.gov refuses automated requests). Part B is the standard premium plus a
# surcharge of 81.20 / 202.90 / 324.60 / 446.30 / 487.00. The Part D column
# here had been the 2025 amounts -- 13.70 through 85.80 re-derive exactly from
# a 2025 base beneficiary premium, which is how the staleness showed up.
IRMAA_TIERS_2026 = {
    MFJ: [
        (218_000, 202.90, 0.00),
        (274_000, 284.10, 14.50),
        (342_000, 405.80, 37.50),
        (410_000, 527.50, 60.40),
        (750_000, 649.20, 83.30),
        (float("inf"), 689.90, 91.00),
    ],
    SINGLE: [
        (109_000, 202.90, 0.00),
        (137_000, 284.10, 14.50),
        (171_000, 405.80, 37.50),
        (205_000, 527.50, 60.40),
        (500_000, 649.20, 83.30),
        (float("inf"), 689.90, 91.00),
    ],
    # Married filing separately gets its own two-step schedule, and its top
    # surcharge is 487.90 rather than the 487.00 every other status pays.
    # Not modelled elsewhere in the app; recorded so it is not re-derived
    # wrongly from the joint figures.
    "MFS_2026": [
        (109_000, 202.90, 0.00),
        (391_000, 649.20, 83.30),
        (float("inf"), 690.80, 91.00),
    ],
}

IRMAA_LOOKBACK_YEARS = 2

# --------------------------------------------------------------------------
# IRS Uniform Lifetime Table (post-2022). Divisor by age.
# Used for RMDs when the spouse is not more than 10 years younger.
# --------------------------------------------------------------------------
UNIFORM_LIFETIME_TABLE = {
    72: 27.4, 73: 26.5, 74: 25.5, 75: 24.6, 76: 23.7, 77: 22.9, 78: 22.0,
    79: 21.1, 80: 20.2, 81: 19.4, 82: 18.5, 83: 17.7, 84: 16.8, 85: 16.0,
    86: 15.2, 87: 14.4, 88: 13.7, 89: 12.9, 90: 12.2, 91: 11.5, 92: 10.8,
    93: 10.1, 94: 9.5, 95: 8.9, 96: 8.4, 97: 7.8, 98: 7.3, 99: 6.8,
    100: 6.4, 101: 6.0, 102: 5.6, 103: 5.2, 104: 4.9, 105: 4.6, 106: 4.3,
    107: 4.1, 108: 3.9, 109: 3.7, 110: 3.5, 111: 3.4, 112: 3.3, 113: 3.1,
    114: 3.0, 115: 2.9, 116: 2.8, 117: 2.7, 118: 2.5, 119: 2.3, 120: 2.0,
}

# Required Beginning Date by birth year, per SECURE 2.0.
RMD_AGE_BY_BIRTH_YEAR = [
    (1950, 72),   # born 1950 or earlier
    (1959, 73),   # born 1951-1959
    (9999, 75),   # born 1960 or later
]

# --------------------------------------------------------------------------
# Social Security claiming adjustment relative to Full Retirement Age.
# Benefit is reduced 5/9 of 1% per month for the first 36 months early, then
# 5/12 of 1% per month beyond that. Delayed credits are 8% per year to age 70.
# --------------------------------------------------------------------------
SS_EARLY_REDUCTION_FIRST_36 = 5.0 / 9.0 / 100.0   # per month
SS_EARLY_REDUCTION_BEYOND_36 = 5.0 / 12.0 / 100.0  # per month
SS_DELAYED_CREDIT_PER_YEAR = 0.08
SS_MIN_CLAIM_AGE = 62
SS_MAX_CLAIM_AGE = 70


def full_retirement_age(birth_year: int) -> float:
    """Social Security Full Retirement Age in years, by birth year."""
    if birth_year <= 1937:
        return 65.0
    if birth_year <= 1942:
        return 65.0 + (birth_year - 1937) * (2.0 / 12.0)
    if birth_year <= 1954:
        return 66.0
    if birth_year <= 1959:
        return 66.0 + (birth_year - 1954) * (2.0 / 12.0)
    return 67.0


def rmd_age_for_birth_year(birth_year: int) -> int:
    """First age at which an RMD is required, per SECURE 2.0."""
    for cutoff, age in RMD_AGE_BY_BIRTH_YEAR:
        if birth_year <= cutoff:
            return age
    return 75


# --------------------------------------------------------------------------
# Survivor benefits
# --------------------------------------------------------------------------
# Survivor Benefit Plan pays this share of the elected base amount of retired
# pay. SBP annuity is taxable income to the survivor.
SBP_ANNUITY_RATE = 0.55

# Dependency and Indemnity Compensation: tax-free monthly payment to the
# surviving spouse of a veteran who dies of a service-connected condition, or
# who was rated totally disabled for the required period. 2026 base rate.
# The SBP-DIC offset ("widow's tax") was fully repealed effective 2023, so a
# survivor may receive both SBP and DIC.
DIC_BASE_MONTHLY_2026 = 1_712.19

# --------------------------------------------------------------------------
# Contribution and conversion limits, 2026
# --------------------------------------------------------------------------
IRA_CONTRIBUTION_LIMIT = 7_500
IRA_CATCHUP_50 = 1_100
EMPLOYER_PLAN_DEFERRAL_LIMIT = 24_500
EMPLOYER_PLAN_CATCHUP_50 = 8_000
EMPLOYER_PLAN_CATCHUP_60_63 = 11_250  # SECURE 2.0 "super catch-up"

# --------------------------------------------------------------------------
# Reference label shown in the UI so the user knows what vintage they are on.
# --------------------------------------------------------------------------
TAX_YEAR_BASIS = 2026
TABLE_VINTAGE_NOTE = (
    "Defaults reflect 2026 federal law as enacted through the One Big Beautiful "
    "Bill Act (July 2025), which made the TCJA rate schedule permanent. Verify "
    "against current IRS and CMS publications before acting."
)
