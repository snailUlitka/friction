"""Friction workflow-tracking package."""

from importlib.metadata import PackageNotFoundError, version

from friction.application import FrictionService, ItemQuery, ItemRepository
from friction.domain import CreateItem, FrictionItem, ItemPatch, ItemSource, ItemStatus
from friction.storage import create_service

__all__ = [
    "CreateItem",
    "FrictionItem",
    "FrictionService",
    "ItemPatch",
    "ItemQuery",
    "ItemRepository",
    "ItemSource",
    "ItemStatus",
    "__version__",
    "create_service",
]

try:
    __version__ = version("friction")
except PackageNotFoundError:  # pragma: no cover - source-only fallback
    __version__ = "0.0.0+unknown"
