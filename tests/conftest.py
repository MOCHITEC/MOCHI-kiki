# tests/conftest.py
import pytest

@pytest.fixture
def meeting_id() -> str:
    return "meeting-test-001"

@pytest.fixture
def speaker_id() -> str:
    return "user-aaa-111"

@pytest.fixture
def speaker_name() -> str:
    return "田中 太郎"
