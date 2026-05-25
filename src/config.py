# src/config.py
import os
import re
from typing import Optional

# Recall.ai が公式に公開しているリージョン
_ALLOWED_RECALL_REGIONS = {"us-east-1", "us-west-2", "eu-central-1", "ap-northeast-1"}

_ALLOWED_TRANSPORTS = {"webhook", "websocket", "both"}
_ALLOWED_AUDIO_SINKS = {"noop", "file", "azure_speech"}


class Config:
    microsoft_app_id: str
    microsoft_app_password: str
    cosmos_endpoint: str
    cosmos_key: str
    cosmos_database: str
    graph_tenant_id: str
    graph_client_id: str
    graph_client_secret: str
    graph_notification_url: str
    port: int
    azure_openai_endpoint: str
    azure_openai_key: str
    azure_openai_deployment: str
    azure_openai_embedding_deployment: str
    azure_search_endpoint: str
    azure_search_key: str
    azure_search_index: str
    recall_webhook_secret: Optional[str]
    recall_api_key: Optional[str]
    recall_region: str
    recall_webhook_public_url: Optional[str]
    transcript_source: str  # "graph" | "recall" | "both"
    recall_transport: str  # "webhook" | "websocket" | "both"
    recall_ws_public_url: Optional[str]
    recall_audio_sink: str

    def __init__(self) -> None:
        self.microsoft_app_id = os.environ["MICROSOFT_APP_ID"]
        self.microsoft_app_password = os.environ["MICROSOFT_APP_PASSWORD"]
        self.cosmos_endpoint = os.environ["AZURE_COSMOS_ENDPOINT"]
        self.cosmos_key = os.environ["AZURE_COSMOS_KEY"]
        self.cosmos_database = os.environ.get("COSMOS_DATABASE", "meeting_db")
        self.graph_tenant_id = os.environ["GRAPH_TENANT_ID"]
        self.graph_client_id = os.environ["GRAPH_CLIENT_ID"]
        self.graph_client_secret = os.environ["GRAPH_CLIENT_SECRET"]
        self.graph_notification_url = os.environ["GRAPH_NOTIFICATION_URL"]
        self.port = int(os.environ.get("PORT", "3978"))
        self.azure_openai_endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
        self.azure_openai_key = os.environ["AZURE_OPENAI_KEY"]
        self.azure_openai_deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
        self.azure_openai_embedding_deployment = os.environ.get(
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small"
        )
        self.azure_search_endpoint = os.environ["AZURE_SEARCH_ENDPOINT"]
        self.azure_search_key = os.environ["AZURE_SEARCH_KEY"]
        self.azure_search_index = os.environ.get("AZURE_SEARCH_INDEX", "documents")

        # 未設定（None）と空文字を同一視する
        secret_raw = os.environ.get("RECALL_WEBHOOK_SECRET", "").strip()
        self.recall_webhook_secret = secret_raw or None

        # Recall bot 投入用
        self.recall_api_key = (os.environ.get("RECALL_API_KEY", "").strip() or None)

        region = os.environ.get("RECALL_REGION", "us-east-1").strip() or "us-east-1"
        if region not in _ALLOWED_RECALL_REGIONS:
            raise RuntimeError(
                f"RECALL_REGION は {sorted(_ALLOWED_RECALL_REGIONS)} のいずれか (got: {region!r})"
            )
        self.recall_region = region

        self.recall_webhook_public_url = (
            os.environ.get("RECALL_WEBHOOK_PUBLIC_URL", "").strip() or None
        )

        # 発話ソース切替
        self.transcript_source = os.environ.get("TRANSCRIPT_SOURCE", "graph").strip().lower()
        if self.transcript_source not in {"graph", "recall", "both"}:
            raise RuntimeError(
                f"TRANSCRIPT_SOURCE は graph/recall/both のいずれかにすること (got: {self.transcript_source!r})"
            )

        # Recall transport: webhook / websocket / both
        transport = os.environ.get("RECALL_TRANSPORT", "webhook").strip().lower() or "webhook"
        if transport not in _ALLOWED_TRANSPORTS:
            raise RuntimeError(
                f"RECALL_TRANSPORT は {sorted(_ALLOWED_TRANSPORTS)} のいずれか (got: {transport!r})"
            )
        self.recall_transport = transport

        self.recall_ws_public_url = (
            os.environ.get("RECALL_WS_PUBLIC_URL", "").strip() or None
        )

        sink = os.environ.get("RECALL_AUDIO_SINK", "noop").strip().lower() or "noop"
        if sink not in _ALLOWED_AUDIO_SINKS:
            raise RuntimeError(
                f"RECALL_AUDIO_SINK は {sorted(_ALLOWED_AUDIO_SINKS)} のいずれか (got: {sink!r})"
            )
        self.recall_audio_sink = sink

        # recall を使うなら必要 env が揃っているか fail-fast
        if self.transcript_source in {"recall", "both"}:
            missing = []
            if not self.recall_api_key:
                missing.append("RECALL_API_KEY")
            # transport に応じて必須 URL が変わる
            if self.recall_transport in ("webhook", "both") and not self.recall_webhook_public_url:
                missing.append("RECALL_WEBHOOK_PUBLIC_URL")
            if self.recall_transport in ("websocket", "both") and not self.recall_ws_public_url:
                missing.append("RECALL_WS_PUBLIC_URL")
            if missing:
                raise RuntimeError(
                    f"TRANSCRIPT_SOURCE={self.transcript_source} / RECALL_TRANSPORT={self.recall_transport} "
                    f"には次の env が必要: {', '.join(missing)}"
                )
            if self.recall_webhook_public_url and not self.recall_webhook_public_url.startswith("https://"):
                raise RuntimeError("RECALL_WEBHOOK_PUBLIC_URL は HTTPS でなければならない")
            if self.recall_ws_public_url and not self.recall_ws_public_url.startswith("wss://"):
                raise RuntimeError("RECALL_WS_PUBLIC_URL は wss:// でなければならない")
