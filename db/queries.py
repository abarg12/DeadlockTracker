"""Dashboard queries: each runs a file from sql/queries/, the same SQL bench/run.py measures."""

import datetime as dt
from decimal import Decimal

import pandas as pd
import streamlit as st

from db.connection import run_query
from ingest.load import query_sql


def _run(name: str, **params) -> pd.DataFrame:
    df = run_query(query_sql(name), params)
    # NUMERIC columns arrive as Decimal; charts need floats
    for column in df.columns:
        if df[column].dtype == object and df[column].map(lambda v: isinstance(v, Decimal)).any():
            df[column] = df[column].astype(float)
    return df


@st.cache_data(ttl="5s")
def ingest_status() -> dict | None:
    """The background ingest's progress row, or None before the schema exists."""
    try:
        return run_query("SELECT * FROM ingest_state").iloc[0].to_dict()
    except Exception:  # schema not built yet
        return None


def data_version() -> int:
    """Increases with every ingest commit; cached queries take it so new data replaces stale results."""
    status = ingest_status()
    return int(status.get("data_version", 0)) if status else -1


def last_ingest_time() -> dt.datetime | None:
    """When the background ingest last finished, or None before its first run."""
    status = ingest_status()
    value = status.get("last_run_at") if status else None
    return None if pd.isna(value) else value.to_pydatetime()


@st.cache_data(ttl="10m", max_entries=4)
def _newest_match_time(version: int) -> dt.datetime | None:
    try:
        newest = run_query("SELECT max(start_time) AS newest FROM match")["newest"].iloc[0]
    except Exception:  # schema not built yet
        return None
    return None if pd.isna(newest) else newest.to_pydatetime()


def newest_match_time() -> dt.datetime | None:
    """Start time of the newest loaded match, or None if no matches are loaded."""
    return _newest_match_time(data_version())


@st.cache_data(ttl="10m", max_entries=4)
def _match_modes(version: int) -> list[str]:
    return run_query("SELECT DISTINCT match_mode FROM match ORDER BY 1")["match_mode"].tolist()


def match_modes() -> list[str]:
    return _match_modes(data_version())


def window_start(days: int) -> dt.datetime | None:
    """UTC midnight starting the last `days` days of loaded data (so the views match exactly)."""
    newest = newest_match_time()
    if newest is None:
        return None
    last_day = newest.astimezone(dt.timezone.utc).date()
    return dt.datetime.combine(last_day - dt.timedelta(days=days - 1), dt.time(), dt.timezone.utc)


@st.cache_data(ttl="10m", max_entries=16)
def _window_bound(since: dt.datetime, version: int) -> int:
    return int(_run("window_bound", since=since)["min_match_id"].iloc[0])


def window_bound(since: dt.datetime) -> int:
    """Smallest match_id in the window, passed to the windowed queries as :min_match_id."""
    return _window_bound(since, data_version())


@st.cache_data(ttl="10m", max_entries=16)
def _daily_summary(since: dt.datetime, version: int) -> pd.DataFrame:
    return _run("daily_summary", since=since, min_match_id=window_bound(since))


def daily_summary(since: dt.datetime) -> pd.DataFrame:
    return _daily_summary(since, data_version())


@st.cache_data(ttl="10m", max_entries=32)
def _hero_win_rates(since: dt.datetime, match_mode: str, version: int) -> pd.DataFrame:
    return _run("hero_win_rates_mv", since=since, match_mode=match_mode)


def hero_win_rates(since: dt.datetime, match_mode: str) -> pd.DataFrame:
    return _hero_win_rates(since, match_mode, data_version())


@st.cache_data(ttl="10m", max_entries=32)
def _item_win_rates(since: dt.datetime, match_mode: str, version: int) -> pd.DataFrame:
    return _run("item_win_rates_mv", since=since, match_mode=match_mode)


def item_win_rates(since: dt.datetime, match_mode: str) -> pd.DataFrame:
    return _item_win_rates(since, match_mode, data_version())


@st.cache_data(ttl="10m", max_entries=64)
def _player_match_history(account_id: int, version: int) -> pd.DataFrame:
    return _run("player_match_history", account_id=account_id)


def player_match_history(account_id: int) -> pd.DataFrame:
    return _player_match_history(int(account_id), data_version())


@st.cache_data(ttl="10m", max_entries=64)
def _player_name(account_id: int, version: int) -> str | None:
    df = run_query("SELECT account_name FROM player WHERE account_id = :id", {"id": account_id})
    return None if df.empty or pd.isna(df["account_name"].iloc[0]) else df["account_name"].iloc[0]


def player_name(account_id: int) -> str | None:
    """Steam display name for an account, or None if unknown."""
    return _player_name(int(account_id), data_version())


@st.cache_data(ttl="10m", max_entries=64)
def _search_players(text: str, version: int) -> pd.DataFrame:
    # escape LIKE wildcards so the search text matches literally
    pattern = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    return run_query(
        """SELECT p.account_id, p.account_name, COUNT(*) AS matches
           FROM player p JOIN match_player mp USING (account_id)
           WHERE p.account_name ILIKE :pattern
           GROUP BY p.account_id, p.account_name
           ORDER BY lower(p.account_name) = lower(:text) DESC, matches DESC, p.account_id
           LIMIT 20""",
        {"pattern": pattern, "text": text},
    )


def search_players(text: str) -> pd.DataFrame:
    """Up to 20 players whose name contains text: exact matches first, then the most active."""
    return _search_players(text, data_version())
