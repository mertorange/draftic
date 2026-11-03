FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
RUN useradd --system --no-create-home draftic
USER draftic

EXPOSE 8010
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/health', timeout=4)"

# One worker only: drafts, rooms and rate limits live in this process's memory.
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "1", \
     "--proxy-headers", "--ws-max-size", "65536", "--limit-concurrency", "500", "--timeout-keep-alive", "15"]
