"""Friction item status transitions."""

from enum import StrEnum

from friction.domain.errors import InvalidTransitionError


class ItemStatus(StrEnum):
    """Lifecycle state of a friction item."""

    OPEN = "open"
    DONE = "done"
    DISMISSED = "dismissed"


_ALLOWED_TRANSITIONS: dict[ItemStatus, frozenset[ItemStatus]] = {
    ItemStatus.OPEN: frozenset({ItemStatus.DONE, ItemStatus.DISMISSED}),
    ItemStatus.DONE: frozenset({ItemStatus.OPEN}),
    ItemStatus.DISMISSED: frozenset({ItemStatus.OPEN}),
}


def validate_transition(current: ItemStatus, target: ItemStatus) -> bool:
    """Validate a transition and return whether it changes state."""
    if current == target:
        return False
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidTransitionError(current.value, target.value)
    return True

