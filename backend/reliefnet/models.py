"""Typed views of the graph nodes the agents work with.

Each model mirrors the properties of one node label. Unknown properties
(such as lease fields) are ignored, so a model can be built straight from
`properties(n)` in a query result."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class Node(BaseModel):
    model_config = ConfigDict(extra="ignore")

    def props(self) -> dict[str, Any]:
        """Properties to write back to the graph (unset values are left out)."""
        return self.model_dump(exclude_none=True)


class Message(Node):
    """A raw message exactly as it arrived (episodic memory)."""

    id: str
    text: str = ""
    channel: str = "unknown"
    sender: str = ""
    received_at: int | None = None
    status: str = "RAW"
    kind: str | None = None
    sim_household: str = ""


class Request(Node):
    """One structured help request, created by Intake from one message."""

    id: str
    status: str = "NEW"
    created_at: int | None = None
    channel: str = "unknown"
    name: str = ""
    people: int = 1
    elderly: int = 0
    children: int = 0
    pregnant_or_disabled: int = 0
    medical: str = ""
    needs: list[str] = []
    water_entering: bool = False
    trapped: bool = False
    urgency: str = "medium"
    ward: int = 0
    landmark: str = ""
    location_text: str = ""
    lat: float = 0.0
    lon: float = 0.0
    geo_confidence: str = "none"
    summary: str = ""
    desc: str = ""
    parsed_by: str = ""
    sim_household: str = ""
    # Written by later stages.
    family: str | None = None
    merged_into: str | None = None
    priority: int | None = None
    reason: str | None = None
    cluster_bonus: int | None = None
    team: str | None = None
    eta_min: float | None = None
    route_roads: list[str] | None = None
    blocked_reason: str | None = None


class Candidate(Node):
    """A similar earlier request found by vector search, with its household."""

    id: str
    name: str = ""
    people: int = 0
    elderly: int = 0
    children: int = 0
    ward: int = 0
    landmark: str = ""
    lat: float
    lon: float
    summary: str = ""
    status: str = ""
    family: str
    similarity: float


class Family(Node):
    """One household. Many requests can point to it (semantic memory)."""

    id: str
    name: str = ""
    people: int = 1
    elderly: int = 0
    children: int = 0
    needs: list[str] = []
    lat: float = 0.0
    lon: float = 0.0
    ward: int = 0
    landmark: str = ""
    status: str = "UNSERVED"
    first_seen: int | None = None
    last_seen: int | None = None
    requests: int = 1
    served_at: int | None = None


class Lesson(Node):
    """Something the Learner found that changes later decisions (procedural memory)."""

    key: str
    kind: str
    target: str = ""
    need: str = ""
    after_hour: int | None = None
    text: str = ""
    confidence: float = 0.5
    seen: int = 0
    by: str = "rules"


class Team(Node):
    """A field team and how many open assignments it has now."""

    name: str
    supplies: list[str] = []
    base: str
    capacity: int = 3
    load: int = 0
