# scripts/test_c02_interactive.py
"""
C02 pipeline interactive CLI test.
Enter text to run: intent analysis -> RAG search -> answer generation.
No Teams posting (dry_run mode).

Run:
    python -m scripts.test_c02_interactive
"""
import asyncio
import logging
import os
import sys
from unittest.mock import AsyncMock, MagicMock

from dotenv import load_dotenv
load_dotenv()  # reads .env from current directory

from src.kernel.orchestrator import Orchestrator
from src.models import Utterance

logging.basicConfig(level=logging.WARNING)
logging.getLogger("src.plugins.intent_analysis").setLevel(logging.DEBUG)


INTENT_LABELS = {
    "spec_inquiry": "SPEC_INQUIRY  (spec question -> RAG search)",
    "ambiguous":    "AMBIGUOUS     (vague utterance -> clarification)",
    "normal":       "NORMAL        (regular chat -> skip)",
}

DIVIDER = "-" * 60


def _print_result(result: dict) -> None:
    print()
    print(DIVIDER)

    intent_val = result.get("intent", "normal")
    label = INTENT_LABELS.get(intent_val, intent_val)
    confidence = result.get("confidence", 0.0)
    keywords = result.get("keywords", [])

    print(f"[1] Intent Analysis")
    print(f"    intent     : {label}")
    print(f"    confidence : {confidence:.2f}")
    print(f"    keywords   : {keywords if keywords else '(none)'}")

    if intent_val == "spec_inquiry":
        search_results = result.get("search_results", [])
        print(f"\n[2] RAG Search  (hits: {len(search_results)})")
        if search_results:
            for r in search_results:
                preview = r["content"][:60].replace("\n", " ")
                print(f"    [{r['score']:.2f}] {r['title']} -- {preview}...")
        else:
            print("    No results (answer generation skipped)")

        answer = result.get("answer")
        posted = result.get("posted_text")
        if answer:
            print(f"\n[3] Answer Generation")
            print(f"    -> {answer}")
            print(f"\n[4] Teams Post (dry_run -- not actually sent)")
            print(f"    {posted}")
        else:
            print(f"\n[3] Answer Generation -> skipped (no search results)")

    elif intent_val == "ambiguous":
        question = result.get("ambiguity_question")
        print(f"\n[2] Ambiguity detected -> clarification question")
        if question:
            print(f"    -> {question}")
        else:
            print("    (not judged as ambiguous)")

    else:
        print("\n    No action taken")

    print(DIVIDER)
    print()


async def run() -> None:
    print("=" * 60)
    print("  C02 Text Input Test  (dry_run mode)")
    print("  Type 'quit' or Ctrl-C to exit")
    print("=" * 60)
    print()

    def _require(name: str) -> str:
        val = os.environ.get(name)
        if not val:
            print(f"[ERROR] Environment variable {name} is not set.")
            sys.exit(1)
        return val

    mock_adapter = MagicMock()
    mock_adapter.continue_conversation = AsyncMock()

    orchestrator = Orchestrator(
        azure_openai_endpoint=_require("AZURE_OPENAI_ENDPOINT"),
        azure_openai_key=_require("AZURE_OPENAI_KEY"),
        chat_deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
        embedding_deployment=os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small"),
        search_endpoint=_require("AZURE_SEARCH_ENDPOINT"),
        search_key=_require("AZURE_SEARCH_KEY"),
        search_index=os.environ.get("AZURE_SEARCH_INDEX", "documents"),
        adapter=mock_adapter,
        app_id="",
    )

    print("Orchestrator ready. Enter an utterance below.")
    print()

    while True:
        try:
            text = input("utterance > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not text:
            continue
        if text.lower() in ("quit", "exit", "q"):
            print("Exiting.")
            break

        utterance = Utterance.new(
            meeting_id="dry-run-meeting",
            speaker_id="test-user",
            speaker_name="Test User",
            text=text,
        )

        try:
            result = await orchestrator.process_dry_run(utterance)
            _print_result(result)
        except Exception as exc:
            print(f"\n[ERROR] {exc}\n")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
