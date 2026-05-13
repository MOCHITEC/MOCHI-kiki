# src/plugins/intent_analysis.py
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import List

import semantic_kernel as sk
from semantic_kernel.functions import KernelArguments


class IntentLabel(str, Enum):
    SPEC_INQUIRY = "spec_inquiry"   # 仕様確認・用語不明
    AMBIGUOUS = "ambiguous"         # 曖昧発言（C-03 で処理）
    NORMAL = "normal"               # 通常会話（スキップ）


@dataclass
class IntentResult:
    intent: IntentLabel
    confidence: float
    keywords: List[str] = field(default_factory=list)


INTENT_PROMPT = """
あなたは会議の発話を分析する AI です。
以下の発話を分析し、JSON 形式で意図を返してください。

発話: {{$utterance}}

意図の分類:
- spec_inquiry: 仕様確認、用語の意味確認、ドキュメント参照が必要な発言
  例: 「〇〇の仕様はどうなっていますか？」「〇〇とはどういう意味ですか？」
- ambiguous: 主語や目的語が不明確で解釈が複数できる発言
  例: 「あれをやっておいて」「その辺はいい感じで」
- normal: 上記以外の通常会話

JSON のみを返す（説明不要）:
{
  "intent": "spec_inquiry" | "ambiguous" | "normal",
  "confidence": 0.0-1.0,
  "keywords": ["キーワード1", "キーワード2"]
}
"""


class IntentAnalysisPlugin:
    def __init__(self, kernel: sk.Kernel) -> None:
        self._kernel = kernel
        self._function = kernel.add_function(
            plugin_name="IntentAnalysis",
            function_name="analyze",
            prompt=INTENT_PROMPT,
        )

    async def analyze(self, utterance: str) -> IntentResult:
        result = await self._kernel.invoke(
            self._function,
            KernelArguments(utterance=utterance),
        )
        try:
            raw = json.loads(str(result))
            return IntentResult(
                intent=IntentLabel(raw.get("intent", "normal")),
                confidence=float(raw.get("confidence", 0.0)),
                keywords=raw.get("keywords", []),
            )
        except (json.JSONDecodeError, ValueError):
            return IntentResult(intent=IntentLabel.NORMAL, confidence=0.0)
