"""
管理コンソールの static frontend (Next.js export) を配信する aiohttp ルータ。

仕様: docs/superpowers/specs/2026-05-29-frontend-bot-console.md (§5)
"ビルド成果物は静的ファイルにし、aiohttp サーバの app.router.add_static('/') で配信する"
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable

from aiohttp import web

logger = logging.getLogger(__name__)

# Next.js export 出力ディレクトリ。Dockerfile が runtime stage に配置する。
DEFAULT_STATIC_DIR = "/app/frontend_out"

# SPA fallback の対象 prefix。これらに該当する GET でファイルが見つからなければ
# Next.js が生成した HTML を返す (client-side で React がレンダリングする)。
SPA_PREFIXES = ("/login", "/meetings", "/meeting", "/bots", "/")
# backend が直接ハンドリングするパス (これらは fallback しない)
API_PREFIXES = ("/api/",)


def register_static_router(app: web.Application, *, static_dir: str | None = None) -> bool:
    """static_dir が存在すれば static 配信 + SPA fallback を登録する。
    存在しなければ何もしない (backend のみ動かす運用)。
    """
    path = Path(static_dir or os.environ.get("FRONTEND_STATIC_DIR") or DEFAULT_STATIC_DIR)
    if not path.is_dir():
        logger.info(
            "frontend static directory が無いので static 配信を無効化 (path=%s)", path
        )
        return False

    if not (path / "index.html").exists():
        logger.warning(
            "frontend static directory はあるが index.html が無い (path=%s)", path
        )
        return False

    # 1. Next.js が生成する static asset (_next/*) を配信
    next_dir = path / "_next"
    if next_dir.is_dir():
        app.router.add_static("/_next/", str(next_dir))

    # 2. SPA fallback handler。
    #    /login や /meetings/ などのトップ階層に対して、対応する HTML を返す。
    #    Next.js は trailingSlash: true で `<page>/index.html` を生成するので、
    #    存在チェック → なければ root の index.html (404 ルートも client-side で扱う)。
    async def serve(request: web.Request) -> web.StreamResponse:
        rel = request.path.lstrip("/")
        # 既に存在するファイルなら direct return
        candidates: Iterable[Path] = (
            path / rel,
            path / rel / "index.html",
            path / f"{rel.rstrip('/')}.html",
        )
        for c in candidates:
            try:
                if c.is_file():
                    return web.FileResponse(c)
            except OSError:
                continue
        # SPA fallback: 既知の prefix なら index.html
        if any(request.path.startswith(p) for p in SPA_PREFIXES) and not any(
            request.path.startswith(p) for p in API_PREFIXES
        ):
            return web.FileResponse(path / "index.html")
        raise web.HTTPNotFound()

    # 全 GET を serve に向ける (api route は先に add_post/add_get されているので競合しない)
    app.router.add_get("/", serve)
    # frontend のトップレベルパスのみ catch-all で登録する。
    # `/{tail:.*}` を最後に登録すると aiohttp は順序に従い、より具体的な既存ルートを優先する。
    app.router.add_get("/{tail:.*}", serve)

    logger.info("frontend static 配信を有効化 (path=%s)", path)
    return True
