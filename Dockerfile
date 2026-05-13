# Dockerfile
FROM python:3.11-slim AS builder
WORKDIR /app
RUN pip install --upgrade pip
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

FROM python:3.11-slim AS runtime
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ ./src/
ENV PYTHONPATH=/app
CMD ["python", "-m", "src.main"]
