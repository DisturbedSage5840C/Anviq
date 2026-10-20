"""A teacher's daily allowance of paid model steps.

Every Plan, Reflect, Ask, Mirror and practice turn calls a paid model, so each is charged first.
The router depends on this port; the Redis counter lives in `app.channel.model_budget`.
"""

from typing import Protocol


class ModelBudget(Protocol):
    """What the router needs to cap a teacher's paid model use."""

    async def spend(self, teacher: bytes) -> bool:
        """Charge one model step to this teacher today. False once the day's allowance is used."""
        ...
