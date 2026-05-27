"""Verify main.py constructs WhisperAudioSink and suppresses native transcript
when RECALL_AUDIO_SINK=azure_openai_whisper."""
import asyncio
import importlib
from unittest.mock import AsyncMock, MagicMock, patch, call


def _base_env(monkeypatch) -> None:
    """Set the minimal env vars that Config.__init__ requires."""
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://fake.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_KEY", "fake-key")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    monkeypatch.setenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
    monkeypatch.setenv("MICROSOFT_APP_ID", "fake-app-id")
    monkeypatch.setenv("MICROSOFT_APP_PASSWORD", "fake-app-pw")
    monkeypatch.setenv("AZURE_COSMOS_ENDPOINT", "https://fake.cosmos.azure.com/")
    monkeypatch.setenv("AZURE_COSMOS_KEY", "fake-cosmos-key")
    monkeypatch.setenv("GRAPH_TENANT_ID", "fake-tenant")
    monkeypatch.setenv("GRAPH_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("GRAPH_CLIENT_SECRET", "fake-secret")
    monkeypatch.setenv("GRAPH_NOTIFICATION_URL", "https://fake.ngrok.io/api/graph/notifications")
    monkeypatch.setenv("AZURE_SEARCH_ENDPOINT", "https://fake.search.azure.com/")
    monkeypatch.setenv("AZURE_SEARCH_KEY", "fake-search-key")
    monkeypatch.setenv("TRANSCRIPT_SOURCE", "graph")
    monkeypatch.setenv("RECALL_TRANSPORT", "websocket")


def _run_main_once(monkeypatch) -> dict:
    """
    Run src.main.main() exactly until the infinite wait, then cancel.
    Returns a dict of mock objects keyed by name.
    """
    import src.main as main_mod
    importlib.reload(main_mod)

    mocks: dict = {}

    # Setup mock instances
    mock_sink_instance = MagicMock()
    mock_sink_instance.set_on_utterance = MagicMock()
    mocks["sink_instance"] = mock_sink_instance

    mock_handler_instance = MagicMock()
    mock_handler_instance.set_on_utterance = MagicMock()
    mocks["handler_instance"] = mock_handler_instance

    mock_cosmos_instance = AsyncMock()
    mock_cosmos_instance.initialize = AsyncMock()
    mock_cosmos_instance.close = AsyncMock()
    mocks["cosmos_instance"] = mock_cosmos_instance

    mock_webhook_handler_instance = MagicMock()
    mock_webhook_handler_instance.set_on_utterance = MagicMock()
    mocks["webhook_handler_instance"] = mock_webhook_handler_instance

    mock_app = MagicMock()
    # Make runner behave like an async context
    mock_runner = MagicMock()
    mock_runner.setup = AsyncMock()
    mock_runner.cleanup = AsyncMock()
    mock_site = MagicMock()
    mock_site.start = AsyncMock()
    mock_adapter = MagicMock()
    mocks["runner"] = mock_runner
    mocks["site"] = mock_site

    mock_orchestrator_instance = MagicMock()
    mock_orchestrator_instance.set_cosmos = MagicMock()
    mock_orchestrator_instance.process = AsyncMock()
    mocks["orchestrator_instance"] = mock_orchestrator_instance

    mock_async_client_instance = MagicMock()
    mocks["async_client_instance"] = mock_async_client_instance

    MockSink = MagicMock(return_value=mock_sink_instance)
    MockHandler = MagicMock(return_value=mock_handler_instance)
    MockAsyncClient = MagicMock(return_value=mock_async_client_instance)
    MockCosmos = MagicMock(return_value=mock_cosmos_instance)
    MockWebhookHandler = MagicMock(return_value=mock_webhook_handler_instance)
    MockMeetingBot = MagicMock()
    MockMeetingBot.return_value._on_utterance = None
    MockMeetingBot.return_value._orchestrator = None
    MockOrchestrator = MagicMock(return_value=mock_orchestrator_instance)
    MockRecallRouter = MagicMock()
    MockBuildSink = MagicMock(return_value=None)

    mocks["MockSink"] = MockSink
    mocks["MockHandler"] = MockHandler
    mocks["MockAsyncClient"] = MockAsyncClient
    mocks["MockBuildSink"] = MockBuildSink

    with patch.object(main_mod, "CosmosClient", MockCosmos), \
         patch.object(main_mod, "RecallWebhookHandler", MockWebhookHandler), \
         patch.object(main_mod, "RecallWsHandler", MockHandler), \
         patch.object(main_mod, "MeetingBot", MockMeetingBot), \
         patch.object(main_mod, "Orchestrator", MockOrchestrator), \
         patch.object(main_mod, "RecallWebhookRouter", MockRecallRouter), \
         patch.object(main_mod, "AsyncAzureOpenAI", MockAsyncClient), \
         patch.object(main_mod, "build_audio_sink", MockBuildSink), \
         patch("src.transcript.audio_sink.WhisperAudioSink", MockSink), \
         patch.object(main_mod, "create_app_with_adapter", return_value=(mock_app, mock_adapter)), \
         patch("aiohttp.web.AppRunner", return_value=mock_runner), \
         patch("aiohttp.web.TCPSite", return_value=mock_site):

        async def _run():
            task = asyncio.create_task(main_mod.main())
            # Give coroutine enough time to reach the infinite wait
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        asyncio.run(_run())

    return mocks


def test_whisper_sink_constructed_when_env_set(monkeypatch):
    """When RECALL_AUDIO_SINK=azure_openai_whisper, WhisperAudioSink is built and
    RecallWsHandler receives suppress_native_transcript=True."""
    _base_env(monkeypatch)
    monkeypatch.setenv("RECALL_AUDIO_SINK", "azure_openai_whisper")
    monkeypatch.setenv("RECALL_WHISPER_DEPLOYMENT", "whisper")

    mocks = _run_main_once(monkeypatch)

    MockSink = mocks["MockSink"]
    MockHandler = mocks["MockHandler"]
    mock_async_client_instance = mocks["async_client_instance"]

    # WhisperAudioSink should have been constructed
    MockSink.assert_called_once()
    init_kwargs = MockSink.call_args.kwargs
    assert init_kwargs.get("openai_client") is mock_async_client_instance
    assert init_kwargs.get("whisper_deployment") == "whisper"
    call_kwargs = MockSink.call_args.kwargs
    assert call_kwargs["silence_rms_threshold"] == 300
    assert call_kwargs["silence_duration_ms"] == 600
    assert call_kwargs["min_segment_secs"] == 1.0
    assert call_kwargs["max_segment_secs"] == 30.0

    # RecallWsHandler should have been called with suppress_native_transcript=True
    MockHandler.assert_called_once()
    handler_kwargs = MockHandler.call_args.kwargs
    assert handler_kwargs.get("suppress_native_transcript") is True

    # set_on_utterance should have been called on the sink
    mocks["sink_instance"].set_on_utterance.assert_called_once()


def test_default_sink_no_suppress(monkeypatch):
    """When RECALL_AUDIO_SINK is noop, WhisperAudioSink is NOT built and
    suppress_native_transcript=False."""
    _base_env(monkeypatch)
    monkeypatch.setenv("RECALL_AUDIO_SINK", "noop")

    mocks = _run_main_once(monkeypatch)

    MockSink = mocks["MockSink"]
    MockHandler = mocks["MockHandler"]
    MockBuildSink = mocks["MockBuildSink"]

    # WhisperAudioSink should NOT have been constructed
    MockSink.assert_not_called()

    # build_audio_sink should have been called for the noop path
    MockBuildSink.assert_called_once()

    # RecallWsHandler should have been called with suppress_native_transcript=False
    MockHandler.assert_called_once()
    handler_kwargs = MockHandler.call_args.kwargs
    assert handler_kwargs.get("suppress_native_transcript") is False
