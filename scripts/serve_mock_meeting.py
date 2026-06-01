"""
モックデータ入りの「会議ビュー」をローカル URL でサーブするスクリプト。

ハッカソン提出デモ動画 (Demo B) のスクショ素材用。
実 MOCHI-kiki バックエンドや Cosmos には触らず、aiohttp を立ち上げて
articles/mochi-kiki-teams-agent/video/mock-views.html を /meeting?id=... で配信する。

使い方:

    python scripts/serve_mock_meeting.py

起動後、以下を Chrome 等で開いてフル画面スクショ:

    http://127.0.0.1:3979/meeting?id=mock-001

会議内容: 仕様詰めミーティング 2026-06-02 14:00-14:30 (Ueda / Nakagawa)。
3 ビュー (議事録 / タイムライン / 文字起こし) が横並びで表示される。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiohttp import web

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 3979  # backend (3978) と被らないように 3979
MOCK_MEETING_ID = "mock-001"
HTML_PATH = (
    Path(__file__).resolve().parent.parent
    / "articles/mochi-kiki-teams-agent/video/mock-views.html"
)


async def handle_meeting(request: web.Request) -> web.Response:
    meeting_id = request.query.get("id", "")
    if meeting_id != MOCK_MEETING_ID:
        return web.Response(
            status=404,
            text=(
                f"meeting_id='{meeting_id}' は登録されていません。\n"
                f"  → http://{HOST}:{PORT}/meeting?id={MOCK_MEETING_ID} を開いてください。"
            ),
            content_type="text/plain",
        )
    if not HTML_PATH.exists():
        return web.Response(
            status=500,
            text=f"mock-views.html が見つかりません: {HTML_PATH}",
            content_type="text/plain",
        )
    html = HTML_PATH.read_text(encoding="utf-8")
    return web.Response(text=html, content_type="text/html", charset="utf-8")


async def handle_root(request: web.Request) -> web.Response:
    return web.Response(
        text=(
            f"MOCHI-kiki mock meeting view server\n"
            f"\n"
            f"  → http://{HOST}:{PORT}/meeting?id={MOCK_MEETING_ID}\n"
        ),
        content_type="text/plain",
    )


async def main() -> None:
    if not HTML_PATH.exists():
        logger.error("mock-views.html が見つかりません: %s", HTML_PATH)
        raise SystemExit(1)

    app = web.Application()
    app.router.add_get("/", handle_root)
    app.router.add_get("/meeting", handle_meeting)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HOST, PORT)
    await site.start()

    url = f"http://{HOST}:{PORT}/meeting?id={MOCK_MEETING_ID}"
    print("\n" + "=" * 68)
    print(f"  MOCHI-kiki mock meeting view が起動しました")
    print(f"  → {url}")
    print(f"")
    print(f"  Chrome 等で上記 URL を開き、フル画面で 1 枚スクショを取ってください")
    print(f"  停止: Ctrl+C")
    print("=" * 68 + "\n")

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n停止しました。")
