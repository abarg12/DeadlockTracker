"""Filter controls and loading status shared by the stats pages."""

import datetime as dt
import pandas as pd
import streamlit as st
from db.queries import data_version, ingest_status, last_ingest_time, match_modes, newest_match_time, window_start

WINDOWS = {1: "Last day", 3: "Last 3 days", 7: "Last 7 days"}


def _load_progress(status: dict | None) -> float | None:
    """Share of the week loaded during a backfill (0 before it starts), or None when not loading."""
    if status is None:
        return 0.0
    done, total = status.get("backfill_done"), status.get("backfill_total")
    if pd.isna(total) or not total:
        # no backfill recorded yet: still loading only if the first run hasn't finished
        return 0.0 if pd.isna(status.get("last_run_at")) else None
    return None if done >= total else float(done) / float(total)


@st.fragment(run_every="10s")
def _loading_banner(version: int) -> None:
    """Progress bar that reruns the page whenever the ingest commits new data."""
    if data_version() != version:
        st.rerun(scope="app")
    progress = _load_progress(ingest_status())
    if progress is not None:
        st.progress(progress, text=f"Loading the past week of matches: {progress:.0%}. "
                                   "This page updates on its own as data arrives.")


def require_data() -> None:
    """Shows load progress while the first ingest runs, and stops the page until some matches exist."""
    if _load_progress(ingest_status()) is not None:
        _loading_banner(data_version())
    if newest_match_time() is None:
        st.info("The first matches will appear here within a minute or two.", icon=":material/hourglass_top:")
        st.stop()


def window_filter() -> dt.datetime:
    """Time window control (kept across pages); returns the window's start."""
    days = st.segmented_control(
        "Time window",
        list(WINDOWS),
        format_func=WINDOWS.get,
        default=7,
        required=True,
        key="window_days",
        persist_state="session",
    )
    return window_start(days)


def match_mode_filter() -> str:
    """Match mode control, kept across pages."""
    modes = match_modes()
    return st.segmented_control(
        "Match mode",
        modes,
        default="Ranked" if "Ranked" in modes else modes[0],
        required=True,
        key="match_mode",
        persist_state="session",
    )


def data_through_caption() -> None:
    newest = newest_match_time().astimezone(dt.timezone.utc)
    updated = last_ingest_time()
    note = f", updated {updated.astimezone(dt.timezone.utc):%H:%M} UTC" if updated else ", first load in progress"
    st.caption(f"Data through {newest:%b %d, %Y %H:%M} UTC{note}. New matches are added automatically.")
