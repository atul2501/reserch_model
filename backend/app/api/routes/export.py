"""One-click report export: everything the dashboard shows, as one .xlsx.

Reuses the dashboard's own route functions (called directly, so `limit=None`
lifts their page caps) - the workbook always matches what the API serves.
Each section is fetched independently: one failing (e.g. no market data yet)
writes a note on its sheet instead of failing the whole export.
"""
from __future__ import annotations

import asyncio
import io
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import council, evolution
from app.api.routes.champion_challenger import list_champions
from app.api.routes.correlation import get_convergence_history
from app.api.routes.leaderboard import get_leaderboard
from app.api.routes.market import get_market_history, get_market_snapshot
from app.api.routes.population import get_population_summary
from app.api.routes.positions import list_open_positions
from app.api.routes.shadow import shadow_summary
from app.api.routes.trades import get_regime_performance, get_side_performance, get_strategy_performance, list_trades
from app.core.database import get_db
from app.core.runtime_status import compute_system_status

router = APIRouter(prefix="/api/export", tags=["export"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EXCEL_MAX_ROWS = 1_048_575          # data rows per sheet, after the header
EXCEL_MAX_CELL_CHARS = 32_767
MARKET_CANDLES = 1_440              # last 24h of 1m candles - full history is raw data, not a report
HEADER_FONT = Font(bold=True)


def _plain(v: Any) -> Any:
    if isinstance(v, BaseModel):
        return v.model_dump(mode="json")
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


def _flatten(d: dict, prefix: str = "") -> dict:
    """Nested dicts become dotted columns; lists become JSON text."""
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out


def _cell_value(v: Any) -> Any:
    if isinstance(v, Enum):
        v = v.value
    if isinstance(v, (list, dict)):
        v = json.dumps(v, default=str)
    if v is None or isinstance(v, (bool, int, float)):
        return v
    s = ILLEGAL_CHARACTERS_RE.sub("", str(v))[:EXCEL_MAX_CELL_CHARS]
    # openpyxl stores any string starting with "=" as a formula; API text
    # (agent ids, LLM reasoning) is untrusted, so never let it execute.
    return "'" + s if s.startswith("=") else s


class _Sheet:
    def __init__(self, wb: Workbook, title: str):
        self.ws = wb.create_sheet(title)

    def _widths(self, rows: list[list[Any]]) -> None:
        for i in range(max((len(r) for r in rows), default=0)):
            longest = max((len(str(r[i])) for r in rows[:200] if i < len(r) and r[i] is not None), default=8)
            self.ws.column_dimensions[get_column_letter(i + 1)].width = min(60, max(10, longest + 2))

    def _header(self, names: list[str]) -> list[WriteOnlyCell]:
        cells = []
        for n in names:
            c = WriteOnlyCell(self.ws, value=n)
            c.font = HEADER_FONT
            cells.append(c)
        return cells

    def note(self, text: str) -> None:
        self.ws.append([text])

    def table(self, rows: list[dict]) -> None:
        if not rows:
            self.note("No data yet")
            return
        rows = [_flatten(r) for r in rows]
        columns = list(dict.fromkeys(k for r in rows for k in r))
        body = [[_cell_value(r.get(c)) for c in columns] for r in rows[:EXCEL_MAX_ROWS - 1]]
        self._widths([columns] + body)
        self.ws.freeze_panes = "A2"
        self.ws.append(self._header(columns))
        for line in body:
            self.ws.append(line)
        if len(rows) > len(body):
            self.ws.append([f"Truncated: {len(rows) - len(body)} more rows exceed Excel's sheet limit"])

    def key_values(self, sections: list[tuple[str, dict | str]]) -> None:
        lines = []
        for title, data in sections:
            lines.append((title, None))
            if isinstance(data, str):
                lines.append(("", data))
            else:
                lines.extend((k, _cell_value(v)) for k, v in _flatten(data).items())
            lines.append(None)
        self.ws.column_dimensions["A"].width = 38
        self.ws.column_dimensions["B"].width = 60
        for line in lines:
            if line is None:
                self.ws.append([])
            elif line[1] is None:
                self.ws.append(self._header([line[0]]))
            else:
                self.ws.append(list(line))


async def _fetch(db: AsyncSession, call: Awaitable) -> tuple[Any, str | None]:
    try:
        return _plain(await call), None
    except HTTPException as e:
        return None, f"Not available: {e.detail}"
    except Exception as e:  # one broken section must not sink the whole report
        await db.rollback()
        return None, f"Not available: {type(e).__name__}: {e}"


def _build(generated_at: datetime, data: dict[str, tuple[Any, str | None]]) -> bytes:
    wb = Workbook(write_only=True)

    def section(key: str) -> dict | str:
        value, err = data[key]
        return err or value or {}

    council_latest = section("council_latest")
    council_decision = {k: v for k, v in council_latest.items() if k != "analysts"} if isinstance(council_latest, dict) else council_latest
    _Sheet(wb, "Summary").key_values([
        ("Report", {"generated_at_utc": generated_at.strftime("%Y-%m-%d %H:%M:%S")}),
        ("Population", section("population")),
        ("Market", section("market")),
        ("System status", section("status")),
        ("Latest council decision", council_decision),
        ("Evolution", section("evolution_summary")),
        ("Shadow execution", section("shadow")),
    ])

    leaderboard, lb_err = data["agents"]
    agents = None if lb_err else [
        {"rank": e["rank"], "strategy_family": e["strategy_family"], **e["agent"]} for e in leaderboard
    ]
    analysts, an_err = data["council_latest"]
    candles, c_err = data["market_history"]
    if candles:
        candles = [{"open_time_utc": datetime.fromtimestamp(c["open_time"] / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M"), **c}
                   for c in candles]

    tables = [
        ("By Strategy", data["by_strategy"]),
        ("By Regime", data["by_regime"]),
        ("By Side", data["by_side"]),
        ("Agents", (agents, lb_err)),
        ("Open Positions", data["positions"]),
        ("Trades", data["trades"]),
        ("Champions", data["champions"]),
        ("Generations", data["generations"]),
        ("Evolution Events", data["evolution_events"]),
        ("Experiments", data["experiments"]),
        ("Council Analysts", (analysts.get("analysts") if analysts else None, an_err)),
        ("Council History", data["council_history"]),
        ("Correlation History", data["correlation"]),
        ("Market Candles 24h", (candles, c_err)),
    ]
    for title, (rows, err) in tables:
        sheet = _Sheet(wb, title)
        if err:
            sheet.note(err)
        else:
            sheet.table(rows or [])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@router.get("/report")
async def export_report(db: AsyncSession = Depends(get_db)):
    generated_at = datetime.now(timezone.utc)
    # Sequential on purpose: all sections share one DB session.
    calls = {
        "population": get_population_summary(db),
        "market": get_market_snapshot(db),
        "status": compute_system_status(db),
        "council_latest": council.latest(db),
        "evolution_summary": evolution.summary(db),
        "shadow": shadow_summary(db),
        "by_strategy": get_strategy_performance(db),
        "by_regime": get_regime_performance(db),
        "by_side": get_side_performance(db),
        "agents": get_leaderboard(db, limit=None, include_dead=True),
        "positions": list_open_positions(db, limit=None),
        "trades": list_trades(db, limit=None),
        "champions": list_champions(db),
        "generations": evolution.generations(db, limit=None),
        "evolution_events": evolution.events(db, generation=None, limit=None),
        "experiments": evolution.experiments(db, limit=None),
        "council_history": council.history(db, limit=None),
        "correlation": get_convergence_history(db, limit=None),
        "market_history": get_market_history(db, limit=MARKET_CANDLES),
    }
    data = {}
    for key, call in calls.items():
        data[key] = await _fetch(db, call)

    content = await asyncio.to_thread(_build, generated_at, data)
    filename = f"trading-report-{generated_at.strftime('%Y%m%d-%H%M%S')}.xlsx"
    return Response(content=content, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
