# src/transcript/graph_subscription.py
import aiohttp
from datetime import datetime, timedelta, timezone
from typing import Optional

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"


class GraphTranscriptSubscription:
    """Graph API 変更通知でTeams Live Transcription を購読する。"""

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        notification_url: str,
    ) -> None:
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._notification_url = notification_url
        self._access_token: Optional[str] = None
        self._http_client: Optional[aiohttp.ClientSession] = None

    async def _ensure_token(self) -> str:
        """アクセストークンを取得する（既にセットされている場合はスキップ）。"""
        if self._access_token:
            return self._access_token
        url = TOKEN_URL_TEMPLATE.format(tenant_id=self._tenant_id)
        data = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "scope": "https://graph.microsoft.com/.default",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data) as resp:
                body = await resp.json()
                self._access_token = body["access_token"]
        return self._access_token

    async def subscribe(self, meeting_id: str, online_meeting_id: str) -> str:
        """
        Teams Live Transcription の変更通知を購読する。
        Returns: subscription ID
        """
        token = await self._ensure_token()
        expiry = (datetime.now(tz=timezone.utc) + timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        payload = {
            "changeType": "created,updated",
            "notificationUrl": self._notification_url,
            "resource": f"/communications/onlineMeetings/{online_meeting_id}/transcripts",
            "expirationDateTime": expiry,
        }
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        if self._http_client:
            resp = await self._http_client.post(
                f"{GRAPH_BASE}/subscriptions", json=payload, headers=headers
            )
            body = await resp.json()
        else:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{GRAPH_BASE}/subscriptions", json=payload, headers=headers
                ) as resp:
                    body = await resp.json()

        return body["id"]

    async def unsubscribe(self, subscription_id: str) -> None:
        """購読を解除する。"""
        token = await self._ensure_token()
        headers = {"Authorization": f"Bearer {token}"}
        if self._http_client:
            await self._http_client.delete(
                f"{GRAPH_BASE}/subscriptions/{subscription_id}", headers=headers
            )
        else:
            async with aiohttp.ClientSession() as session:
                async with session.delete(
                    f"{GRAPH_BASE}/subscriptions/{subscription_id}", headers=headers
                ):
                    pass
