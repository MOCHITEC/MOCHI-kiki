#!/usr/bin/env python3
"""会議の文字起こしを Cosmos から取り出して標準出力に表示する。

使い方:
    # 最近の meeting 一覧 (utterance 数つき)
    python3 scripts/show_transcript.py

    # 特定 meeting の transcript を時刻順に表示
    python3 scripts/show_transcript.py <meeting_id>

    # 発話テキストを連結して plain text で出力 (パイプ向け)
    python3 scripts/show_transcript.py <meeting_id> --plain

    # 件数 / 期間を絞る
    python3 scripts/show_transcript.py --limit 10
    python3 scripts/show_transcript.py <meeting_id> --since 2026-05-27

`.env` に AZURE_COSMOS_ENDPOINT / AZURE_COSMOS_KEY が必要 (fetch_azure_env.sh で生成済の想定)。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from azure.cosmos.aio import CosmosClient
except ImportError:
    sys.stderr.write("azure-cosmos が必要: pip install azure-cosmos\n")
    sys.exit(2)


_DEFAULT_DB = "meeting_db"
_UTTERANCES_CONTAINER = "utterances"
_MEETINGS_CONTAINER = "meetings"
_RECENT_LIMIT_DEFAULT = 20


def _load_env() -> dict[str, str]:
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        sys.stderr.write(f"❌ .env が無い: {env_path}\n")
        sys.exit(2)
    env: dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


async def list_meetings(container, limit: int) -> None:
    """
    Cosmos の cross-partition GROUP BY は制約が強いため、最近の発話 1000 件を
    取得してクライアント側で meeting_id ごとに集計する。
    """
    query = (
        "SELECT TOP 1000 c.meeting_id, c.timestamp FROM c ORDER BY c.timestamp DESC"
    )
    by_mid: dict[str, dict] = {}
    async for it in container.query_items(query=query):
        mid = it.get("meeting_id") or ""
        ts = it.get("timestamp") or ""
        if mid not in by_mid:
            by_mid[mid] = {"meeting_id": mid, "count": 0, "last_ts": ts}
        agg = by_mid[mid]
        agg["count"] += 1
        if ts > agg["last_ts"]:
            agg["last_ts"] = ts
    rows = sorted(by_mid.values(), key=lambda r: r["last_ts"], reverse=True)[:limit]
    if not rows:
        print("(発話レコードがありません)")
        return
    print(f"{'meeting_id':40}  {'count':>5}  last_utterance_ts")
    print("-" * 80)
    for r in rows:
        print(f"{r['meeting_id']:40}  {r['count']:>5}  {r['last_ts']}")
    print()
    print("注: 直近 1000 発話を集計対象。古い meeting は表示されない場合があります。")
    print("詳細:  python3 scripts/show_transcript.py <meeting_id>")


async def show_transcript(
    container, meeting_id: str, *, plain: bool, since: str | None
) -> None:
    where = ["c.meeting_id = @mid"]
    params: list[dict] = [{"name": "@mid", "value": meeting_id}]
    if since:
        where.append("c.timestamp >= @since")
        params.append({"name": "@since", "value": since})
    query = (
        "SELECT c.id, c.speaker_name, c.speaker_id, c.text, c.timestamp, c.language "
        f"FROM c WHERE {' AND '.join(where)} ORDER BY c.timestamp ASC"
    )
    rows: list[dict] = []
    async for it in container.query_items(query=query, parameters=params):
        rows.append(it)

    if not rows:
        print(f"(meeting_id={meeting_id} に発話レコードがありません)", file=sys.stderr)
        return

    if plain:
        # テキストのみ連結 (発話間に改行)
        for r in rows:
            print(r.get("text", ""))
        return

    print(f"meeting_id: {meeting_id}")
    print(f"utterances: {len(rows)}")
    print("-" * 80)
    for r in rows:
        ts = r.get("timestamp", "")
        speaker = r.get("speaker_name") or "?"
        text = r.get("text", "")
        print(f"[{ts}] {speaker}:")
        print(f"  {text}")
        print()


async def main_async(args: argparse.Namespace) -> int:
    env = _load_env()
    endpoint = env.get("AZURE_COSMOS_ENDPOINT")
    key = env.get("AZURE_COSMOS_KEY")
    db_name = env.get("COSMOS_DATABASE", _DEFAULT_DB)
    if not (endpoint and key):
        sys.stderr.write("❌ AZURE_COSMOS_ENDPOINT / AZURE_COSMOS_KEY が .env に必要\n")
        return 2

    client = CosmosClient(endpoint, credential=key)
    try:
        db = client.get_database_client(db_name)
        container = db.get_container_client(_UTTERANCES_CONTAINER)

        if args.meeting_id:
            await show_transcript(
                container, args.meeting_id, plain=args.plain, since=args.since
            )
        else:
            await list_meetings(container, args.limit)
    finally:
        await client.close()
    return 0


def main() -> None:
    p = argparse.ArgumentParser(
        description="Cosmos から会議の文字起こしを表示する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("meeting_id", nargs="?", help="表示したい meeting_id (未指定なら一覧)")
    p.add_argument(
        "--plain",
        action="store_true",
        help="発話テキストのみを連結出力 (パイプ向け)",
    )
    p.add_argument(
        "--since",
        default=None,
        help="この ISO8601 以降の発話のみ (例: 2026-05-27)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=_RECENT_LIMIT_DEFAULT,
        help=f"一覧モードでの最大件数 (default: {_RECENT_LIMIT_DEFAULT})",
    )
    args = p.parse_args()

    rc = asyncio.run(main_async(args))
    sys.exit(rc)


if __name__ == "__main__":
    main()
