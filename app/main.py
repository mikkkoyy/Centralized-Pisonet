"""MKY PisoNet Central — FastAPI application assembly.

Startup (lifespan):
1. Validate configuration; refuse to start on missing/invalid
   required settings (no default secrets, no default admin).
2. Open the database engine and run pending versioned migrations
   (repeatable, tracked, fails loudly on unsupported states).
3. Resolve the enrollment secret (environment > persisted
   server_config > generated once and persisted).
4. Start the background session sweeper.

Shutdown: stop the sweeper and dispose the engine.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from app import __version__
from app.core.config import Settings, get_settings
from app.core.protocol import PROTOCOL_VERSION
from app.db.database import (
    create_engine_from_settings,
    get_session_factory,
    sqlite_path_from_url,
)
from app.db.migration_runner import upgrade as run_migrations
from app.models.runtime import ServerConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pisonet")


def _resolve_enrollment_secret(db, settings: Settings) -> str:
    """Environment value wins; otherwise use the persisted
    secret; otherwise generate once and persist so station
    credentials survive server restarts."""
    if settings.enrollment_secret:
        return settings.enrollment_secret
    row = (
        db.query(ServerConfig)
        .filter(ServerConfig.key == "enrollment_secret")
        .first()
    )
    if row is not None:
        return row.value
    generated = secrets.token_hex(32)
    db.add(
        ServerConfig(
            key="enrollment_secret",
            value=generated,
            updated_at=int(__import__("time").time()),
        )
    )
    db.commit()
    return generated


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    notices = settings.validate_or_generate_secrets()
    app.state.settings = settings

    engine = create_engine_from_settings(settings)
    app.state.engine = engine
    app.state.session_factory = get_session_factory(engine)

    # Explicit, versioned migrations at startup. Repeatable;
    # fails loudly on unsupported migration states.
    db_path = sqlite_path_from_url(settings)
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        applied = run_migrations(conn)
        if applied:
            logger.info("Applied migrations: %s", applied)
        else:
            logger.info("Database schema is up to date")
    finally:
        conn.close()

    # Resolve enrollment secret and surface operator notices.
    factory = app.state.session_factory
    db = factory()
    try:
        app.state.enrollment_secret = _resolve_enrollment_secret(db, settings)
    finally:
        db.close()
    for notice in notices:
        logger.warning("NOTICE: %s", notice)
    logger.info(
        "MKY PisoNet Central v%s starting (protocol v%d, environment=%s)",
        __version__,
        PROTOCOL_VERSION,
        settings.environment,
    )

    # Background session sweeper: expire sessions whose time
    # ran out even when heartbeats are sparse.
    stop_event = asyncio.Event()

    async def _sweeper() -> None:
        while not stop_event.is_set():
            try:
                await asyncio.sleep(30)
                db = factory()
                try:
                    from app.services.session import expire_stale_sessions

                    expired = expire_stale_sessions(db)
                    if expired:
                        logger.info("Expired %d session(s)", len(expired))
                finally:
                    db.close()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Session sweeper error")

    sweeper_task = asyncio.create_task(_sweeper())

    try:
        yield
    finally:
        stop_event.set()
        sweeper_task.cancel()
        try:
            await sweeper_task
        except (asyncio.CancelledError, Exception):
            pass
        engine.dispose()
        logger.info("MKY PisoNet Central stopped")


app = FastAPI(
    title="MKY PisoNet Central",
    version=__version__,
    lifespan=lifespan,
)

# Static assets and Jinja2 templates for the dashboard.
_templates = Jinja2Templates(directory="app/templates")
app.state.templates = _templates

from app.api.v1 import admin as admin_api  # noqa: E402
from app.api.v1 import health as health_api  # noqa: E402
from app.api.v1 import ledger as ledger_api  # noqa: E402
from app.api.v1 import stations as stations_api  # noqa: E402

app.include_router(health_api.router)
app.include_router(stations_api.router)
app.include_router(ledger_api.router)
app.include_router(admin_api.router)


def mount_web(app: FastAPI) -> None:
    """Mount the dashboard (web routes) and static files.
    Imported lazily to avoid circular imports at module load."""
    from pathlib import Path

    from app.web.main import web_router

    app.include_router(web_router)
    static_dir = Path(__file__).resolve().parent / "static"
    app.mount(
        "/static",
        StaticFiles(directory=str(static_dir)),
        name="static",
    )


mount_web(app)
