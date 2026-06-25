"""Plotting — vendored and evolved from the repo's ``viz/pair_plot.py`` and
``viz/traces.py`` styling, self-contained (no ``ebola_camdl`` import).

Two headline figures:

  * :func:`enhanced_pair_plot` — lower-triangle scatter + per-chain colored
    diagonal histograms, PLUS a bottom row of ``param`` vs ``log_posterior``
    scatters with the ``log_posterior`` marginal in the far-right diagonal
    cell, PLUS a light-gray prior overlay on each parameter diagonal, with a
    toggle for the x-limits ("show prior breadth" vs "fit to posterior").

  * :func:`trace_grid` — per-param + log_posterior trace panels, all chains
    overlaid, decimated, with the warm-up region shaded.

Inputs are plain numpy via :class:`PlotData`, decoupled from RunState so the
plots are testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from matplotlib.figure import Figure

from .ingest import sample_prior
from .state import PriorSpec


# ---------------------------------------------------------------------------
# Color palette (vendored from viz/pair_plot.chain_color_palette)
# ---------------------------------------------------------------------------

def chain_color_palette(chain_ids) -> dict:
    import matplotlib.pyplot as plt

    cids = sorted(set(chain_ids))
    if len(cids) <= 10:
        cmap = plt.get_cmap("tab10")
        return {c: cmap(i % 10) for i, c in enumerate(cids)}
    if len(cids) <= 20:
        cmap = plt.get_cmap("tab20")
        return {c: cmap(i % 20) for i, c in enumerate(cids)}
    cmap = plt.get_cmap("viridis")
    return {c: cmap(i / max(1, len(cids) - 1)) for i, c in enumerate(cids)}


# ---------------------------------------------------------------------------
# Plot input (decoupled from RunState)
# ---------------------------------------------------------------------------

def objective_options(run) -> list[tuple[str, str]]:
    """Available (column, label) objective series for a run, best-first.

    The observation log-likelihood is the data-fit signal and the default:
    ``obs_ll`` = log p(y|x,θ) for PGAS; for MH/PMMH the bare ``log_likelihood``
    already *is* p(y|θ) (no latent path). The complete-data ``log_posterior`` is
    offered too, but for PGAS it's dominated by the resampled trajectory."""
    aux: set[str] = set()
    for buf in run.chains.values():
        aux |= set(buf.aux)
    opts: list[tuple[str, str]] = []
    if "obs_ll" in aux:
        opts.append(("obs_ll", "observation log-lik  p(y|x,·)"))
    elif "log_likelihood" in aux:
        opts.append(("log_likelihood", "observation log-lik  p(y|·)"))
    opts.append(("log_posterior", f"log-posterior ({run.meta.backend.logpost_label})"))
    if "transition_ll" in aux:
        opts.append(("transition_ll", "transition log-lik  p(x|·)"))
    return opts


def resolve_objective(run, objective: str | None) -> tuple[str, str]:
    """(column, label) for the requested objective column, or the default
    (first / observation log-lik) when ``objective`` is None or unavailable."""
    opts = objective_options(run)
    keys = [k for k, _ in opts]
    col = objective if objective in keys else (keys[0] if keys else "log_posterior")
    return col, dict(opts).get(col, col)


def resolve_objectives(run, objectives: list[str] | None) -> list[str]:
    """The requested objective columns in canonical (best-first) order, falling
    back to just the primary (observation log-lik) when none are valid."""
    keys = [k for k, _ in objective_options(run)]
    chosen = [k for k in keys if objectives and k in objectives]
    return chosen or keys[:1]


def objective_series(run, buf, col: str) -> np.ndarray | None:
    """One chain's objective series. Reconstructs ``log_posterior`` from
    ``log_likelihood`` + priors only when that column is absent."""
    from .ingest import log_prior_density

    if col in buf.aux:
        return buf.aux[col]
    if col == "log_posterior" and "log_likelihood" in buf.aux:
        y = buf.aux["log_likelihood"].copy()
        for p in run.params:
            if p in buf.values and p in run.priors:
                y = y + log_prior_density(run.priors[p], buf.values[p])
        return y
    return None


@dataclass
class PlotData:
    """Per-chain, post-warmup arrays ready to plot.

    ``chains[cid][col]`` -> 1-D array. ``col`` covers each param plus each
    objective column (keyed by its own name, e.g. ``obs_ll``). ``objectives``
    lists those objective keys (in order, each gets a pair-plot row); the
    ``objective_labels`` map gives their axis labels.
    """

    chains: dict[int, dict[str, np.ndarray]]
    params: list[str]
    priors: dict[str, PriorSpec]
    iters: dict[int, np.ndarray]  # cid -> iteration index (full, pre-warmup)
    objectives: list[str] = field(default_factory=list)
    objective_labels: dict[str, str] = field(default_factory=dict)


def build_plot_data(
    run, warmup: int, params: list[str] | None = None, objectives: list[str] | None = None
) -> PlotData:
    """Assemble a :class:`PlotData` from a RunState, selecting the post-warmup
    tail. Each objective in ``objectives`` (default: just the primary,
    observation log-lik) becomes its own keyed series and pair-plot row;
    ``log_posterior`` is reconstructed only when the trace lacks it.

    ``params`` restricts which estimated coordinates are kept for plotting (the
    UI passes the user-selected subset); ``None`` keeps all of ``run.params``.
    """
    selected = list(run.params) if params is None else [p for p in run.params if p in set(params)]
    obj_cols = resolve_objectives(run, objectives)
    labels = {c: lbl for c, lbl in objective_options(run) if c in set(obj_cols)}

    chains: dict[int, dict[str, np.ndarray]] = {}
    iters: dict[int, np.ndarray] = {}
    for cid in sorted(run.chains):
        buf = run.chains[cid]
        if buf.n == 0:
            continue
        mask = buf.iters >= warmup
        d: dict[str, np.ndarray] = {}
        for p in selected:
            if p in buf.values:
                d[p] = buf.values[p][mask]
        for col in obj_cols:
            series = objective_series(run, buf, col)
            if series is not None:
                d[col] = series[mask]
        if d:
            chains[cid] = d
            iters[cid] = buf.iters[mask]
    return PlotData(
        chains=chains,
        params=selected,
        priors=dict(run.priors),
        iters=iters,
        objectives=obj_cols,
        objective_labels=labels,
    )


# ---------------------------------------------------------------------------
# Enhanced pair plot
# ---------------------------------------------------------------------------

def _prior_central_interval(spec: PriorSpec, draws: np.ndarray, q: float = 0.005) -> tuple[float, float] | None:
    """Central (1-2q) interval of the prior — used to widen x-limits in
    "show prior breadth" mode without letting fat tails blow up the axis."""
    if draws.size:
        return float(np.quantile(draws, q)), float(np.quantile(draws, 1 - q))
    if spec.bounds is not None:
        return spec.bounds
    return None


def _dim_limit(
    vals_all: np.ndarray,
    spec: PriorSpec | None,
    prior_draws: np.ndarray | None,
    prior_xlim_mode: str,
    *,
    is_logpost: bool,
) -> tuple[float, float]:
    """The single (xlo, xhi) limit for one dimension, reused as the column-x
    and (off-diagonal) row-y everywhere that dimension appears.

    "posterior" mode = the posterior data range with a small pad; "prior" mode =
    that range widened by the prior central interval (params only — logpost has
    no prior). Mirrors the per-cell logic that previously lived in
    ``_draw_diagonal``."""
    if vals_all.size == 0:
        return (0.0, 1.0)
    post_lo, post_hi = float(vals_all.min()), float(vals_all.max())
    if post_hi - post_lo < 1e-9:
        pad = max(abs(post_lo) * 0.01, 1e-6)
        post_lo, post_hi = post_lo - pad, post_hi + pad

    draw_prior = (not is_logpost) and spec is not None and prior_draws is not None
    if draw_prior and prior_xlim_mode == "prior" and prior_draws.size:
        pi = _prior_central_interval(spec, prior_draws)
        if pi is not None:
            lo = min(post_lo, pi[0])
            hi = max(post_hi, pi[1])
        else:
            lo, hi = post_lo, post_hi
    else:
        lo, hi = post_lo, post_hi
    pad = 0.05 * (hi - lo) if hi > lo else 1.0
    return (lo - pad, hi + pad)


def enhanced_pair_plot(
    data: PlotData,
    *,
    prior_xlim_mode: str = "posterior",   # "prior" (show breadth) | "posterior" (fit)
    n_prior: int = 10_000,
    point_size: float = 3.0,
    chain_alpha: float = 0.55,
    hist_alpha: float = 0.5,
    title: str = "",
    max_params: int = 24,
) -> Figure:
    """Enhanced pair plot. See module docstring for the layout.

    Grid is ``m x m`` for ``m = n_params + n_objectives``. The ``n`` params form
    the usual lower-triangle scatter + diagonal-histogram matrix; each objective
    adds a bottom **row** of ``param_j`` (x) vs ``objective`` (y) scatters and a
    diagonal marginal. The objective *columns* (incl. objective×objective) are
    blank — only param columns carry scatters — so extra objectives never add
    clutter. The top-right empty cell carries the chain legend.
    """
    import matplotlib.pyplot as plt

    params = list(data.params)
    if len(params) > max_params:
        params = params[:max_params]
    n = len(params)
    objectives = list(data.objectives)
    dims = params + objectives
    obj_set = set(objectives)
    m = len(dims)  # grid side length

    chain_ids = sorted(data.chains)
    colors = chain_color_palette(chain_ids)

    # Pre-sample priors once (deterministic).
    rng = np.random.default_rng(0)
    prior_draws: dict[str, np.ndarray] = {}
    for p in params:
        spec = data.priors.get(p)
        prior_draws[p] = sample_prior(spec, n_prior, rng) if spec is not None else np.empty(0)

    def col(cid, name):
        return data.chains[cid].get(name, np.empty(0))

    def _finite_concat(name):
        vals = [col(c, name) for c in chain_ids]
        v = np.concatenate(vals) if vals else np.empty(0)
        return v[np.isfinite(v)]

    def _label(name):
        return data.objective_labels.get(name, name)

    # ONE limit per dimension — computed once, then reused as the column-x AND
    # (off-diagonal) row-y everywhere the dimension appears, so a parameter's
    # axis is identical across the whole grid (a proper pair plot).
    lim: dict[str, tuple[float, float]] = {}
    for d in dims:
        lim[d] = _dim_limit(
            _finite_concat(d),
            data.priors.get(d),
            prior_draws.get(d),
            prior_xlim_mode,
            is_logpost=(d in obj_set),
        )

    # Square figure (1:1) — width == height — so each cell is itself ~square.
    fig_size = (1.9 * m + 1, 1.9 * m + 1)
    fig, axes = plt.subplots(m, m, figsize=fig_size, squeeze=False)

    for i, p_y in enumerate(dims):
        for j, p_x in enumerate(dims):
            ax = axes[i, j]
            is_diag = i == j
            # Scatter ONLY where the column is a parameter: that's the
            # param×param lower triangle plus each objective row's param cells.
            # The upper triangle and every objective column (incl.
            # objective×objective) stay blank — save diagonals and the legend.
            if is_diag:
                _draw_diagonal(
                    ax, p_y, chain_ids, colors, col, _finite_concat,
                    prior_draws.get(p_y), data.priors.get(p_y),
                    lim[p_y], hist_alpha,
                    is_logpost=(p_y in obj_set),
                )
            elif i > j and p_x not in obj_set:
                _draw_scatter(
                    ax, p_x, p_y, chain_ids, colors, col, point_size, chain_alpha,
                    xlim=lim[p_x], ylim=lim[p_y],
                )
            else:
                ax.set_visible(False)
                continue

            # Edge labels.
            if i == m - 1:
                ax.set_xlabel(_label(p_x), fontsize=8)
                # Rotate the numeric x-tick labels on the bottom row so long
                # values don't collide / get clipped at the figure edge.
                for t in ax.get_xticklabels():
                    t.set_rotation(45)
                    t.set_ha("right")
                    t.set_rotation_mode("anchor")
            else:
                ax.set_xticklabels([])
            if j == 0:
                ax.set_ylabel(_label(p_y), fontsize=8)
            else:
                ax.set_yticklabels([])
            ax.tick_params(labelsize=6)

    # Legend in the top-right cell.
    legend_ax = axes[0, m - 1]
    legend_ax.set_visible(True)
    legend_ax.axis("off")
    handles = [
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=colors[c],
                   markersize=6, label=f"chain {c}")
        for c in chain_ids
    ]
    handles.append(
        plt.Line2D([0], [0], marker="s", color="w", markerfacecolor="#bbbbbb",
                   markersize=8, label="prior")
    )
    legend_ax.legend(handles=handles, frameon=False, fontsize=7, loc="center",
                     ncol=2 if len(chain_ids) > 6 else 1)

    if title:
        fig.suptitle(title, fontsize=11)
        # Reserve top space for the suptitle and bottom space for the rotated
        # x-tick labels so nothing is clipped at the figure edges.
        fig.tight_layout(rect=(0, 0.0, 1, 0.97))
    else:
        fig.tight_layout()
    return fig


def _draw_diagonal(ax, name, chain_ids, colors, col, finite_concat, prior_draws,
                   spec, xlim, hist_alpha, *, is_logpost):
    vals_all = finite_concat(name)
    if vals_all.size == 0:
        ax.set_visible(False)
        return

    # x-limit is the dimension's shared limit (computed once in the caller). The
    # prior band still only renders for params (not logpost).
    draw_prior = (not is_logpost) and spec is not None and prior_draws is not None
    xlo, xhi = xlim

    bins = np.linspace(xlo, xhi, 30)

    # Prior overlay BEHIND (zorder 0), density-normalized, light gray.
    if draw_prior:
        if prior_draws.size:
            pd_clip = prior_draws[(prior_draws >= xlo) & (prior_draws <= xhi)]
            if pd_clip.size:
                ax.hist(pd_clip, bins=bins, density=True, color="#cccccc",
                        alpha=0.9, histtype="stepfilled", edgecolor="#999999",
                        linewidth=0.6, zorder=0)
        elif spec.bounds is not None:
            # Flat / bounds-only: uniform gray band across the bounds∩view.
            blo, bhi = spec.bounds
            blo, bhi = max(blo, xlo), min(bhi, xhi)
            if bhi > blo:
                height = 1.0 / (bhi - blo)
                ax.fill_between([blo, bhi], 0, height, color="#cccccc",
                                alpha=0.9, edgecolor="#999999", linewidth=0.6,
                                zorder=0)

    # Per-chain posterior histograms (density-normalized so they sit on the
    # same scale as the prior overlay).
    for c in chain_ids:
        sub = col(c, name)
        sub = sub[np.isfinite(sub)]
        if sub.size:
            ax.hist(sub, bins=bins, density=True, color=colors[c],
                    alpha=hist_alpha, edgecolor="none", zorder=2)
    ax.set_xlim(xlo, xhi)
    ax.set_yticks([])


def _draw_scatter(ax, p_x, p_y, chain_ids, colors, col, point_size, chain_alpha,
                  *, xlim, ylim):
    for c in chain_ids:
        x = col(c, p_x)
        y = col(c, p_y)
        m = np.isfinite(x) & np.isfinite(y)
        if m.any():
            ax.scatter(x[m], y[m], color=colors[c], s=point_size,
                       alpha=chain_alpha, edgecolor="none")
    # Shared limits: x = lim[dim_j] (column), y = lim[dim_i] (row) — so every
    # cell in a column shares x and every off-diagonal cell in a row shares y.
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)


# ---------------------------------------------------------------------------
# Trace grid
# ---------------------------------------------------------------------------

def _decimate(x: np.ndarray, y: np.ndarray, max_pts: int) -> tuple[np.ndarray, np.ndarray]:
    if x.shape[0] <= max_pts:
        return x, y
    idx = np.linspace(0, x.shape[0] - 1, max_pts).astype(int)
    return x[idx], y[idx]


def trace_grid(
    run,
    *,
    warmup: int | None = None,
    ncols: int = 3,
    max_pts: int = 5000,
    title: str | None = None,
    max_params: int = 24,
    params: list[str] | None = None,
    objectives: list[str] | None = None,
) -> Figure:
    """Per-parameter + one-panel-per-objective trace facets, all chains
    overlaid, decimated to ``max_pts`` per panel, with the warm-up region shaded.

    ``params`` restricts which coordinates get a panel (the UI passes the
    user-selected subset); ``None`` shows all of ``run.params``. ``objectives``
    is the list of objective columns to panel (default: just the primary,
    observation log-lik)."""
    import matplotlib.pyplot as plt

    selected = list(run.params) if params is None else [p for p in run.params if p in set(params)]
    panel_params = selected[:max_params] if len(selected) > max_params else selected
    obj_cols = resolve_objectives(run, objectives)
    obj_labels = dict(objective_options(run))
    obj_set = set(obj_cols)
    panels = panel_params + obj_cols
    n = len(panels)
    ncols = min(ncols, n)
    nrows = (n + ncols - 1) // ncols
    # Panels ~3.6 wide x 2.6 tall (~1.4:1) — wide enough to read a trace, but
    # not extremely stretched.
    fig, axes_arr = plt.subplots(nrows, ncols, figsize=(3.6 * ncols, 2.6 * nrows + 0.8),
                                 squeeze=False)
    axes = axes_arr.ravel()
    chain_ids = sorted(run.chains)
    colors = chain_color_palette(chain_ids)

    for ax in axes[n:]:
        ax.set_visible(False)

    for ax, name in zip(axes, panels):
        is_obj = name in obj_set
        for cid in chain_ids:
            buf = run.chains[cid]
            if buf.n == 0:
                continue
            it = buf.iters.astype(float)
            if is_obj:
                y = objective_series(run, buf, name)
                if y is None:
                    continue
            elif name in buf.values:
                y = buf.values[name]
            else:
                continue
            xx, yy = _decimate(it, y, max_pts)
            ax.plot(xx, yy, color=colors[cid], linewidth=0.7, alpha=0.85)
        if warmup is not None:
            lo = run.min_iter()
            if lo is not None and warmup > lo:
                ax.axvspan(lo, warmup, color="black", alpha=0.06, zorder=0)
        ax.set_title(obj_labels.get(name, name) if is_obj else name, fontsize=9)
        ax.tick_params(labelsize=7)
        ax.grid(alpha=0.25)
        ax.set_xlabel("iteration", fontsize=8)

    handles = [plt.Line2D([0], [0], color=colors[c], linewidth=1.5, label=f"chain {c}")
               for c in chain_ids]
    # Reserve a bottom band (rect bottom = 0.06) for both the "iteration"
    # x-labels and the legend, so neither gets clipped at the figure edge.
    if title:
        fig.suptitle(title, fontsize=11)
        fig.tight_layout(rect=(0, 0.06, 1, 0.96))
    else:
        fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.legend(handles=handles, loc="lower center", ncol=min(len(handles), 8),
               frameon=False, fontsize=8, bbox_to_anchor=(0.5, 0.0))
    return fig


# ---------------------------------------------------------------------------
# Chain-health figures (camdl telemetry: per-chain mixing + per-chain ESS)
# ---------------------------------------------------------------------------

def mixing_bars(
    values: list[float],
    labels: list[str],
    *,
    xlabel: str,
    band: tuple[float, float] | None = (0.15, 0.50),
    title: str = "",
) -> Figure:
    """Horizontal per-chain bars (acceptance / trajectory-renewal) in [0, 1],
    one per chain, with an optional shaded *healthy band*. A value's label is
    drawn in green inside the band and red outside, so a too-sticky (high
    acceptance) or too-jumpy chain is obvious at a glance. ``band=None`` (e.g.
    PGAS trajectory renewal, which has no universal target) skips the shading.
    """
    import matplotlib.pyplot as plt

    n = max(len(values), 1)
    fig, ax = plt.subplots(figsize=(5.2, 0.46 * n + 1.0))
    colors = chain_color_palette(list(range(n)))
    y = np.arange(len(values))[::-1]  # chain 0 at the top

    if band is not None:
        ax.axvspan(band[0], band[1], color="#27ae60", alpha=0.12, zorder=0)
        for b in band:
            ax.axvline(b, color="#27ae60", linewidth=0.8, alpha=0.5, zorder=1)

    for i, (yy, v) in enumerate(zip(y, values)):
        ax.barh(yy, v, color=colors[i], alpha=0.85, height=0.62, zorder=2)
        healthy = band is None or (band[0] <= v <= band[1])
        ax.text(
            min(v + 0.012, 0.995), yy, f"{v:.0%}",
            va="center", ha="left", fontsize=8,
            color=("#333333" if band is None else ("#1e8449" if healthy else "#c0392b")),
            fontweight="bold" if (band is not None and not healthy) else "normal",
        )
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlim(0, 1)
    ax.set_xlabel(xlabel, fontsize=9)
    if title:
        ax.set_title(title, fontsize=10)
    ax.grid(axis="x", alpha=0.2)
    fig.tight_layout()
    return fig


def ess_heatmap(
    ess_per_chain: dict[str, list[float]],
    *,
    params: list[str] | None = None,
    healthy_ess: float = 400.0,
    max_params: int = 40,
    title: str = "",
) -> Figure:
    """Param × chain effective-sample-size heatmap (red = low, green ≥
    ``healthy_ess``), annotated with the raw counts. Surfaces *which chain*
    drags a parameter's ESS down — invisible in the combined number. ``params``
    restricts/orders the rows to the user's selection."""
    import matplotlib.pyplot as plt

    keys = [p for p in (params or list(ess_per_chain)) if p in ess_per_chain and ess_per_chain[p]]
    keys = keys[:max_params]
    if not keys:
        fig, ax = plt.subplots(figsize=(4, 1.2))
        ax.text(0.5, 0.5, "no per-chain ESS", ha="center", va="center", color="#999")
        ax.axis("off")
        return fig

    mat = np.array([ess_per_chain[p] for p in keys], dtype=float)  # (n_param, n_chain)
    nrow, ncol = mat.shape
    fig, ax = plt.subplots(figsize=(0.78 * ncol + 2.4, 0.34 * nrow + 1.2))
    # Color encodes "fraction of healthy": ESS ≥ healthy_ess saturates green.
    im = ax.imshow(mat, aspect="auto", cmap="RdYlGn", vmin=0.0, vmax=healthy_ess)
    ax.set_xticks(range(ncol))
    ax.set_xticklabels([f"c{j}" for j in range(ncol)], fontsize=8)
    ax.set_yticks(range(nrow))
    ax.set_yticklabels(keys, fontsize=7)
    for i in range(nrow):
        for j in range(ncol):
            ax.text(j, i, f"{mat[i, j]:.0f}", ha="center", va="center",
                    fontsize=6, color="#222222")
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.set_label(f"ESS (≥{healthy_ess:.0f} = green)", fontsize=8)
    cb.ax.tick_params(labelsize=7)
    if title:
        ax.set_title(title, fontsize=10)
    fig.tight_layout()
    return fig
