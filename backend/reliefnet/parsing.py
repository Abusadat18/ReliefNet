"""Rule-based Hinglish message parser.

This is the offline fallback for the Intake agent and the fast path for load
tests. It returns the same shape as the LLM extraction schema."""
from __future__ import annotations

import re

from .areas.places import is_generic, norm as _norm

_NUM_WORDS = {
    "one": 1, "ek": 1, "two": 2, "do": 2, "three": 3, "teen": 3, "four": 4, "char": 4, "chaar": 4,
    "five": 5, "paanch": 5, "panch": 5, "six": 6, "chhe": 6, "seven": 7, "saat": 7, "eight": 8, "aath": 8,
    "nine": 9, "nau": 9, "ten": 10, "das": 10,
}
_NUM = r"(\d{1,3}|" + "|".join(_NUM_WORDS) + r")"

NEED_WORDS: dict[str, list[str]] = {
    "medicine": ["medicine", "medicines", "dawai", "dawa", "dava", "tablet", "tablets", "insulin", "bp ", "bp,",
                 "sugar ki", "inhaler", "oxygen", "dialysis"],
    "water": ["drinking water", "paani chahiye", "pani chahiye", "peene ka paani", "water bottle", "no water",
              "pani nahi", "paani nahi", "need water", "water chahiye", "water needed", "no clean water"],
    "food": ["food", "khana", "khaana", "ration", "bhojan", "roti", "hungry", "bhookh", "bhukh", "chura"],
    "evacuation": ["evacuat", "nikalo", "nikal", "stuck", "fanse", "phanse", "fasa", "trapped", "chhat", "chat pe",
                   "roof", "boat", "naav", "nav bhejo", "water entering", "paani ghar", "pani ghar",
                   "paani aa raha", "pani aa raha", "doob", "submerged"],
    "rescue": ["drowning", "doob raha", "rescue", "bachao", "save us"],
    "shelter": ["shelter", "camp", "rehne ki jagah", "ghar gir", "house collapsed", "no place to stay"],
    "blankets": ["blanket", "kambal", "kapde", "clothes", "tarpaulin", "tirpal"],
    "baby_food": ["baby food", "doodh", "milk", "formula", "infant"],
    "first_aid": ["injur", "chot", "bleeding", "khoon", "wound", "fracture", "snake", "saanp"],
    "sanitation": ["toilet", "sanitation", "sanitary", "pads"],
}
ELDERLY_WORDS = ["dadi", "dada", "nani", "nana", "elderly", "old man", "old woman", "old lady", "buzurg", "budhe",
                 "budhi", "grandmother", "grandfather", "senior citizen", "amma", "baba ji"]
CHILD_WORDS = ["kids", "children", "child", "bachche", "bacche", "bachhe", "baby", "infant", "bachcha", "beti",
               "beta"]
PREGNANT_WORDS = ["pregnant", "garbhvati", "delivery due", "disabled", "wheelchair", "viklang", "paralys"]
MEDICAL_WORDS = ["bp", "sugar", "diabetes", "heart", "asthma", "dialysis", "fever", "bukhar", "sick", "bimar",
                 "unconscious", "behosh"]
WATER_ENTERING = ["water entering", "paani ghar", "pani ghar", "paani aa raha", "pani aa raha", "water rising",
                  "paani badh", "pani badh", "submerged", "doob", "neck deep", "waist deep", "kamar tak"]
TRAPPED = ["stuck", "fanse", "phanse", "fasa", "trapped", "chhat", "roof", "cannot get out", "nikal nahi"]
CRITICAL = ["drowning", "doob raha", "unconscious", "behosh", "dying", "bleeding", "snake", "saanp", "heart attack",
            "pregnant", "labour", "labor pain"]
ROAD_WORDS = ["bridge", "pul", "road", "sadak", "path", "lane", "nh-12", "nh12", "rasta", "flyover", "setu",
              "marg", "underpass", "overbridge"]
FLOOD_WORDS = ["flooded", "flood", "doob", "submerged", "pani bhar", "paani bhar", "under water", "band hai",
               "blocked", "closed", "washed", "tut gaya", "toot"]
OPEN_WORDS = ["is open", "khul gaya", "open now", "clear now", "cleared", "chalu"]


# Words that only say "this is a road". A road name made only of these ("Main Road") fits many roads.
ROAD_TYPE_WORDS = {"road", "rd", "marg", "path", "lane", "gali", "street", "main", "flyover", "bridge", "setu",
                   "overbridge", "ramp", "no", "number", "the", "link", "cross", "new", "old", "of"}


def _road_text(text: str) -> str:
    """Normalised text with one spelling of a numbered road: "Rd No.6" and "road number 6" become "road 6"."""
    t = re.sub(r"\brd\b", "road", _norm(text))
    return re.sub(r"\b(road|gali|lane)\s+(?:no|nos|number|num|nr)\s*(?=\d)", r"\1 ", t)


def road_forms(name: str) -> set[str]:
    """The spellings of a road name that a message can contain.

    A generated name ("Lane near Kali Mandir 3") is not a name people type, so it has none.
    The importer adds the ward to a repeated name ("Road No.1, Lohanipur"); people type only "Road No.1"."""
    if " near " in f" {name.lower()} ":
        return set()
    base = name.split(",")[0]
    forms = {_norm(base), _road_text(base)}
    if all(w in ROAD_TYPE_WORDS for w in _road_text(base).split()):
        return set()
    return {f for f in forms if len(f) >= 4}


def location_clues(raw: str, neighbourhood_names: list[tuple[str, list[str]]] | None = None,
                   road_names: list[str] | None = None, taken: list[str] = ()) -> dict:
    """The neighbourhood and the road that a message names, by exact match against our own lists.

    The longest match wins. A road is skipped when its words are only part of a matched landmark
    name in `taken` ("kali mandir road" is an alias of Kali Mandir). Works with no model."""
    t = f" {_road_text(raw)} "
    hood, best = "", 0
    for name, aliases in neighbourhood_names or []:
        for alias in {_norm(name), *(_norm(a) for a in aliases)}:
            if len(alias) >= 3 and f" {alias} " in t and len(alias) > best:
                best, hood = len(alias), name
    inside = [f" {_road_text(x)} " for x in taken if x]
    road, best = "", 0
    for name in road_names or []:
        for form in road_forms(name):
            if f" {form} " in t and len(form) > best and not any(f" {form} " in x for x in inside):
                best, road = len(form), name.split(",")[0]
    return {"neighbourhood": hood, "road": road}


def _num(tok: str) -> int:
    return int(tok) if tok.isdigit() else _NUM_WORDS.get(tok, 0)


def _has(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


def parse_message(raw: str, landmark_names: list[tuple[str, list[str]]] | None = None,
                  neighbourhood_names: list[tuple[str, list[str]]] | None = None,
                  road_names: list[str] | None = None) -> dict:
    t = " " + re.sub(r"\s+", " ", raw.lower()) + " "
    people = 0
    m = re.search(_NUM + r"\s*(?:\+\s*)?(ppl|people|log|logon|members|member|persons|person|jan|family members|of us)", t)
    if m:
        people = _num(m.group(1))
    m = re.search(r"(?:we are|hum|hum log)\s+" + _NUM, t)
    if not people and m:
        people = _num(m.group(1))
    m = re.search(_NUM + r"\s*(kids|children|bachche|bacche|bachhe|child|bachcha)", t)
    children = _num(m.group(1)) if m else (1 if _has(t, CHILD_WORDS) else 0)
    m = re.search(_NUM + r"\s*(elderly|old|buzurg|senior)", t)
    elderly = _num(m.group(1)) if m else sum(1 for w in ["dadi", "dada", "nani", "nana"] if w in t) or (
        1 if _has(t, ELDERLY_WORDS) else 0
    )
    pregnant = 1 if _has(t, PREGNANT_WORDS) else 0
    needs = [n for n, words in NEED_WORDS.items() if _has(t, words)]
    if "rescue" in needs and "evacuation" not in needs:
        needs.append("evacuation")
    medical = next((w for w in MEDICAL_WORDS if re.search(rf"\b{re.escape(w)}\b", t)), "")
    if medical and "medicine" not in needs:
        needs.append("medicine")
    water_entering = _has(t, WATER_ENTERING)
    trapped = _has(t, TRAPPED)

    ward = 0
    m = re.search(r"(?:ward|wd|w\.)\s*(?:no\.?|number|num)?\s*(\d{1,2})", t)
    if m:
        ward = int(m.group(1))

    landmark, landmark_alias = "", ""
    if landmark_names:
        best = 0
        for name, aliases in landmark_names:
            for alias in [name.lower(), *aliases]:
                if re.search(rf"\b{re.escape(alias)}\b", t) and len(alias) > best:
                    best, landmark, landmark_alias = len(alias), name, alias
    clues = location_clues(raw, neighbourhood_names, road_names, taken=[landmark_alias])
    # "Birla Mandir Road" names a road, not the landmark that has the generic alias "mandir".
    if clues["road"] and landmark_alias and is_generic(landmark_alias) and any(
            f" {_road_text(landmark_alias)} " in f" {form} " and len(form) > len(landmark_alias)
            for form in road_forms(clues["road"])):
        landmark = ""

    name = ""
    m = re.search(r"\b([a-z]\.?\s?[a-z]{2,}|[a-z]{3,})\s+(?:family|parivar|pariwar|household)\b", t)
    if m and m.group(1).strip() not in {"the", "our", "my", "one", "this", "big", "poor", "whole", "ek", "hamara"}:
        name = m.group(1).strip()
    skip = {"stuck", "fanse", "here", "in", "at", "near", "my", "the", "help", "food", "water", "us", "please",
            "pls", "a", "an", "our", "hum", "relatives", "relative", "family"}
    for m in re.finditer(r"\b(?:my name is|mera naam|naam hai|i am|main|relatives?|uncle|aunty)\s+([a-z]+(?:\s[a-z]+)?)", t):
        if name:
            break
        words = [w for w in m.group(1).split() if w not in {"hai", "hain", "hu", "hoon"}]
        if words and words[0] not in skip:
            name = " ".join(words)
    name = name.title()

    road_name, road_status = "", ""
    is_road_msg = _has(t, ROAD_WORDS) and (_has(t, FLOOD_WORDS) or _has(t, OPEN_WORDS))
    if is_road_msg and not (people or trapped or (needs and needs != ["evacuation"])):
        road_status = "open" if _has(t, OPEN_WORDS) else "flooded"
        m = re.search(r"(nh-?12 bridge|nh-?12|old iron bridge|rail bridge|lane \d+"
                      r"|(?:[a-z0-9.]+ ){1,3}(?:road|path|marg|flyover|setu|overbridge|underpass|bridge|lane \d+))", t)
        road_name = m.group(1) if m else ""

    if "nobody has come" in t or "koi nahi aaya" in t or "no one came" in t or "no help" in t:
        needs = needs or ["food", "water"]

    if road_status:
        kind = "road_report"
    elif "?" in t and not (people or trapped or water_entering or "help" in t or "madad" in t):
        kind = "info"
    elif needs or people or trapped or water_entering or "help" in t or "madad" in t or "bachao" in t:
        kind = "help_request"
    elif _has(t, ["volunteer", "i can help", "donate", "madad kar sakte"]):
        kind = "volunteer_offer"
    elif "?" in t:
        kind = "info"
    else:
        kind = "other"

    if _has(t, CRITICAL) or (water_entering and (elderly or children or pregnant)):
        urgency = "critical" if _has(t, CRITICAL) else "high"
    elif water_entering or trapped or medical or elderly:
        urgency = "high"
    elif needs:
        urgency = "medium"
    else:
        urgency = "low"

    if kind == "help_request" and not people:
        people = max(1, children + elderly)
    summary_bits = []
    if people:
        summary_bits.append(f"{people} people")
    if elderly:
        summary_bits.append(f"{elderly} elderly")
    if children:
        summary_bits.append(f"{children} children")
    if needs:
        summary_bits.append("need " + ", ".join(needs))
    loc = landmark or (f"ward {ward}" if ward else "unknown place")
    # geo.resolve matches landmarks against location_text, so a road name stays out of it.
    where = landmark or clues["road"] or clues["neighbourhood"] or loc
    summary = (f"{name + ' family: ' if name else ''}" + "; ".join(summary_bits) + f" at {where}").strip()

    return {
        "kind": kind,
        "is_help_request": kind == "help_request",
        "contact_name": name,
        "people": people,
        "elderly": elderly,
        "children": children,
        "pregnant_or_disabled": pregnant,
        "medical_condition": medical,
        "needs": needs,
        "water_entering": water_entering,
        "trapped": trapped,
        "urgency": urgency,
        "ward": ward,
        "landmark": landmark,
        "neighbourhood": clues["neighbourhood"],
        "road": clues["road"],
        "location_text": loc,
        "road_name": road_name,
        "road_status": road_status,
        "summary_en": summary if kind == "help_request" else raw[:140],
        "language": "hinglish" if re.search(r"\b(hai|hain|ke|ka|ki|mein|chahiye|log)\b", t) else "english",
    }
