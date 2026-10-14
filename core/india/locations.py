"""
Indian state / union-territory and city masters.

Single source of truth for every location dropdown, validation and document in
the app. Cities are keyed by state code so an invalid pairing (e.g. Telangana →
Chennai) is rejected structurally rather than by a hand-written check that
drifts.

Professional Tax is levied by STATE, not centrally, so the PT flag lives here
next to the state it belongs to — see core/india/statutory.py for the amounts.
"""

from __future__ import annotations

from typing import NamedTuple


class State(NamedTuple):
    code: str
    name: str
    kind: str          # "STATE" | "UT"
    levies_pt: bool    # whether the state levies Professional Tax


# Ordered as they conventionally appear in Indian HR systems: states first
# alphabetically, then union territories.
STATES: tuple[State, ...] = (
    State("AP", "Andhra Pradesh", "STATE", True),
    State("AR", "Arunachal Pradesh", "STATE", False),
    State("AS", "Assam", "STATE", True),
    State("BR", "Bihar", "STATE", True),
    State("CG", "Chhattisgarh", "STATE", True),
    State("GA", "Goa", "STATE", True),
    State("GJ", "Gujarat", "STATE", True),
    State("HR", "Haryana", "STATE", False),
    State("HP", "Himachal Pradesh", "STATE", False),
    State("JH", "Jharkhand", "STATE", True),
    State("KA", "Karnataka", "STATE", True),
    State("KL", "Kerala", "STATE", True),
    State("MP", "Madhya Pradesh", "STATE", True),
    State("MH", "Maharashtra", "STATE", True),
    State("MN", "Manipur", "STATE", True),
    State("ML", "Meghalaya", "STATE", True),
    State("MZ", "Mizoram", "STATE", True),
    State("NL", "Nagaland", "STATE", True),
    State("OD", "Odisha", "STATE", True),
    State("PB", "Punjab", "STATE", True),
    State("RJ", "Rajasthan", "STATE", False),
    State("SK", "Sikkim", "STATE", True),
    State("TN", "Tamil Nadu", "STATE", True),
    State("TS", "Telangana", "STATE", True),
    State("TR", "Tripura", "STATE", True),
    State("UP", "Uttar Pradesh", "STATE", False),
    State("UK", "Uttarakhand", "STATE", False),
    State("WB", "West Bengal", "STATE", True),
    # Union Territories
    State("AN", "Andaman and Nicobar Islands", "UT", False),
    State("CH", "Chandigarh", "UT", False),
    State("DN", "Dadra and Nagar Haveli and Daman and Diu", "UT", False),
    State("DL", "Delhi", "UT", False),
    State("JK", "Jammu and Kashmir", "UT", False),
    State("LA", "Ladakh", "UT", False),
    State("LD", "Lakshadweep", "UT", False),
    State("PY", "Puducherry", "UT", True),
)

STATE_BY_CODE: dict[str, State] = {s.code: s for s in STATES}
STATE_BY_NAME: dict[str, State] = {s.name.lower(): s for s in STATES}

# Employment centres by state. Not exhaustive — these are the locations an
# employer realistically posts a role to.
CITIES: dict[str, tuple[str, ...]] = {
    "AP": ("Visakhapatnam", "Vijayawada", "Guntur", "Tirupati", "Kakinada", "Nellore"),
    "AS": ("Guwahati", "Dibrugarh"),
    "BR": ("Patna", "Gaya"),
    "CG": ("Raipur", "Bhilai"),
    "GA": ("Panaji", "Margao"),
    "GJ": ("Ahmedabad", "Surat", "Vadodara", "Gandhinagar", "Rajkot"),
    "HR": ("Gurugram", "Faridabad", "Panchkula", "Hisar"),
    "HP": ("Shimla", "Baddi"),
    "JH": ("Ranchi", "Jamshedpur"),
    "KA": ("Bengaluru", "Mysuru", "Mangaluru", "Hubballi", "Belagavi"),
    "KL": ("Kochi", "Thiruvananthapuram", "Kozhikode", "Thrissur"),
    "MP": ("Indore", "Bhopal", "Jabalpur", "Gwalior"),
    "MH": ("Mumbai", "Pune", "Nagpur", "Nashik", "Aurangabad", "Thane", "Navi Mumbai"),
    "OD": ("Bhubaneswar", "Cuttack", "Rourkela"),
    "PB": ("Ludhiana", "Mohali", "Amritsar", "Jalandhar"),
    "RJ": ("Jaipur", "Jodhpur", "Udaipur", "Kota"),
    "TN": ("Chennai", "Coimbatore", "Madurai", "Tiruchirappalli", "Salem", "Hosur"),
    "TS": ("Hyderabad", "Warangal", "Karimnagar", "Nizamabad"),
    "UP": ("Noida", "Greater Noida", "Ghaziabad", "Lucknow", "Kanpur", "Varanasi", "Prayagraj"),
    "UK": ("Dehradun", "Haridwar", "Roorkee"),
    "WB": ("Kolkata", "Siliguri", "Durgapur", "Howrah"),
    "AN": ("Port Blair",),
    "CH": ("Chandigarh",),
    "DL": ("New Delhi", "Delhi", "Dwarka", "Rohini"),
    "JK": ("Srinagar", "Jammu"),
    "PY": ("Puducherry",),
    "AR": ("Itanagar",),
    "MN": ("Imphal",),
    "ML": ("Shillong",),
    "MZ": ("Aizawl",),
    "NL": ("Kohima", "Dimapur"),
    "SK": ("Gangtok",),
    "TR": ("Agartala",),
    "LA": ("Leh",),
    "LD": ("Kavaratti",),
    "DN": ("Daman", "Silvassa"),
}


def is_valid_state(code: str) -> bool:
    return code.upper() in STATE_BY_CODE


def cities_for(state_code: str) -> tuple[str, ...]:
    return CITIES.get(state_code.upper(), ())


def is_valid_city(state_code: str, city: str) -> bool:
    """
    True only when the city genuinely belongs to the state. This is the check
    that makes `Telangana → Chennai` impossible; comparison is case-insensitive
    because the value may arrive from a free-text form.
    """
    return city.strip().lower() in {c.lower() for c in cities_for(state_code)}


def state_name(code: str) -> str:
    s = STATE_BY_CODE.get(code.upper())
    return s.name if s else code


def levies_professional_tax(state_code: str) -> bool:
    s = STATE_BY_CODE.get(state_code.upper())
    return bool(s and s.levies_pt)


# Metro classification drives the HRA exemption rate (50% vs 40% of Basic)
# under the Income Tax Act. Only these four are metros for that purpose —
# a common and expensive thing to get wrong.
HRA_METRO_CITIES: frozenset[str] = frozenset(
    {"mumbai", "delhi", "new delhi", "kolkata", "chennai"}
)


def is_hra_metro(city: str) -> bool:
    return city.strip().lower() in HRA_METRO_CITIES


PINCODE_RE = r"^[1-9][0-9]{5}$"
PAN_RE = r"^[A-Z]{5}[0-9]{4}[A-Z]$"
AADHAAR_RE = r"^[2-9][0-9]{11}$"          # never starts 0 or 1
IFSC_RE = r"^[A-Z]{4}0[A-Z0-9]{6}$"       # 5th char is always '0'
UAN_RE = r"^[0-9]{12}$"
