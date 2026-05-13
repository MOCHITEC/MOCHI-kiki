# src/kernel/clarification_session.py
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class SessionStatus(str, Enum):
    PENDING = "pending"         # 確認メッセージを送信済み、返信待ち
    REPLIED = "replied"         # 発言者が返信した
    SUMMARIZED = "summarized"   # 整理文を会議チャットに投稿した
    TIMED_OUT = "timed_out"     # タイムアウト（60 秒以内に返信なし）


@dataclass
class ClarificationSession:
    session_id: str
    meeting_id: str
    utterance_id: str
    speaker_id: str
    speaker_name: str
    original_text: str
    clarification_question: str
    status: SessionStatus
    created_at: datetime
    reply: Optional[str] = None
    summary: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.session_id,
            "meeting_id": self.meeting_id,
            "utterance_id": self.utterance_id,
            "speaker_id": self.speaker_id,
            "speaker_name": self.speaker_name,
            "original_text": self.original_text,
            "clarification_question": self.clarification_question,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "reply": self.reply,
            "summary": self.summary,
        }

    @classmethod
    def new(
        cls,
        meeting_id: str,
        utterance_id: str,
        speaker_id: str,
        speaker_name: str,
        original_text: str,
        clarification_question: str,
    ) -> "ClarificationSession":
        return cls(
            session_id=str(uuid.uuid4()),
            meeting_id=meeting_id,
            utterance_id=utterance_id,
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            original_text=original_text,
            clarification_question=clarification_question,
            status=SessionStatus.PENDING,
            created_at=datetime.now(tz=timezone.utc),
        )
