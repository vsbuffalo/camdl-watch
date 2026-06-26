"""FastAPI application: the typed seam between the Python core and the browser.

Routes live under ``/api/*``; the built frontend (``web/dist``) is mounted at
``/`` when present, so a single ``camdl-watch`` process serves both. The store
to read is taken from ``CAMDL_WATCH_STORE`` (set by the CLI / env), else
``results/fits`` under the working directory — matching the v1 app's contract.

This module must import cleanly even while the rest of the core is mid-edit:
the run store is only touched inside request handlers (lazily), never at import.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Store resolution mirrors the v1 app: an explicit override wins, else the
# conventional ``results/fits`` under the directory camdl-watch is launched from.
_DEFAULT_STORE = Path.cwd() / "results" / "fits"

# repo root = camdl_watch/api/app.py -> api -> camdl_watch -> <root>
_WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


def current_store() -> Path:
    """The fit store to read, resolved *fresh* on every call from
    ``CAMDL_WATCH_STORE`` (the CLI/env override), else the conventional
    ``results/fits``. Reading the env each call — rather than freezing it at
    import — lets the CLI and the tests repoint the store after this module is
    imported."""
    return Path(os.environ.get("CAMDL_WATCH_STORE", str(_DEFAULT_STORE)))


app = FastAPI(title="camdl-watch", version="2.0.0-dev")


@app.middleware("http")
async def _no_cache_html(request, call_next):
    """Serve the SPA shell (index.html) no-cache so a rebuilt frontend shows up
    on a normal refresh — it references content-hashed assets, which stay
    cacheable. Without this the browser pins a stale index.html and never sees
    new builds."""
    response = await call_next(request)
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.get("/api/health")
def health() -> dict:
    """Liveness + a cheap store summary, for the frontend's plumbing check.

    Run discovery is best-effort: a malformed/absent store must never 500 the
    health probe, so discovery failures degrade to ``runs: 0`` rather than
    propagating (the broad guard is deliberate and scoped to this probe)."""
    store = current_store()
    runs = 0
    try:
        from .. import ingest

        runs = len(ingest.discover_runs(store, include_warming=True))
    except Exception:  # health must stay green regardless of store state
        runs = 0
    return {"status": "ok", "store": str(store), "runs": runs}


# Typed read-only API under /api. Mounted before the SPA static block so the
# /api routes win; the catch-all "/" mount must stay last.
from .routes import router  # noqa: E402  (import here: see ordering note above)

app.include_router(router)


# Serve the built SPA at the root when it exists (production / `make serve`).
# In dev the frontend runs under Vite and proxies /api here, so the absence of
# web/dist is expected and fine.
if _WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_WEB_DIST), html=True), name="web")
