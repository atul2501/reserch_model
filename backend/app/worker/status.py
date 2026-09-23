"""Builds the runtime snapshot the worker publishes each loop (Ollama key
health, WebSocket state, last council, metrics) for the API/dashboard."""
from __future__ import annotations

from app.core import metrics


def build_worker_payload(ollama_client, ws, engine, outcomes) -> dict:
    ws_state = None
    if ws is not None:
        st = ws.stats
        ws_state = {
            "connected": st.connected, "stale": ws.is_stale, "connects": st.connects, "reconnects": st.reconnects,
            "messages": st.messages, "candles_delivered": st.candles_delivered, "duplicates": st.duplicates,
            "invalid": st.invalid, "out_of_order": st.out_of_order, "stale_reconnects": st.stale_reconnects,
            "last_error": st.last_error, "newest_open_time": st.newest_open_time,
        }
    last_council = None
    for o in reversed(outcomes or []):
        if o.council_status != "NOT_RUN":
            last_council = {"status": o.council_status, "candle_open_time": o.candle_open_time}
            break
    return {
        "execution_venue": engine.venue.value if engine is not None else None,
        "ollama_keys": ollama_client.key_health_snapshot() if ollama_client is not None else None,
        "websocket": ws_state,
        "last_council": last_council,
        "metrics_text": metrics.render_prometheus(),
    }
