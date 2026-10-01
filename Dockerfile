FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown -R app /data /app
USER app
ENV ENV=production DB_PATH=/data/jobs.db
# TRUST_PROXY=1 only when a proxy you control sits in front and appends the client address (Render does; see render.yaml).
# Left on with nothing in front, anyone could fake their address and skip the rate limits.
EXPOSE 8000
CMD ["sh", "-c", "python -m uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
