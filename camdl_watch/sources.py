"""Read a run's source files for the Source tab.

Two files back a run, and they live differently in the store:

* ``fit.toml`` is **mirrored** into the run dir as ``fit.toml.original`` — a
  byte copy, always available.
* the ``.camdl`` model is **not** stored in the content-addressed store. The
  run records only its absolute ``model_path`` and an IR-identity hash
  (``model_identity``), so we read the model live from that path; if it has
  moved or changed since the fit, this is the current source, not a snapshot.

Kept beside the app (not in the shared ingest layer) so the source-tab reader
stays small and self-contained.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunSources:
    model_path: Path | None     # recorded absolute model path (may be missing)
    model_text: str | None      # model source, or None if unreadable/missing
    model_identity: str | None  # recorded IR-identity hash (provenance only)
    toml_path: Path | None      # the mirrored fit.toml.original, if present
    toml_text: str | None       # fit TOML source, or None if missing


def read_run_sources(run_dir: Path) -> RunSources:
    """Read the fit TOML (mirrored) and the model (from its recorded path)."""
    run_dir = Path(run_dir)

    toml_path = run_dir / "fit.toml.original"
    toml_text = _safe_read(toml_path)

    model_path: Path | None = None
    model_identity: str | None = None
    meta_path = run_dir / "fit.meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            meta = {}
        mp = meta.get("model_path")
        model_path = Path(mp) if mp else None
        model_identity = meta.get("model_identity")

    model_text = _safe_read(model_path) if model_path else None

    return RunSources(
        model_path=model_path,
        model_text=model_text,
        model_identity=model_identity,
        toml_path=toml_path if toml_text is not None else None,
        toml_text=toml_text,
    )


def _safe_read(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    try:
        return path.read_text()
    except OSError:
        return None
