"""Clock used by the research planner.

``APP_TODAY`` pins the rolling one-year window so the sample corpus stays
demonstrable and tests stay deterministic. The value is read from settings,
which picks it up from the environment or from ``.env``.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.config import get_settings


def app_today() -> date:
    raw = get_settings().app_today.strip()
    if raw:
        return date.fromisoformat(raw)
    return date.today()


def rolling_year_start(today: date | None = None) -> str:
    current = today or app_today()
    return (current - timedelta(days=365)).isoformat()
