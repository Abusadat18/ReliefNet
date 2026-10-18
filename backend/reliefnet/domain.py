"""Shared vocabulary: request statuses, needs, and which team supplies cover them."""

# Message: RAW -> PARSED (or IGNORED when it is not a help request)
# Request: NEW -> RESOLVED -> TRIAGED -> ASSIGNED -> DELIVERED
# A duplicate request ends as MERGED; its needs move to the primary request.
REQUEST_FLOW = ["NEW", "RESOLVED", "TRIAGED", "ASSIGNED", "DELIVERED"]
ACTIVE_STATUSES = ["NEW", "RESOLVED", "TRIAGED", "ASSIGNED"]

NEEDS = [
    "medicine",
    "water",
    "food",
    "evacuation",
    "rescue",
    "shelter",
    "blankets",
    "baby_food",
    "first_aid",
    "sanitation",
]

# A need is covered when the team carries any one of these supplies.
NEED_SUPPLIES: dict[str, list[str]] = {
    "medicine": ["medicine"],
    "water": ["water"],
    "food": ["food"],
    "evacuation": ["boat", "evacuation"],
    "rescue": ["boat"],
    "shelter": ["evacuation", "boat"],
    "blankets": ["blankets"],
    "baby_food": ["baby_food", "food"],
    "first_aid": ["first_aid", "medicine"],
    "sanitation": ["water"],
}

# What a team can carry. Every supply in NEED_SUPPLIES is here.
SUPPLIES = ["food", "water", "medicine", "first_aid", "baby_food", "blankets", "boat", "evacuation"]

TEAM_NAME_MAX = 40
TEAM_CAPACITY_MAX = 20

URGENCY = ["low", "medium", "high", "critical"]

LESSON_KINDS = ["road_risk", "team_skill", "area_risk", "general"]

# Road travel speed for ETA. Boats are slower, but the route is the same graph.
SPEED_M_PER_MIN = 220.0


def coverage(needs: list[str], supplies: list[str]) -> float:
    if not needs:
        return 1.0
    covered = sum(1 for n in needs if any(s in supplies for s in NEED_SUPPLIES.get(n, [n])))
    return covered / len(needs)
