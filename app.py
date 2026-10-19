"""Serves the dashboard and keeps its data current by ingesting new matches in the background.

    streamlit run app.py
"""

import logging
from contextlib import asynccontextmanager

import anyio
import streamlit as st

log = logging.getLogger("deadlock.ingest")


@asynccontextmanager
async def lifespan(app):
    from ingest import live

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")

    async def ingest_periodically():
        while True:
            try:
                await anyio.to_thread.run_sync(live.run_once, abandon_on_cancel=True)
            except Exception:
                log.exception("ingest failed; retrying next interval")
            await anyio.sleep(live.settings()["interval_minutes"] * 60)

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(ingest_periodically)
        try:
            yield
        finally:
            live.STOP.set()
            task_group.cancel_scope.cancel()


app = st.App("dashboard.py", lifespan=lifespan)
