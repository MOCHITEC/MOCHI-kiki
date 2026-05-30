# Dockerfile - backend (Python aiohttp) + frontend (Next.js static export) 同梱

# ── 1. frontend を Next.js static export でビルド ─────────────────────────────
FROM node:20-slim AS frontend_builder
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# dev mock の Route Handler は static export と非互換 (cookies()/dynamic 操作のため)。
# 本番では backend の /api/console/* が応答するので不要。
RUN rm -rf src/app/api
ENV NEXT_BUILD_MODE=export
RUN npm run build
# 成果物は /frontend/out/

# ── 2. Python 依存をインストール ──────────────────────────────────────────────
FROM python:3.11-slim AS builder
WORKDIR /app
RUN pip install --upgrade pip
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# ── 3. runtime image (backend + frontend out/ を同梱) ─────────────────────────
FROM python:3.11-slim AS runtime
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ ./src/
# Next.js static export を /app/frontend_out/ に配置 (static_router.py が参照)
COPY --from=frontend_builder /frontend/out/ ./frontend_out/
ENV PYTHONPATH=/app
CMD ["python", "-m", "src.main"]
