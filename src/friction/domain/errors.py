"""Stable application and domain errors."""

from collections.abc import Mapping
from typing import Any


class FrictionError(Exception):
    """Base exception with a stable machine-readable code."""

    code = "friction_error"

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = dict(details or {})


class ItemNotFoundError(FrictionError):
    """Raised when no item matches an identifier."""

    code = "not_found"

    def __init__(self, identifier: str) -> None:
        super().__init__(
            f"No friction item matches {identifier!r}.",
            details={"identifier": identifier},
        )


class AmbiguousIdentifierError(FrictionError):
    """Raised when a UUID prefix matches multiple items."""

    code = "ambiguous_identifier"

    def __init__(self, identifier: str) -> None:
        super().__init__(
            f"Friction item prefix {identifier!r} is ambiguous.",
            details={"identifier": identifier},
        )


class RevisionConflictError(FrictionError):
    """Raised when optimistic concurrency detects a stale write."""

    code = "revision_conflict"

    def __init__(self, item_id: str, expected: int, actual: int) -> None:
        super().__init__(
            f"Friction item {item_id} changed from revision {expected} to {actual}.",
            details={
                "item_id": item_id,
                "expected_revision": expected,
                "actual_revision": actual,
            },
        )


class InvalidTransitionError(FrictionError):
    """Raised for a forbidden lifecycle transition."""

    code = "invalid_transition"

    def __init__(self, current: str, target: str) -> None:
        super().__init__(
            f"Cannot change friction status from {current!r} to {target!r}.",
            details={"current_status": current, "target_status": target},
        )


class StorageError(FrictionError):
    """Raised when persistence cannot complete an operation."""

    code = "storage_error"


class DuplicateItemError(FrictionError):
    """Raised when an item UUID already exists."""

    code = "duplicate_item"


class ImportFailureError(FrictionError):
    """Raised when an import cannot be validated or persisted."""

    code = "import_error"
