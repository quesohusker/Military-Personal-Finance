"""
Career timeline: promotions, PCS moves, and the pay they produce year by year.

A military career is event-driven in a way a civilian one is not. Pay does not
grow on a smooth curve -- it steps at longevity boundaries, jumps at promotion,
and BAH can move by thousands a month on a single PCS. Fort Sill to San Diego
is a raise of roughly $2,800 a month that no salary negotiation produced, and a
projection that models "3% annual growth" misses all of it.

So the profile carries a timeline, and every downstream projection reads pay
from it rather than from a growth rate.

The promotion timings here are AVERAGES and are meant to be overridden. Officer
timing is fairly predictable because DOPMA sets the promotion zones; enlisted
timing varies enormously by branch and specialty, and a member in an
overmanned MOS can sit at a grade for years past the average.
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field, asdict, fields as dataclass_fields

from engine.pay import grades as G
from engine.pay import bah as BAH
from engine.pay import bas as BAS
from engine.pay import basepay as BP


# --------------------------------------------------------------------------
# Default promotion timing -- years of service at which promotion TO a grade
# typically occurs. Averages, adjustable by the user.
# --------------------------------------------------------------------------

ENLISTED_DEFAULTS = {
    "E-2": 0.5, "E-3": 1.0, "E-4": 2.0, "E-5": 4.5, "E-6": 8.5,
    "E-7": 13.5, "E-8": 18.5, "E-9": 22.5,
}

# DOPMA promotion zones. Far more predictable than enlisted timing.
OFFICER_DEFAULTS = {
    "O-2": 1.5, "O-3": 4.0, "O-4": 10.0, "O-5": 16.0, "O-6": 22.0,
    "O-7": 26.0, "O-8": 29.0, "O-9": 32.0, "O-10": 35.0,
}

WARRANT_DEFAULTS = {
    "W-2": 2.0, "W-3": 6.0, "W-4": 12.0, "W-5": 20.0,
}

PROMOTION_NOTE = {
    "enlisted": ("Enlisted promotion timing varies more than any other number in "
                 "this app. It depends on your branch, your specialty and how "
                 "overmanned it is, and on cutoff scores that move every month. "
                 "Treat these as a starting point and set your own."),
    "officer": ("Officer promotion is governed by DOPMA promotion zones, so these "
                "timings are reasonably reliable through O-5. Selection to O-6 "
                "and above is competitive and far from automatic — model it as a "
                "possibility, not a plan."),
    "warrant": ("Warrant officer timing varies by branch and by the technical "
                "track. Adjust to your own community's pattern."),
}


def default_promotions(current_grade: str, current_yos: float) -> list:
    """Remaining promotions from the member's current grade, at typical timing."""
    try:
        grade = G.get(current_grade)
    except KeyError:
        return []

    if grade.category == G.ENLISTED:
        table, sort_key = ENLISTED_DEFAULTS, "E"
    elif grade.category == G.WARRANT:
        table, sort_key = WARRANT_DEFAULTS, "W"
    else:
        table, sort_key = OFFICER_DEFAULTS, "O"

    out = []
    for label, yos in sorted(table.items(), key=lambda kv: kv[1]):
        try:
            g = G.get(label)
        except KeyError:
            continue
        if g.sort <= grade.sort:
            continue
        # Never schedule a promotion in the past.
        out.append(Promotion(to_grade=label,
                             at_years_of_service=max(yos, current_yos + 0.5)))
    return out


def promotion_note(current_grade: str) -> str:
    try:
        cat = G.get(current_grade).category
    except KeyError:
        return ""
    if cat == G.ENLISTED:
        return PROMOTION_NOTE["enlisted"]
    if cat == G.WARRANT:
        return PROMOTION_NOTE["warrant"]
    return PROMOTION_NOTE["officer"]


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------

@dataclass
class Promotion:
    to_grade: str = ""
    at_years_of_service: float = 0.0
    confirmed: bool = False          # already has orders / a sequence number

    def to_dict(self) -> dict:
        return asdict(self)


# Typical tour lengths, for suggesting the next move.
TYPICAL_TOUR_YEARS = {"CONUS": 3.0, "OCONUS accompanied": 3.0,
                      "OCONUS unaccompanied": 1.0, "Training": 1.0}
TOUR_TYPES = list(TYPICAL_TOUR_YEARS)


@dataclass
class PCSMove:
    at_years_of_service: float = 0.0
    destination_zip: str = ""
    destination_label: str = ""
    tour_type: str = "CONUS"
    confirmed: bool = False          # has orders
    into_government_housing: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _event(cls, raw):
    """
    Rebuild one saved event, ignoring any key the class no longer carries.

    A plan file outlives the version of the app that wrote it, so a key that
    has since been renamed or removed must not raise on the way back in.
    """
    if not isinstance(raw, dict):
        return None
    known = {f.name for f in dataclass_fields(cls)}
    return cls(**{k: v for k, v in raw.items() if k in known})


@dataclass
class CareerTimeline:
    promotions: list = field(default_factory=list)
    moves: list = field(default_factory=list)
    separation_at_years_of_service: float = 20.0

    # Whether anyone has actually answered these questions. An empty promotion
    # list is a real answer -- "no more promotions" -- and is indistinguishable
    # from a plan nobody has opened the Career page on. Without this flag the
    # page would helpfully re-seed service averages over that answer on the
    # next load, which is exactly what persisting the timeline is meant to stop.
    entered: bool = False

    def to_dict(self) -> dict:
        return {"promotions": [p.to_dict() for p in self.promotions],
                "moves": [m.to_dict() for m in self.moves],
                "separation_at_years_of_service": self.separation_at_years_of_service,
                "entered": self.entered}

    @staticmethod
    def from_dict(d: dict) -> "CareerTimeline":
        """
        Rebuild from a saved plan, tolerating a file written by any version.

        Every key is optional: a plan saved before the timeline was part of the
        plan carries none of them, and must load as an untouched timeline
        rather than raise.
        """
        d = d if isinstance(d, dict) else {}
        try:
            sep = float(d.get("separation_at_years_of_service", 20.0))
        except (TypeError, ValueError):
            sep = 20.0
        return CareerTimeline(
            promotions=[p for p in (_event(Promotion, x)
                                    for x in (d.get("promotions") or [])) if p],
            moves=[m for m in (_event(PCSMove, x)
                               for x in (d.get("moves") or [])) if m],
            separation_at_years_of_service=sep,
            entered=bool(d.get("entered", False)),
        )


# --------------------------------------------------------------------------
# Projection
# --------------------------------------------------------------------------

@dataclass
class YearOfService:
    year: int = 0
    years_of_service: float = 0.0
    grade: str = ""
    promoted_this_year: bool = False
    duty_zip: str = ""
    duty_label: str = ""
    moved_this_year: bool = False

    basic_pay_monthly: float = 0.0
    bah_monthly: float = 0.0
    bas_monthly: float = 0.0
    special_pay_monthly: float = 0.0

    @property
    def taxable_monthly(self) -> float:
        return self.basic_pay_monthly + self.special_pay_monthly

    @property
    def nontaxable_monthly(self) -> float:
        return self.bah_monthly + self.bas_monthly

    @property
    def total_monthly(self) -> float:
        return self.taxable_monthly + self.nontaxable_monthly

    @property
    def total_annual(self) -> float:
        return self.total_monthly * 12.0

    @property
    def nontaxable_share(self) -> float:
        return (self.nontaxable_monthly / self.total_monthly) if self.total_monthly else 0.0


def project(member, timeline: CareerTimeline, start_year: int,
            years: int = 0, bah_data=None, basepay_table=None,
            annual_raise: float = 0.0) -> list[YearOfService]:
    """
    Walk the career forward one year at a time, applying promotions and moves.

    `annual_raise` compounds basic pay above the table, for projecting years
    beyond the published one. BAH is NOT inflated -- it is a market-set rate
    and guessing its trajectory adds error rather than removing it. BAS is not
    inflated for the same reason.
    """
    if bah_data is None:
        bah_data = BAH.load()
    if basepay_table is None:
        basepay_table = BP.load()

    end_yos = timeline.separation_at_years_of_service
    # CEILING, not round. The walk steps a whole year at a time from wherever
    # the member is NOW, and years of service is no longer a whole number --
    # intake derives it from the DIEMS date, so 6.3 is the ordinary case. With
    # `round` a member at 6.9 heading for 20 ran out of iterations at 19.9 and
    # the loop below never got the chance to land them on the target.
    n = years or max(1, int(math.ceil(end_yos - member.years_of_service - 1e-9)) + 1)

    promotions = sorted(timeline.promotions, key=lambda p: p.at_years_of_service)
    moves = sorted(timeline.moves, key=lambda m: m.at_years_of_service)

    grade = member.grade
    zipcode = member.duty_zip
    label = ""
    in_quarters = member.lives_in_government_housing
    rows: list[YearOfService] = []

    for i in range(n):
        yos = member.years_of_service + i
        year = start_year + i
        if yos > end_yos + 1e-9:
            # THE MEMBER CROSSES THE SEPARATION POINT DURING THIS YEAR, and the
            # year they cross it is a year they serve. Stopping at the last
            # whole step instead used to end a career SHORT of its own target:
            # from 6.3 years the steps run 6.3, 7.3 ... 19.3, and a member who
            # said "I separate at twenty" was modelled as separating at 19.3 --
            # which is on the wrong side of the twenty-year cliff, so
            # `pension_at_separation()` correctly priced no pension at all and
            # silently deleted a lifetime annuity.
            #
            # It never showed up while years of service was a whole number
            # typed by hand. It appeared the moment intake began deriving it
            # from the DIEMS date, which makes a fraction the ordinary case.
            if rows and rows[-1].years_of_service >= end_yos - 1e-9:
                break
            yos = end_yos

        promoted = False
        for p in promotions:
            if p.at_years_of_service <= yos:
                try:
                    if G.get(p.to_grade).sort > G.get(grade).sort:
                        grade = p.to_grade
                        promoted = abs(p.at_years_of_service - yos) < 1.0
                except KeyError:
                    continue

        moved = False
        for m in moves:
            if m.at_years_of_service <= yos:
                if m.destination_zip and m.destination_zip != zipcode:
                    moved = abs(m.at_years_of_service - yos) < 1.0
                zipcode = m.destination_zip or zipcode
                label = m.destination_label or label
                in_quarters = m.into_government_housing

        row = YearOfService(year=year, years_of_service=yos, grade=grade,
                            promoted_this_year=promoted, duty_zip=zipcode,
                            duty_label=label, moved_this_year=moved)

        bp = BP.lookup(grade, yos, basepay_table,
                       override_monthly=(member.basic_pay_monthly_override
                                         if i == 0 else 0.0))
        row.basic_pay_monthly = bp.monthly * ((1.0 + annual_raise) ** i)

        if in_quarters:
            row.bah_monthly = 0.0
        elif member.bah_monthly_override > 0 and i == 0:
            row.bah_monthly = member.bah_monthly_override
        else:
            b = BAH.lookup(zipcode, grade, member.has_dependents, bah_data)
            row.bah_monthly = b.monthly if b.found else (
                member.bah_monthly_override if member.bah_monthly_override > 0 else 0.0)
            if b.found and not label:
                row.duty_label = b.mha_name

        row.bas_monthly = (member.bas_monthly_override or
                           BAS.bas_monthly(G.is_officer(G.get(grade))).monthly)
        row.special_pay_monthly = member.special_pay_monthly
        rows.append(row)

    return rows


@dataclass
class MoveImpact:
    from_zip: str = ""
    to_zip: str = ""
    from_label: str = ""
    to_label: str = ""
    from_bah: float = 0.0
    to_bah: float = 0.0
    monthly_change: float = 0.0
    annual_change: float = 0.0
    found: bool = False
    note: str = ""


def compare_locations(from_zip: str, to_zip: str, grade: str,
                      has_dependents: bool, bah_data=None) -> MoveImpact:
    """
    What a move does to BAH. This is the single most useful number when orders
    arrive, and it is invisible in any civilian planning tool.
    """
    bah_data = bah_data if bah_data is not None else BAH.load()
    a = BAH.lookup(from_zip, grade, has_dependents, bah_data)
    b = BAH.lookup(to_zip, grade, has_dependents, bah_data)

    out = MoveImpact(from_zip=from_zip, to_zip=to_zip,
                     from_bah=a.monthly, to_bah=b.monthly,
                     from_label=a.mha_name, to_label=b.mha_name)
    if not (a.found and b.found):
        out.note = a.note or b.note or "One of these ZIP codes is not in the BAH tables."
        return out

    out.found = True
    out.monthly_change = b.monthly - a.monthly
    out.annual_change = out.monthly_change * 12.0

    if out.monthly_change > 0:
        out.note = (f"Your housing allowance rises {_money(out.monthly_change)} a "
                    f"month — {_money(out.annual_change)} a year, tax-free. Local "
                    f"housing costs are higher too, which is why the rate is "
                    f"higher; this is not a raise in real terms.")
    elif out.monthly_change < 0:
        out.note = (f"Your housing allowance falls {_money(-out.monthly_change)} a "
                    f"month — {_money(-out.annual_change)} a year. If you keep a "
                    f"mortgage at the old station, it does not fall with it.")
    else:
        out.note = "Your housing allowance is unchanged."
    return out


def _money(x: float) -> str:
    return f"${abs(x):,.0f}"
