# src/transcript/transcript_pipeline.py
"""
Recall.ai の transcript.data 公式 envelope を Utterance に変換する純粋ロジック。

Webhook 経路 (RecallWebhookHandler) と WebSocket 経路 (RecallWsHandler) の両方から
呼ばれるため、I/O やネットワーク副作用を持たない。
"""
from __future__ import annotations

from typing import Optional

from src.models import Utterance

_MAX_TEXT_FIELD_LEN = 200
_MAX_WORDS = 500


def extract_utterance_from_transcript_data(
    payload: dict, *, meeting_id: str
) -> Optional[Utterance]:
    """
    Recall.ai の transcript.data envelope (webhook / websocket 共通) から
    確定発話を Utterance に変換する。

    payload 形式:
        {
            "event": "transcript.data",
            "data": {
                "data": {
                    "is_final": true,          # webhook 経路で出現する
                    "words": [{"text": ...}, ...],
                    "participant": {"id": int, "name": str},
                    "language_code": "ja",
                },
                "bot": {"id": ...},
                ...
            }
        }

    is_final の扱い:
        - webhook 経路は data.data.is_final を常に持つ (True/False)
        - realtime WebSocket 経路は **is_final フィールド自体を持たない**。
          event 名 (transcript.data vs transcript.partial_data) で
          final / partial を区別する設計。
        - そのため「明示的に False の時だけ reject」「欠落は確定扱い」とする。

    返り値:
        Utterance (有効な発話の場合)
        None     (is_final=False / 空 / 形式不正)
    """
    data_outer = payload.get("data")
    if not isinstance(data_outer, dict):
        return None
    data = data_outer.get("data")
    if not isinstance(data, dict):
        return None
    # 明示的な False のみ reject。欠落 (None) は確定扱い (WS realtime の挙動と整合)。
    if data.get("is_final") is False:
        return None

    words = data.get("words")
    if not isinstance(words, list):
        return None
    words = words[:_MAX_WORDS]
    text = _join_words(words)
    if not text:
        return None

    participant = data.get("participant") or {}
    if not isinstance(participant, dict):
        participant = {}
    speaker_id = _sanitize_text(participant.get("id"), default="unknown")
    speaker_name = _sanitize_text(participant.get("name"), default="不明")

    return Utterance.new(
        meeting_id=meeting_id,
        speaker_id=speaker_id,
        speaker_name=speaker_name,
        text=text,
    )


def _join_words(words: list) -> str:
    # 日本語が中心。ASCII 空白は挿入しない。
    # Recall の word.text に既に必要な区切りが含まれている前提。
    parts: list[str] = []
    for w in words:
        if not isinstance(w, dict):
            continue
        t = w.get("text")
        if isinstance(t, str):
            parts.append(t)
    return "".join(parts).strip()


def _sanitize_text(value, default: str) -> str:
    if value is None:
        return default
    s = str(value)
    if not s:
        return default
    return s[:_MAX_TEXT_FIELD_LEN]
