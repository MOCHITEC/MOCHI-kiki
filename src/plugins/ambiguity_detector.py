# src/plugins/ambiguity_detector.py
import json
from dataclasses import dataclass

import semantic_kernel as sk
from semantic_kernel.functions import KernelArguments


AMBIGUITY_PROMPT = """
あなたは会議の発話を分析する AI です。
以下の発話が曖昧かどうかを判定し、JSON で返してください。

発話: {{$utterance}}

曖昧な発話の例:
- 主語が不明確: 「あれをやっておいて」「それで進めて」
- 目的語が不明確: 「その辺はいい感じで」「適当にやって」
- 代名詞の指示対象が不明: 「これ」「あれ」「そこ」が何を指すか不明

JSON のみを返す（説明不要）:
{
  "is_ambiguous": true | false,
  "reason": "曖昧と判断した理由（30文字以内）",
  "question": "発言者への確認質問（曖昧でない場合は空文字）"
}
"""


@dataclass
class AmbiguityResult:
    is_ambiguous: bool
    reason: str
    question: str


class AmbiguityDetectorPlugin:
    def __init__(self, kernel: sk.Kernel) -> None:
        self._kernel = kernel
        self._function = kernel.add_function(
            plugin_name="AmbiguityDetector",
            function_name="detect",
            prompt=AMBIGUITY_PROMPT,
        )

    async def detect(self, utterance: str) -> AmbiguityResult:
        result = await self._kernel.invoke(
            self._function,
            KernelArguments(utterance=utterance),
        )
        try:
            raw = json.loads(str(result))
            return AmbiguityResult(
                is_ambiguous=bool(raw.get("is_ambiguous", False)),
                reason=raw.get("reason", ""),
                question=raw.get("question", ""),
            )
        except (json.JSONDecodeError, ValueError):
            return AmbiguityResult(is_ambiguous=False, reason="", question="")
