"""
Pay grades, ranks and the shape of the basic pay table.

The grade list is not simply E-1..E-9 / W-1..W-5 / O-1..O-10. The pay table also
carries O-1E, O-2E and O-3E -- officers with at least four years of prior
enlisted or warrant service, who are paid on a separate, higher line. Omitting
them silently underpays a mustang, and they are common enough that a military
app that cannot represent them is not credible.
"""

from __future__ import annotations
from dataclasses import dataclass

ENLISTED = "Enlisted"
WARRANT = "Warrant Officer"
OFFICER = "Officer"
OFFICER_PRIOR_ENLISTED = "Officer with prior enlisted service"


@dataclass(frozen=True)
class Grade:
    code: str            # "E05", matching the DTMO BAH column codes
    label: str           # "E-5"
    category: str
    sort: int
    army: str = ""
    navy: str = ""
    air_force: str = ""
    marines: str = ""

    def title(self, branch: str = "") -> str:
        b = (branch or "").lower()
        if b.startswith("army"): return self.army or self.label
        if b.startswith("navy") or b.startswith("coast"): return self.navy or self.label
        if b.startswith("air") or b.startswith("space"): return self.air_force or self.label
        if b.startswith("marine"): return self.marines or self.label
        return self.label


def _g(code, label, category, sort, army="", navy="", af="", usmc=""):
    return Grade(code, label, category, sort, army, navy, af, usmc)


GRADES: list[Grade] = [
    _g("E01", "E-1", ENLISTED, 1, "Private", "Seaman Recruit", "Airman Basic", "Private"),
    _g("E02", "E-2", ENLISTED, 2, "Private", "Seaman Apprentice", "Airman", "Private First Class"),
    _g("E03", "E-3", ENLISTED, 3, "Private First Class", "Seaman", "Airman First Class", "Lance Corporal"),
    _g("E04", "E-4", ENLISTED, 4, "Specialist / Corporal", "Petty Officer 3rd Class", "Senior Airman", "Corporal"),
    _g("E05", "E-5", ENLISTED, 5, "Sergeant", "Petty Officer 2nd Class", "Staff Sergeant", "Sergeant"),
    _g("E06", "E-6", ENLISTED, 6, "Staff Sergeant", "Petty Officer 1st Class", "Technical Sergeant", "Staff Sergeant"),
    _g("E07", "E-7", ENLISTED, 7, "Sergeant First Class", "Chief Petty Officer", "Master Sergeant", "Gunnery Sergeant"),
    _g("E08", "E-8", ENLISTED, 8, "Master Sergeant / First Sergeant", "Senior Chief Petty Officer", "Senior Master Sergeant", "Master Sergeant / First Sergeant"),
    _g("E09", "E-9", ENLISTED, 9, "Sergeant Major", "Master Chief Petty Officer", "Chief Master Sergeant", "Master Gunnery Sergeant / Sergeant Major"),

    _g("W01", "W-1", WARRANT, 11, "Warrant Officer 1", "Warrant Officer 1", "", "Warrant Officer 1"),
    _g("W02", "W-2", WARRANT, 12, "Chief Warrant Officer 2", "Chief Warrant Officer 2", "", "Chief Warrant Officer 2"),
    _g("W03", "W-3", WARRANT, 13, "Chief Warrant Officer 3", "Chief Warrant Officer 3", "", "Chief Warrant Officer 3"),
    _g("W04", "W-4", WARRANT, 14, "Chief Warrant Officer 4", "Chief Warrant Officer 4", "", "Chief Warrant Officer 4"),
    _g("W05", "W-5", WARRANT, 15, "Chief Warrant Officer 5", "Chief Warrant Officer 5", "", "Chief Warrant Officer 5"),

    _g("O01E", "O-1E", OFFICER_PRIOR_ENLISTED, 21),
    _g("O02E", "O-2E", OFFICER_PRIOR_ENLISTED, 22),
    _g("O03E", "O-3E", OFFICER_PRIOR_ENLISTED, 23),

    _g("O01", "O-1", OFFICER, 31, "Second Lieutenant", "Ensign", "Second Lieutenant", "Second Lieutenant"),
    _g("O02", "O-2", OFFICER, 32, "First Lieutenant", "Lieutenant Junior Grade", "First Lieutenant", "First Lieutenant"),
    _g("O03", "O-3", OFFICER, 33, "Captain", "Lieutenant", "Captain", "Captain"),
    _g("O04", "O-4", OFFICER, 34, "Major", "Lieutenant Commander", "Major", "Major"),
    _g("O05", "O-5", OFFICER, 35, "Lieutenant Colonel", "Commander", "Lieutenant Colonel", "Lieutenant Colonel"),
    _g("O06", "O-6", OFFICER, 36, "Colonel", "Captain", "Colonel", "Colonel"),
    _g("O07", "O-7", OFFICER, 37, "Brigadier General", "Rear Admiral (lower half)", "Brigadier General", "Brigadier General"),
    _g("O08", "O-8", OFFICER, 38, "Major General", "Rear Admiral", "Major General", "Major General"),
    _g("O09", "O-9", OFFICER, 39, "Lieutenant General", "Vice Admiral", "Lieutenant General", "Lieutenant General"),
    _g("O10", "O-10", OFFICER, 40, "General", "Admiral", "General", "General"),
]

BY_CODE = {g.code: g for g in GRADES}
BY_LABEL = {g.label: g for g in GRADES}
GRADE_LABELS = [g.label for g in GRADES]

BRANCHES = ["Army", "Navy", "Air Force", "Marine Corps", "Space Force", "Coast Guard"]

# Years-of-service columns in the DFAS basic pay table. A cell means "over N
# years"; the first is under 2.
YOS_COLUMNS = [0, 2, 3, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 34, 36, 38, 40]


def get(label_or_code: str) -> Grade:
    key = (label_or_code or "").strip().upper()
    if key in BY_CODE:
        return BY_CODE[key]
    if key in BY_LABEL:
        return BY_LABEL[key]
    # Accept "E5" as well as "E-5"
    if len(key) >= 2 and key[0] in "EWO":
        digits = "".join(c for c in key[1:] if c.isdigit())
        suffix = "E" if key.endswith("E") and len(key) > 2 else ""
        if digits:
            padded = f"{key[0]}{int(digits):02d}{suffix}"
            if padded in BY_CODE:
                return BY_CODE[padded]
    raise KeyError(f"Unknown pay grade: {label_or_code!r}")


def yos_column(years: float) -> int:
    """The pay-table column a given length of service falls in."""
    col = 0
    for boundary in YOS_COLUMNS:
        if years >= boundary:
            col = boundary
        else:
            break
    return col


def is_officer(grade: Grade) -> bool:
    return grade.category in (OFFICER, OFFICER_PRIOR_ENLISTED)
