from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional
import uuid


@dataclass
class Utterance:
    utterance_id: str
    meeting_id: str
    speaker_id: str
    speaker_name: str
    text: str
    timestamp: datetime
    language: str = "ja-JP"
    processed: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.utterance_id,
            "meeting_id": self.meeting_id,
            "speaker_id": self.speaker_id,
            "speaker_name": self.speaker_name,
            "text": self.text,
            "timestamp": self.timestamp.isoformat(),
            "language": self.language,
            "processed": self.processed,
        }

    @classmethod
    def new(cls, meeting_id: str, speaker_id: str, speaker_name: str, text: str) -> "Utterance":
        return cls(
            utterance_id=str(uuid.uuid4()),
            meeting_id=meeting_id,
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            text=text,
            timestamp=datetime.now(tz=timezone.utc),
        )


@dataclass
class Meeting:
    meeting_id: str
    thread_id: str
    organizer_id: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    transcript_subscription_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.meeting_id,
            "thread_id": self.thread_id,
            "organizer_id": self.organizer_id,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "transcript_subscription_id": self.transcript_subscription_id,
        }
