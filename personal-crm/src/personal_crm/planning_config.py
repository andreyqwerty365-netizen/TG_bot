"""Server policy bounds for local proposals, independent of model prompts."""
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class PlanningPolicy:
    early_horizon_days: int = 7
    early_lead_days: int = 2
    history_days: int = 14
    required_choices: int = 3
    task_limit: int = 100

    def __post_init__(self):
        if (not 1 <= self.early_horizon_days <= 365 or not 0 <= self.early_lead_days <= 365
                or not 1 <= self.history_days <= 365 or not 3 <= self.required_choices <= 20
                or not 1 <= self.task_limit <= 1000):
            raise ValueError("Invalid planning policy bounds")

    @classmethod
    def from_env(cls):
        return cls(**{name: int(os.getenv("CRM_PLANNING_" + name.upper(), default))
                      for name, default in (("early_horizon_days", 7), ("early_lead_days", 2),
                         ("history_days", 14), ("required_choices", 3), ("task_limit", 100))})
