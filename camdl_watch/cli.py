"""camdl-watch CLI — launch the browser results viewer.

A thin ``defopt`` wrapper over :func:`uvicorn.run`. ``--store`` maps to the
``CAMDL_WATCH_STORE`` env var (the app's public override), set before the app is
imported so it reads the chosen store. The server hosts the JSON API under
``/api`` and, when ``web/dist`` has been built, the React frontend at ``/``.

For frontend development, run the API with reload and the Vite dev server
side by side via ``make dev`` instead of this launcher.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import defopt


def main(
    *,
    store: Optional[Path] = None,
    host: str = "127.0.0.1",
    port: int = 8800,
) -> None:
    """Launch the camdl-watch results viewer.

    Serves the JSON API (and the built frontend, if present) for a camdl fit
    store. Bind ``--host 0.0.0.0`` to reach it from a phone over LAN / Tailscale.

    :param store: camdl fit store to read (the directory of run dirs).
        Defaults to ``results/fits`` under the current working directory.
    :param host: Network interface to bind.
    :param port: TCP port to serve on.
    """
    if store is not None:
        os.environ["CAMDL_WATCH_STORE"] = str(store)
    # Import after setting the env var: the app reads CAMDL_WATCH_STORE at import.
    import uvicorn

    uvicorn.run("camdl_watch.api.app:app", host=host, port=port, reload=False)


def cli() -> None:
    """Console-script entry point."""
    defopt.run(main)
