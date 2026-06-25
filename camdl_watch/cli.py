"""camdl-watch CLI — launch the live MCMC-diagnostics dashboard.

A thin ``defopt`` wrapper over :func:`shiny.run_app`. ``--store`` is mapped to
the ``CAMDL_WATCH_STORE`` env var (the app's public override), set before the
app module is imported so it picks up the chosen store.
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
    port: int = 8804,
) -> None:
    """Launch the camdl-watch dashboard.

    Serves the live MCMC-diagnostics dashboard for a camdl fit store, then
    prints the URL to open. Bind ``--host 0.0.0.0`` to reach it from a phone
    over LAN / Tailscale.

    :param store: camdl fit store to watch (the directory of run dirs).
        Defaults to ``results/fits`` under the current working directory.
    :param host: Network interface to bind.
    :param port: TCP port to serve on.
    """
    if store is not None:
        os.environ["CAMDL_WATCH_STORE"] = str(store)
    # Import after setting the env var: app reads CAMDL_WATCH_STORE at import.
    from shiny import run_app

    from .app import app

    run_app(app, host=host, port=port)


def cli() -> None:
    """Console-script entry point."""
    defopt.run(main)
