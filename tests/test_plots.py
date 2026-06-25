"""Plot smoke tests: render the enhanced pair plot (both toggle modes) and the
trace grid to PNGs against a real run, asserting the figure structure."""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import pytest

import numpy as np

from camdl_watch import ingest, plots
from camdl_watch.state import Backend, ChainBuffer, RunMeta, RunState


def _synthetic(algorithm: str, backend: Backend, aux: dict) -> RunState:
    meta = RunMeta(
        run_id="syn-0", run_dir=Path("/tmp"), posterior_dir=Path("/tmp"),
        chain_paths={}, model="m", algorithm=algorithm, backend=backend,
        estimated=["R0"], target_sweeps=None, declared_burn_in=None,
    )
    rs = RunState(meta=meta)
    buf = ChainBuffer(cid=1, path=Path("/tmp"))
    buf.iters = np.arange(10)
    buf.values = {"R0": np.linspace(1.0, 2.0, 10)}
    buf.aux = {k: np.full(10, v) for k, v in aux.items()}
    rs.chains[1] = buf
    return rs


def test_objective_pgas_defaults_to_obs_ll():
    rs = _synthetic("pgas", Backend.CHAIN_BINOMIAL,
                    {"obs_ll": -100.0, "log_posterior": -9000.0, "transition_ll": -8900.0})
    assert [k for k, _ in plots.objective_options(rs)] == ["obs_ll", "log_posterior", "transition_ll"]
    col, _ = plots.resolve_objective(rs, None)
    assert col == "obs_ll"
    # the default objective series is obs_ll, not the path-dominated log_posterior
    pd = plots.build_plot_data(rs, warmup=0)
    assert pd.objectives == ["obs_ll"]
    assert np.allclose(pd.chains[1]["obs_ll"], -100.0)
    # explicit selection is honored (and each becomes its own keyed series)
    pd2 = plots.build_plot_data(rs, warmup=0, objectives=["obs_ll", "log_posterior"])
    assert pd2.objectives == ["obs_ll", "log_posterior"]
    assert np.allclose(pd2.chains[1]["log_posterior"], -9000.0)


def test_objective_mh_uses_log_likelihood():
    rs = _synthetic("mh", Backend.ODE, {"log_likelihood": -50.0, "log_posterior": -60.0})
    assert [k for k, _ in plots.objective_options(rs)] == ["log_likelihood", "log_posterior"]
    col, _ = plots.resolve_objective(rs, None)
    assert col == "log_likelihood"


def test_resolve_objectives_multi_and_trace_panels():
    rs = _synthetic("pgas", Backend.CHAIN_BINOMIAL,
                    {"obs_ll": -100.0, "log_posterior": -9000.0, "transition_ll": -8900.0})
    # default -> primary only
    assert plots.resolve_objectives(rs, None) == ["obs_ll"]
    # selection respected, returned in canonical (best-first) order
    assert plots.resolve_objectives(rs, ["transition_ll", "obs_ll"]) == ["obs_ll", "transition_ll"]
    # unknowns dropped, falls back to primary when empty
    assert plots.resolve_objectives(rs, ["nope"]) == ["obs_ll"]
    # trace grid: one panel per param + one per selected objective
    fig = plots.trace_grid(rs, warmup=0, objectives=["obs_ll", "log_posterior"])
    assert len([ax for ax in fig.get_axes() if ax.get_visible()]) == 3  # R0 + 2 objectives

def test_mixing_bars_render():
    # Per-chain acceptance with a healthy band; one sticky chain (out of band).
    fig = plots.mixing_bars([0.99, 0.86, 0.30], ["c0", "c1", "c2"],
                            xlabel="acceptance", band=(0.15, 0.50), title="acc")
    ax = fig.get_axes()[0]
    assert ax.get_xlim() == (0.0, 1.0)
    assert len(ax.patches) >= 3  # one bar per chain (+ the band span)
    # band=None path (e.g. PGAS renewal) renders without the shaded span.
    fig2 = plots.mixing_bars([0.4, 0.5], ["c0", "c1"], xlabel="renewal", band=None)
    assert fig2.get_axes()


def test_ess_heatmap_render_and_param_filter():
    epc = {"R0": [4.0, 10.0, 11.0, 10.0], "k_obs": [47.0, 17.0, 45.0, 34.0],
           "Actrl": [7.0, 15.0, 5.0, 9.0]}
    fig = plots.ess_heatmap(epc, title="ess")
    ax = fig.get_axes()[0]
    assert len(ax.get_yticklabels()) == 3  # one row per param
    # param filter restricts/orders rows
    fig2 = plots.ess_heatmap(epc, params=["k_obs"])
    labels = [t.get_text() for t in fig2.get_axes()[0].get_yticklabels()]
    assert labels == ["k_obs"]
    # empty -> graceful placeholder, no crash
    assert plots.ess_heatmap({}, params=["nope"]).get_axes()


STORE = Path(os.environ.get("CAMDL_WATCH_STORE", Path(__file__).resolve().parents[3] / "results" / "fits"))
OUT = Path(__file__).resolve().parents[1]


def _load_run(prefix: str) -> RunState:
    metas = {m.run_id: m for m in ingest.discover_runs(STORE)}
    meta = next((m for k, m in metas.items() if k.startswith(prefix)), None)
    if meta is None:
        pytest.skip(f"{prefix} not present")
    rs = RunState(meta=meta)
    for cid, path in meta.chain_paths.items():
        buf = ChainBuffer(cid=cid, path=path)
        ingest.tail_chain(buf)
        rs.chains[cid] = buf
    rs.priors = ingest.extract_priors(meta)
    return rs


def test_pair_plot_both_modes_render():
    rs = _load_run("natbc_dens_hierk_nc_pgas_long")
    lo, hi = rs.min_iter(), rs.max_iter()
    warmup = int(lo + 0.5 * (hi - lo))
    pdata = plots.build_plot_data(rs, warmup)
    # the objective series is present in the plot data for every chain.
    assert pdata.objectives  # at least the primary
    for cid, d in pdata.chains.items():
        assert all(o in d for o in pdata.objectives)

    for mode in ("prior", "posterior"):
        fig = plots.enhanced_pair_plot(pdata, prior_xlim_mode=mode,
                                       title=f"pgas-long ({mode})")
        out = OUT / f"pairplot_pgas_long_{mode}.png"
        fig.savefig(out, dpi=110, bbox_inches="tight")
        assert out.stat().st_size > 0


def test_pair_plot_axes_are_locked_across_grid():
    """A given dimension's axis must be IDENTICAL everywhere it appears: every
    cell in a column shares x; every off-diagonal cell in a row shares y."""
    import numpy as np

    rs = _load_run("natbc_dens_hierk_nc_pgas_long")
    lo, hi = rs.min_iter(), rs.max_iter()
    warmup = int(lo + 0.5 * (hi - lo))

    from camdl_watch.grouping import group_params

    default_sel = group_params(list(rs.params)).default_selection()
    pdata = plots.build_plot_data(rs, warmup, params=default_sel)
    n = len(pdata.params)
    m = n + 1  # grid side incl. log_posterior

    for mode in ("prior", "posterior"):
        fig = plots.enhanced_pair_plot(pdata, prior_xlim_mode=mode)
        # axes are row-major (m x m); recover the grid.
        grid = [fig.axes[r * m:(r + 1) * m] for r in range(m)]

        # Column x-limits: collect xlim of every VISIBLE cell in each column.
        for j in range(m):
            xlims = [
                grid[i][j].get_xlim()
                for i in range(m)
                if grid[i][j].get_visible() and i >= j  # lower tri + diagonal
            ]
            for xl in xlims[1:]:
                assert np.allclose(xl, xlims[0]), f"col {j} x mismatch ({mode})"

        # Row y-limits: off-diagonal visible cells in each row share y.
        for i in range(m):
            ylims = [
                grid[i][j].get_ylim()
                for j in range(m)
                if grid[i][j].get_visible() and i > j  # strictly lower (no diag)
            ]
            for yl in ylims[1:]:
                assert np.allclose(yl, ylims[0]), f"row {i} y mismatch ({mode})"


def test_trace_grid_renders():
    rs = _load_run("natbc_dens_hierk_nc_pgas_long")
    lo, hi = rs.min_iter(), rs.max_iter()
    warmup = int(lo + 0.5 * (hi - lo))
    fig = plots.trace_grid(rs, warmup=warmup, title="pgas-long traces")
    out = OUT / "tracegrid_pgas_long.png"
    fig.savefig(out, dpi=110, bbox_inches="tight")
    assert out.stat().st_size > 0


def test_param_filter_drives_all_outputs_consistently():
    """The selected subset must drive the pair plot, trace grid, AND diagnostics
    table the same way — and the default (leaves hidden) yields a small grid."""
    from camdl_watch import diagnostics as diag_mod
    from camdl_watch.grouping import group_params

    rs = _load_run("natbc_dens_hierk_nc_pgas_long")
    lo, hi = rs.min_iter(), rs.max_iter()
    warmup = int(lo + 0.5 * (hi - lo))

    groups = group_params(list(rs.params))
    default_sel = groups.default_selection()  # scalars only, leaves hidden
    assert "k_raw" in groups.families
    assert all("k_raw" not in p for p in default_sel)
    assert len(default_sel) < len(rs.params)

    # build_plot_data respects the subset (plus the objective series)
    pdata = plots.build_plot_data(rs, warmup, params=default_sel)
    assert pdata.params == default_sel
    for d in pdata.chains.values():
        # only selected params + the objective series present
        keys = set(d) - set(pdata.objectives)
        assert keys <= set(default_sel)
        assert all(o in d for o in pdata.objectives)
    # pair plot grid is (n_sel + n_obj) square — much smaller than full
    fig = plots.enhanced_pair_plot(pdata)
    assert fig.axes  # rendered
    assert len(default_sel) + len(pdata.objectives) < len(rs.params) + 1

    # trace grid panels = selected + objective
    tg = plots.trace_grid(rs, warmup=warmup, params=default_sel)
    assert tg.axes

    # diagnostics table restricted to the same subset
    d_full = diag_mod.compute_diagnostics(rs, warmup)
    d_sel = diag_mod.compute_diagnostics(rs, warmup, params=default_sel)
    assert set(d_sel.per_param) == set(default_sel)
    assert set(d_full.per_param) == set(rs.params)
    assert set(d_sel.chain_separation) == set(default_sel)

    # turning the family ON brings the leaves back into all outputs
    with_leaves = default_sel + groups.families["k_raw"]
    pdata2 = plots.build_plot_data(rs, warmup, params=with_leaves)
    assert set(groups.families["k_raw"]) <= set(pdata2.params)
    d2 = diag_mod.compute_diagnostics(rs, warmup, params=with_leaves)
    assert set(groups.families["k_raw"]) <= set(d2.per_param)
