from datetime import datetime, timezone
from src.models import Utterance, Meeting

def test_utterance_creation():
    u = Utterance(
        utterance_id="utt-001",
        meeting_id="meet-001",
        speaker_id="user-111",
        speaker_name="田中 太郎",
        text="この機能の仕様はどうなっていますか？",
        timestamp=datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc),
    )
    assert u.utterance_id == "utt-001"
    assert u.language == "ja-JP"
    assert u.processed is False

def test_utterance_to_dict():
    u = Utterance(
        utterance_id="utt-002",
        meeting_id="meet-001",
        speaker_id="user-111",
        speaker_name="田中 太郎",
        text="テスト発言",
        timestamp=datetime(2026, 5, 12, 10, 1, 0, tzinfo=timezone.utc),
    )
    d = u.to_dict()
    assert d["id"] == "utt-002"
    assert d["meeting_id"] == "meet-001"
    assert d["text"] == "テスト発言"
    assert "timestamp" in d

def test_meeting_creation():
    m = Meeting(
        meeting_id="meet-001",
        thread_id="19:thread@thread.v2",
        organizer_id="user-000",
        started_at=datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc),
    )
    assert m.meeting_id == "meet-001"
    assert m.ended_at is None
    assert m.transcript_subscription_id is None
