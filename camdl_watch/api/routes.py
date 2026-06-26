"""Read-only API routes — the typed projection of the run store as JSON.

Each request resolves the store fresh via ``current_store()`` (so the CLI and
tests can repoint it), discovers runs through :mod:`camdl_watch.ingest`, builds
a :class:`~camdl_watch.state.RunState` server-side, and serializes the
diagnostics / docs / schema the core already computed. No statistic is computed
in the browser; every number here is produced in Python (the proposal's
correctness guardrail).

A run state is rebuilt per request (a full tail-read of each chain). That is
fine for finished fits polled infrequently; a signature-keyed cache is a clean
later optimization, not a correctness requirement.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException, Query

from .. import diagnostics as diag_mod
from .. import ingest
from .. import predictive
from ..grouping import group_params
from ..highlight import HIGHLIGHT_CSS, highlight_camdl, highlight_toml
from ..state import (
    AUX_COLUMNS,
    ChainBuffer,
    PriorFamily,
    PriorSpec,
    RunMeta,
    RunState,
    Status,
)
from .models import (
    DimensionInfo,
    DrawsResponse,
    FindingGroup,
    ObservedPoint,
    ParamFamily,
    ParamGroups,
    ParamPosterior,
    ParamTrace,
    PosteriorResponse,
    PredictivePoint,
    PredictiveResponse,
    RunDetail,
    RunSummary,
    SourceFile,
    SourceResponse,
    StreamInfo,
    TraceSeries,
    TracesResponse,
)

router = APIRouter(prefix="/api")

_QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)


def _store() -> Path:
    """The store to read, resolved fresh per request. Imported lazily from the
    app module to keep the import acyclic (app.py imports this module to mount
    the router)."""
    from .app import current_store

    return current_store()


# ---------------------------------------------------------------------------
# Run-state assembly (server-side; never shipped raw)
# ---------------------------------------------------------------------------


def _classify(rs: RunState, now: float) -> Status:
    """Status from camdl's ``progress.json`` heartbeat when present (terminal
    states win regardless of freshness; a fresh ``running`` beat is live), else
    the ``.lock`` PID + presence of draws.

    NOTE: replicated verbatim from ``camdl_watch.app._classify`` — that module
    imports ``shiny``, so the API layer cannot import it. Candidate to extract
    into a shiny-free status helper and share; keep the two in sync until then.
    """
    prog = rs.progress
    if prog is not None:
        if prog.state == "done":
            return Status.DONE
        if prog.state == "failed":
            return Status.FAILED
        if prog.state == "running":
            if not ingest.progress_is_fresh(prog, now):
                return Status.STALLED
            return Status.WARMING if prog.phase == "burn_in" else Status.RUNNING
        return Status.DONE
    live = ingest.stage_is_live(rs.meta.posterior_dir)
    has_draws = any(buf.n for buf in rs.chains.values())
    if has_draws:
        return Status.RUNNING if live else Status.DONE
    return Status.WARMING if live else Status.STALLED


def _build_run_state(meta: RunMeta) -> RunState:
    """Assemble a full :class:`RunState` for one run: tail-read every chain from
    offset 0, attach priors / progress / authoritative summary, and classify."""
    rs = RunState(meta=meta)
    max_mtime = 0.0
    for cid, path in meta.chain_paths.items():
        buf = ChainBuffer(cid=cid, path=path)
        ingest.tail_chain(buf)  # full read from offset 0
        rs.chains[cid] = buf
        try:
            max_mtime = max(max_mtime, path.stat().st_mtime)
        except OSError:
            pass
    rs.priors = ingest.extract_priors(meta)
    rs.progress = ingest.read_progress(meta.posterior_dir)
    rs.summary = ingest.read_chain_summary(meta.posterior_dir)
    rs.updated_at = max_mtime
    rs.status = _classify(rs, time.time())
    return rs


def _warmup_cutoff(rs: RunState, warmup_pct: int) -> int:
    """Sweep index that splits warm-up from the retained tail (app.py's rule)."""
    lo = rs.min_iter() or 0
    hi = rs.max_iter() or lo
    return int(lo + (hi - lo) * warmup_pct / 100.0)


# ---------------------------------------------------------------------------
# Formatting / projection helpers
# ---------------------------------------------------------------------------


def _g(x: float) -> str:
    """Compact number for a prior label: drops trailing zeros (``0.0`` -> ``0``,
    ``-0.6`` -> ``-0.6``)."""
    return f"{float(x):g}"


def _format_prior(spec: PriorSpec | None) -> str | None:
    """A resolved prior as a human label, e.g. ``LogNormal(μ=-0.6, σ=0.4)``,
    ``Beta(α=3, β=6)``, ``Uniform(0, 1)``, ``Flat[-5, 5]``. ``None`` when there
    is no prior to render."""
    if spec is None:
        return None
    a = spec.args
    f = spec.family
    if f is PriorFamily.NORMAL:
        return f"Normal(μ={_g(a.get('mu', 0.0))}, σ={_g(a.get('sigma', 1.0))})"
    if f is PriorFamily.LOGNORMAL:
        return f"LogNormal(μ={_g(a.get('mu', 0.0))}, σ={_g(a.get('sigma', 1.0))})"
    if f is PriorFamily.HALFNORMAL:
        return f"HalfNormal(σ={_g(a.get('sigma', 1.0))})"
    if f is PriorFamily.BETA:
        return f"Beta(α={_g(a.get('alpha', 1.0))}, β={_g(a.get('beta', 1.0))})"
    if f is PriorFamily.GAMMA:
        return f"Gamma(α={_g(a.get('alpha', 1.0))}, β={_g(a.get('beta', 1.0))})"
    if f is PriorFamily.UNIFORM:
        return f"Uniform({_g(a.get('lo', 0.0))}, {_g(a.get('hi', 1.0))})"
    # FLAT: a bounds-only / improper prior.
    if spec.bounds is not None:
        lo, hi = spec.bounds
        return f"Flat[{_g(lo)}, {_g(hi)}]"
    return "Flat"


def _finite_or_none(x: float | None) -> float | None:
    """A diagnostic value for the wire: ``None`` unless it is a finite float
    (Starlette serializes with ``allow_nan=False``, so NaN/inf cannot ship)."""
    if x is None:
        return None
    x = float(x)
    return x if np.isfinite(x) else None


def _run_summary(meta: RunMeta, rs: RunState) -> RunSummary:
    return RunSummary(
        run_id=meta.run_id,
        label=meta.display_label,
        model=meta.model,
        algorithm=meta.algorithm,
        backend=meta.backend.value,
        status=rs.status.value,
        n_chains=len(rs.chains),
        n_params=len(meta.estimated),
        has_docs=not meta.docs.is_empty(),
        max_iter=rs.max_iter(),
        updated_at=rs.updated_at,
    )


def _run_detail(meta: RunMeta, rs: RunState) -> RunDetail:
    schema = meta.schema
    streams = [
        StreamInfo(
            name=s.name,
            index_dims=list(s.index_dims),
            value_kind=s.value_kind,
            likelihood=s.likelihood,
        )
        for s in (schema.streams if schema else [])
    ]
    dimensions = [
        DimensionInfo(name=d.name, levels=list(d.levels))
        for d in (schema.dimensions.values() if schema else [])
    ]
    findings: list[FindingGroup] = []
    if rs.summary is not None:
        for g in diag_mod.summarize_findings(rs.summary.findings):
            findings.append(
                FindingGroup(
                    kind=g.kind,
                    severity=g.severity.value,
                    headline=g.headline,
                    params=list(g.params),
                )
            )
    pg = group_params(list(meta.estimated))
    groups = ParamGroups(
        scalars=pg.scalars,
        families=[ParamFamily(base=b, members=ms) for b, ms in pg.families.items()],
        default_selection=pg.default_selection(),
    )
    return RunDetail(
        run_id=meta.run_id,
        label=meta.display_label,
        model=meta.model,
        algorithm=meta.algorithm,
        backend=meta.backend.value,
        status=rs.status.value,
        n_chains=len(rs.chains),
        max_iter=rs.max_iter(),
        target_sweeps=meta.target_sweeps,
        estimated=list(meta.estimated),
        groups=groups,
        streams=streams,
        dimensions=dimensions,
        findings=findings,
        # camdl writes predictive/observed at the FIT (run) dir level, not the
        # seed dir — read there.
        available_streams=predictive.discover_streams(meta.run_dir),
    )


def _param_posterior(
    meta: RunMeta, rs: RunState, diag, cutoff: int, param: str
) -> ParamPosterior | None:
    """Project one estimated coordinate onto the wire: pooled post-warmup
    quantiles (computed here), the resolved doc block + prior, and the effective
    R̂/ESS. ``None`` when the coordinate has no finite post-warmup draws."""
    parts = [
        buf.values[param][buf.iters >= cutoff]
        for buf in rs.chains.values()
        if param in buf.values
    ]
    vals = np.concatenate(parts) if parts else np.empty(0)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return None
    q05, q25, q50, q75, q95 = (float(x) for x in np.quantile(vals, _QUANTILES))
    mean = float(vals.mean())
    sd = float(vals.std(ddof=1)) if vals.size >= 2 else 0.0

    block = meta.docs.for_param(param)
    spec = rs.priors.get(param)
    rhat_v, _ = diag_mod.effective_rhat(diag, rs.summary, param)
    ess_v, _ = diag_mod.effective_ess(diag, rs.summary, param)
    return ParamPosterior(
        name=param,
        symbol=block.symbol if block else None,
        description=block.text if block else None,
        reference=block.reference if block else None,
        source=spec.source if spec else "unknown",
        prior=_format_prior(spec),
        bounds=spec.bounds if spec else None,
        mean=mean,
        sd=sd,
        q05=q05,
        q25=q25,
        q50=q50,
        q75=q75,
        q95=q95,
        rhat=_finite_or_none(rhat_v),
        ess=_finite_or_none(ess_v),
    )


def _build_draws(
    meta: RunMeta, rs: RunState, cutoff: int, max_draws: int
) -> tuple[list[int], dict[str, np.ndarray]]:
    """Row-aligned, pooled, thinned post-warmup draws.

    Within a chain the i-th retained sweep is the same joint sample across
    params; chains are concatenated (carrying a chain id per row). Rows where any
    estimated coordinate is non-finite are dropped so every column stays aligned
    and JSON-serializable, then the whole set is thinned to ``max_draws`` by an
    even stride."""
    params = list(meta.estimated)
    chain_parts: list[np.ndarray] = []
    col_parts: dict[str, list[np.ndarray]] = {p: [] for p in params}
    for cid, buf in sorted(rs.chains.items()):
        idx = np.where(buf.iters >= cutoff)[0]
        if idx.size == 0:
            continue
        chain_parts.append(np.full(idx.size, cid, dtype=np.int64))
        for p in params:
            col_parts[p].append(
                buf.values[p][idx] if p in buf.values else np.full(idx.size, np.nan)
            )
    if not chain_parts:
        return [], {p: np.empty(0) for p in params}

    chain = np.concatenate(chain_parts)
    cols = {p: np.concatenate(col_parts[p]) for p in params}
    finite = np.ones(chain.size, dtype=bool)
    for p in params:
        finite &= np.isfinite(cols[p])
    chain = chain[finite]
    cols = {p: cols[p][finite] for p in params}

    total = chain.size
    if total > max_draws:
        sel = np.unique(np.linspace(0, total - 1, max_draws).astype(int))
        chain = chain[sel]
        cols = {p: cols[p][sel] for p in params}
    return chain.tolist(), cols


def _find_meta(store: Path, run_id: str) -> RunMeta | None:
    for meta in ingest.discover_runs(store, include_warming=True):
        if meta.run_id == run_id:
            return meta
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/runs", response_model=list[RunSummary])
def list_runs() -> list[RunSummary]:
    """Every discoverable run, newest first by last-written chain mtime."""
    store = _store()
    summaries = [
        _run_summary(meta, _build_run_state(meta))
        for meta in ingest.discover_runs(store, include_warming=True)
    ]
    summaries.sort(key=lambda s: s.updated_at, reverse=True)
    return summaries


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: str) -> RunDetail:
    """One run's metadata, schema, and authoritative verdict."""
    store = _store()
    meta = _find_meta(store, run_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return _run_detail(meta, _build_run_state(meta))


@router.get("/runs/{run_id}/posterior", response_model=PosteriorResponse)
def get_posterior(
    run_id: str, warmup_pct: int = Query(default=50, ge=0, le=100)
) -> PosteriorResponse:
    """Doc-labelled posterior summary (the forest-plot payload). Params are in
    the model's estimated order; a run with no draws yet returns ``params=[]``
    and ``n_tail=0`` rather than erroring."""
    store = _store()
    meta = _find_meta(store, run_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    rs = _build_run_state(meta)
    cutoff = _warmup_cutoff(rs, warmup_pct)
    if rs.max_iter() is None:  # warming up — no draws to summarize
        return PosteriorResponse(
            run_id=run_id, warmup_pct=warmup_pct, warmup_cutoff=cutoff,
            n_tail=0, params=[],
        )
    diag = diag_mod.compute_diagnostics(rs, cutoff, params=rs.params)
    params = [
        pp
        for p in meta.estimated
        if (pp := _param_posterior(meta, rs, diag, cutoff, p)) is not None
    ]
    return PosteriorResponse(
        run_id=run_id, warmup_pct=warmup_pct, warmup_cutoff=cutoff,
        n_tail=diag.n_tail, params=params,
    )


def _sample_priors(rs: RunState, params: list[str], n: int = 2000) -> dict[str, list[float]]:
    """Marginal prior samples per param (for the pair-plot diagonal overlay).

    Drawn from each resolved :class:`PriorSpec` with a fixed seed (deterministic
    per request), truncated to bounds by the sampler. A param with no usable
    prior (e.g. an unbounded flat) yields an empty list."""
    rng = np.random.default_rng(0)
    out: dict[str, list[float]] = {}
    for p in params:
        spec = rs.priors.get(p)
        if spec is None:
            out[p] = []
            continue
        s = ingest.sample_prior(spec, n=n, rng=rng)
        out[p] = s[np.isfinite(s)].tolist()
    return out


@router.get("/runs/{run_id}/draws", response_model=DrawsResponse)
def get_draws(
    run_id: str,
    warmup_pct: int = Query(default=50, ge=0, le=100),
    max_draws: int = Query(default=1200, ge=50, le=5000),
) -> DrawsResponse:
    """Row-aligned post-warmup draws (plus marginal prior samples) for the
    marginal densities and the pair plot. Pooled across chains, thinned to
    ``max_draws``; ``params`` in estimated order. A run with no draws yet returns
    empty columns and ``n_draws=0`` (priors are still sampled)."""
    store = _store()
    meta = _find_meta(store, run_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    rs = _build_run_state(meta)
    cutoff = _warmup_cutoff(rs, warmup_pct)
    params = list(meta.estimated)
    prior = _sample_priors(rs, params)
    if rs.max_iter() is None:
        return DrawsResponse(
            run_id=run_id, warmup_pct=warmup_pct, warmup_cutoff=cutoff,
            n_draws=0, params=params, chain=[], draws={p: [] for p in params},
            prior=prior,
        )
    chain, cols = _build_draws(meta, rs, cutoff, max_draws)
    return DrawsResponse(
        run_id=run_id, warmup_pct=warmup_pct, warmup_cutoff=cutoff,
        n_draws=len(chain), params=params,
        chain=chain, draws={p: cols[p].tolist() for p in params},
        prior=prior,
    )


# ---------------------------------------------------------------------------
# Source tab
# ---------------------------------------------------------------------------


def _project_root(store: Path) -> Path:
    """The camdl project root a fit's *relative* paths resolve against. The store
    is ``<root>/results/fits``, so the project root is two levels up."""
    return store.parent.parent if store.name == "fits" else store.parent


def _read_model_source(store: Path, model_path: str) -> SourceFile:
    """The model source, syntax-highlighted. Resolves a relative recorded
    ``model_path`` against the project root (newer fits store it relative; older
    ones absolute). Read live from the path — the model isn't in the CAS."""
    if not model_path:
        return SourceFile(path=None, present=False)
    p = Path(model_path)
    if not p.is_absolute():
        p = _project_root(store) / p
    if not p.is_file():
        return SourceFile(path=model_path, present=False)
    try:
        text = p.read_text()
    except OSError:
        return SourceFile(path=model_path, present=False)
    return SourceFile(path=model_path, present=True, html=highlight_camdl(text), text=text)


@router.get("/runs/{run_id}/source", response_model=SourceResponse)
def get_source(run_id: str) -> SourceResponse:
    """The fit's sources: the highlighted ``.camdl`` model (read live from its
    recorded path) and the mirrored ``fit.toml`` (always in the run store)."""
    store = _store()
    meta = _find_meta(store, run_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    try:
        meta_json = json.loads((meta.run_dir / "fit.meta.json").read_text())
    except (OSError, json.JSONDecodeError):
        meta_json = {}
    model = _read_model_source(store, str(meta_json.get("model_path", "")))

    toml_path = meta.run_dir / "fit.toml.original"
    if toml_path.is_file():
        try:
            ttext = toml_path.read_text()
            fit_toml = SourceFile(
                path="fit.toml", present=True, html=highlight_toml(ttext), text=ttext
            )
        except OSError:
            fit_toml = SourceFile(path="fit.toml", present=False)
    else:
        fit_toml = SourceFile(path="fit.toml", present=False)

    return SourceResponse(
        run_id=run_id, model=model,
        model_identity=meta_json.get("model_identity"),
        fit_toml=fit_toml, highlight_css=HIGHLIGHT_CSS,
    )


# ---------------------------------------------------------------------------
# Predictive tab
# ---------------------------------------------------------------------------


def _stream_index_dims(meta: RunMeta, stream: str) -> list[str]:
    if meta.schema is None:
        return []
    for s in meta.schema.streams:
        if s.name == stream:
            return list(s.index_dims)
    return []


def _fnum(v: object) -> float:
    """A finite float for the wire (Starlette can't serialize NaN/inf)."""
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return f if np.isfinite(f) else 0.0


@router.get("/runs/{run_id}/predictive/{stream}", response_model=PredictiveResponse)
def get_predictive(run_id: str, stream: str) -> PredictiveResponse:
    """One stream's posterior-predictive ribbons (``camdl fit predict`` output)
    plus the observed series. 404 if the stream has no predictive artifact."""
    store = _store()
    meta = _find_meta(store, run_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    ps = predictive.read_predictive(meta.run_dir, stream)
    if ps is None:
        raise HTTPException(status_code=404, detail=f"no predictive artifact for stream: {stream}")
    obs = predictive.read_observed(meta.run_dir, stream)
    index_dims = _stream_index_dims(meta, stream)

    def stratum(row: dict) -> dict[str, str]:
        return {d: str(row[d]) for d in index_dims if row.get(d) is not None}

    horizons: set[str] = set()
    treatments: set[str] = set()
    pred_points: list[PredictivePoint] = []
    for r in ps.table.to_dicts():
        h, t = str(r.get("horizon") or ""), str(r.get("treatment") or "")
        horizons.add(h)
        treatments.add(t)
        pred_points.append(
            PredictivePoint(
                time=_fnum(r.get("time")), stratum=stratum(r), horizon=h, treatment=t,
                q05=_fnum(r.get("q05")), q25=_fnum(r.get("q25")), q50=_fnum(r.get("q50")),
                q75=_fnum(r.get("q75")), q95=_fnum(r.get("q95")),
            )
        )
    obs_points: list[ObservedPoint] = []
    if obs is not None:
        for r in obs.table.to_dicts():
            v = r.get("value")
            obs_points.append(
                ObservedPoint(
                    time=_fnum(r.get("time")), stratum=stratum(r),
                    value=(_fnum(v) if v is not None else None),
                )
            )
    return PredictiveResponse(
        run_id=run_id, stream=stream, index_dims=index_dims,
        horizons=sorted(horizons), treatments=sorted(treatments),
        predictive=pred_points, observed=obs_points,
    )


# ---------------------------------------------------------------------------
# Traces tab
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/traces", response_model=TracesResponse)
def get_traces(
    run_id: str,
    warmup_pct: int = Query(default=50, ge=0, le=100),
    max_points: int = Query(default=600, ge=50, le=4000),
) -> TracesResponse:
    """Per-parameter, per-chain iteration traces (thinned) for the trace grid.
    Includes the estimated coordinates plus any present objective aux columns
    (``log_posterior`` / ``log_likelihood``) — the first thing to eyeball for
    mixing."""
    store = _store()
    meta = _find_meta(store, run_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    rs = _build_run_state(meta)
    cutoff = _warmup_cutoff(rs, warmup_pct)

    objectives = [
        c for c in ("log_posterior", "log_likelihood")
        if c in AUX_COLUMNS and any(c in b.aux for b in rs.chains.values())
    ]
    traces: list[ParamTrace] = []
    for p in list(meta.estimated) + objectives:
        series: list[TraceSeries] = []
        for cid, buf in sorted(rs.chains.items()):
            arr = buf.values.get(p)
            if arr is None:
                arr = buf.aux.get(p)
            if arr is None or buf.iters.size == 0:
                continue
            m = min(buf.iters.size, arr.size)
            it, vv = buf.iters[:m], arr[:m]
            # Trim the burn-in off the left so the trace tab's slider actually
            # removes the messy initial transient (and the y-scale rescales to
            # the stationary region). At warmup_pct=0 the cutoff is the first
            # sweep, so nothing is dropped.
            keep = it >= cutoff
            it, vv = it[keep], vv[keep]
            if it.size > max_points:
                sel = np.unique(np.linspace(0, it.size - 1, max_points).astype(int))
                it, vv = it[sel], vv[sel]
            finite = np.isfinite(vv)
            series.append(
                TraceSeries(
                    chain=int(cid),
                    iters=it[finite].astype(np.int64).tolist(),
                    values=vv[finite].tolist(),
                )
            )
        if series:
            traces.append(ParamTrace(param=p, series=series))
    return TracesResponse(
        run_id=run_id, warmup_cutoff=cutoff,
        params=[t.param for t in traces], traces=traces,
    )
