# Runs the trading-cycle background worker (scripts/run_cycle.py), kept as
# a separate process/image from the API server (see app/main.py docstring)
# so a dashboard restart or deploy never interrupts a live trading loop.
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

CMD ["python", "-m", "scripts.run_cycle"]
