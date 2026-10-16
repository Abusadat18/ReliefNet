from .coordinator import ShiftScheduler
from .dedupe import DedupeAgent
from .dispatch import DispatchAgent
from .intake import IntakeAgent
from .learner import LearnerAgent
from .triage import TriageAgent

AGENT_TYPES = {
    "intake": (IntakeAgent, "Intake"),
    "dedupe": (DedupeAgent, "Dedupe"),
    "triage": (TriageAgent, "Triage"),
    "dispatch": (DispatchAgent, "Dispatch"),
    "learner": (LearnerAgent, "Learner"),
    "coordinator": (ShiftScheduler, "Coordinator"),
}
