from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from friction.domain import CreateItem, InvalidTransitionError, ItemStatus
from friction.domain.statuses import validate_transition


def test_create_item_normalizes_note_tags_and_time() -> None:
    item = CreateItem(
        note="  multiline\nnote  ",
        tags=("Editor", "editor", " cli "),
        created_at=datetime(2026, 7, 16, 12, tzinfo=UTC),
    ).to_item()

    assert item.note == "multiline\nnote"
    assert item.tags == ("cli", "Editor")
    assert item.status is ItemStatus.OPEN
    assert item.revision == 1
    assert item.created_at == item.updated_at


def test_create_item_rejects_blank_note_and_naive_time() -> None:
    with pytest.raises(ValidationError):
        CreateItem(note="  ")

    with pytest.raises(ValidationError):
        CreateItem(note="valid", created_at=datetime(2026, 7, 16))


def test_status_transition_rules() -> None:
    assert validate_transition(ItemStatus.OPEN, ItemStatus.DONE)
    assert validate_transition(ItemStatus.DONE, ItemStatus.OPEN)
    assert not validate_transition(ItemStatus.OPEN, ItemStatus.OPEN)

    with pytest.raises(InvalidTransitionError):
        validate_transition(ItemStatus.DONE, ItemStatus.DISMISSED)
