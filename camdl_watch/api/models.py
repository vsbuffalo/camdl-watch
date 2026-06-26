"""Pydantic wire models — the typed JSON contract the browser depends on.

These re-project the Python core's ADTs (``state.py`` / ``docs.py`` /
``schema.py``) onto the HTTP boundary. FastAPI turns them into the OpenAPI
schema, which ``openapi-typescript`` turns into ``web/src/api/types.ts`` — one
source of truth, typed on both ends. Nothing here computes anything: the routes
fill these in from numbers the core already produced (R̂, ESS, quantiles), so a
field carries a value, never a recipe for one.

Floats on the wire are always finite. R̂/ESS that the core could not estimate
arrive as ``None`` (not ``NaN``) because Starlette serializes with
``allow_nan=False``; the routes are responsible for that conversion.
"""

from __future__ import annotations

from pydantic import BaseModel


class ParamPosterior(BaseModel):
    """One estimated coordinate, doc-labelled and summarized — the unit a forest
    plot draws: a point (``q50``) with an interval (``q05``…``q95``), a human
    label (``symbol`` / ``description`` / ``reference``), and its prior."""

    name: str
    symbol: str | None = None
    description: str | None = None
    reference: str | None = None
    source: str  # prior provenance: fit_toml | model_ir | default
    prior: str | None = None  # human-formatted prior, e.g. "LogNormal(μ=-0.6, σ=0.4)"
    bounds: tuple[float, float] | None = None
    mean: float
    sd: float
    q05: float
    q25: float
    q50: float
    q75: float
    q95: float
    rhat: float | None = None
    ess: float | None = None


class PosteriorResponse(BaseModel):
    """Doc-labelled posterior summary for one run — what the first frontend
    screen (the forest plot) consumes. ``params`` is in the model's estimated
    order; empty when the run has no draws yet."""

    run_id: str
    warmup_pct: int
    warmup_cutoff: int
    n_tail: int
    params: list[ParamPosterior]


class DrawsResponse(BaseModel):
    """Row-aligned post-warmup posterior draws — the substrate for proper
    statistical graphics (marginal densities, the pair/corner plot). Row ``i`` is
    one joint sample: ``draws[param][i]`` for every param, drawn by chain
    ``chain[i]``. Pooled across chains and thinned to at most ``max_draws`` rows;
    every value is finite (non-finite rows are dropped to keep alignment)."""

    run_id: str
    warmup_pct: int
    warmup_cutoff: int
    n_draws: int
    params: list[str]
    chain: list[int]
    draws: dict[str, list[float]]
    # Marginal prior samples per param (NOT row-aligned; truncated to bounds, may
    # be shorter/empty) — for the prior overlay on the pair-plot diagonals.
    prior: dict[str, list[float]] = {}


class StreamInfo(BaseModel):
    """One observation stream's structure (from the fit's ``schema``)."""

    name: str
    index_dims: list[str]
    value_kind: str | None = None
    likelihood: str | None = None


class DimensionInfo(BaseModel):
    """One indexing dimension and its ordered levels (from the fit's ``schema``)."""

    name: str
    levels: list[str]


class FindingGroup(BaseModel):
    """One ``kind`` of camdl diagnostic finding, collapsed to a single line."""

    kind: str
    severity: str
    headline: str
    params: list[str]


class RunSummary(BaseModel):
    """A run as it appears in the selector list — enough to identify, label, and
    badge it without fetching its draws."""

    run_id: str
    label: str
    model: str
    algorithm: str
    backend: str
    status: str
    n_chains: int
    n_params: int
    has_docs: bool
    max_iter: int | None = None
    updated_at: float


class ParamFamily(BaseModel):
    """An indexed parameter family — a base name expanded per stratum, e.g.
    ``k_raw`` → ``[k_raw_Bo, k_raw_Bombali, …]``. The UI toggles these as a group."""

    base: str
    members: list[str]


class ParamGroups(BaseModel):
    """Estimated coordinates partitioned for selection UIs: ungrouped ``scalars``
    plus indexed ``families`` (≥2 members). ``default_selection`` is the
    recommended visible set (scalars + hyperparameters; family leaves hidden) so
    a 20-parameter hierarchical fit doesn't open as a wall of panels."""

    scalars: list[str]
    families: list[ParamFamily]
    default_selection: list[str]


class RunDetail(BaseModel):
    """A run's metadata, schema, and verdict — everything but the draws."""

    run_id: str
    label: str
    model: str
    algorithm: str
    backend: str
    status: str
    n_chains: int
    max_iter: int | None = None
    target_sweeps: int | None = None
    estimated: list[str]
    groups: ParamGroups
    streams: list[StreamInfo]
    dimensions: list[DimensionInfo]
    findings: list[FindingGroup]
    available_streams: list[str]


# --- Source tab --------------------------------------------------------------


class SourceFile(BaseModel):
    """One source artifact: syntax-highlighted ``html`` to render and raw
    ``text`` for the copy button. ``present`` is false when the file couldn't be
    read (e.g. the model moved since the fit)."""

    path: str | None = None
    present: bool
    html: str = ""
    text: str = ""


class SourceResponse(BaseModel):
    """The fit's sources: the ``.camdl`` model (read live from its recorded
    path) and the ``fit.toml`` (mirrored in the run store). ``highlight_css`` is
    the Pygments token stylesheet to inject once."""

    run_id: str
    model: SourceFile
    model_identity: str | None = None
    fit_toml: SourceFile
    highlight_css: str


# --- Predictive tab ----------------------------------------------------------


class PredictivePoint(BaseModel):
    """One posterior-predictive ribbon point: quantiles at a time × stratum,
    for a given forecast ``horizon`` and ``treatment``."""

    time: float
    stratum: dict[str, str] = {}
    horizon: str = ""
    treatment: str = ""
    q05: float
    q25: float
    q50: float
    q75: float
    q95: float


class ObservedPoint(BaseModel):
    """One observed value to overlay (``value`` is null where the series has a hole)."""

    time: float
    stratum: dict[str, str] = {}
    value: float | None = None


class PredictiveResponse(BaseModel):
    """One stream's posterior-predictive ribbons + observed series. The frontend
    facets by ``stratum`` and filters by ``horizon`` (e.g. free_forward)."""

    run_id: str
    stream: str
    index_dims: list[str]
    horizons: list[str]
    treatments: list[str]
    predictive: list[PredictivePoint]
    observed: list[ObservedPoint]


# --- Traces tab --------------------------------------------------------------


class TraceSeries(BaseModel):
    """One chain's thinned trace for one parameter: aligned ``iters`` + ``values``."""

    chain: int
    iters: list[int]
    values: list[float]


class ParamTrace(BaseModel):
    """One parameter's per-chain traces (estimated coordinate, or an objective
    like ``log_posterior``)."""

    param: str
    series: list[TraceSeries]


class TracesResponse(BaseModel):
    """Per-parameter, per-chain iteration traces (thinned) for the trace grid —
    the raw mixing view. ``warmup_cutoff`` marks the retained-tail boundary."""

    run_id: str
    warmup_cutoff: int
    params: list[str]
    traces: list[ParamTrace]
