FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --system --gid 10001 facet && useradd --system --uid 10001 --gid facet --home-dir /app facet \
    && mkdir -p /data && chown facet:facet /data

COPY --chown=facet:facet *.py *.md ./
COPY --chown=facet:facet web ./web
COPY --chown=facet:facet examples ./examples
COPY --chown=facet:facet deploy ./deploy

USER facet
EXPOSE 8765
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3).read()"]

CMD ["python", "web_app.py", "--host", "0.0.0.0", "--port", "8765", "--data", "/data/workspace.sqlite3"]
