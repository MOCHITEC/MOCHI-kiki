# src/plugins/clarification_summary.py
import semantic_kernel as sk
from semantic_kernel.functions import KernelArguments


SUMMARY_PROMPT = """
会議で曖昧だった発言が明確になりました。以下の情報をもとに、
会議参加者全員に向けて 100 文字以内で状況を整理してください。

発言者: {{$speaker_name}}
元の発言: {{$original_text}}
確認した質問: {{$question}}
発言者の回答: {{$reply}}

整理文は「発言者名 + の発言 + 明確化した内容」の形式で書いてください。
例: 「田中さんの「あれ」は認証フローのレビュー（PR #42）を指していました。」
"""


class ClarificationSummaryPlugin:
    def __init__(self, kernel: sk.Kernel) -> None:
        self._kernel = kernel
        self._function = kernel.add_function(
            plugin_name="ClarificationSummary",
            function_name="summarize",
            prompt=SUMMARY_PROMPT,
        )

    async def summarize(
        self,
        speaker_name: str,
        original_text: str,
        clarification_question: str,
        reply: str,
    ) -> str:
        result = await self._kernel.invoke(
            self._function,
            KernelArguments(
                speaker_name=speaker_name,
                original_text=original_text,
                question=clarification_question,
                reply=reply,
            ),
        )
        text = str(result).strip()
        return text[:200] if len(text) > 200 else text
