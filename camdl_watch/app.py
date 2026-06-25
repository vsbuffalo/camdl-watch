"""camdl-watch — the Shiny dashboard (Layer 3: a projection of state).

Thin. A ``reactive.poll`` heartbeat drives discovery + incremental tailing of
the run store; everything else renders the resulting RunState / Diagnostics.

The UI:

* a run selector at the top (full-width, mobile-friendly), searchable by model
  stem, config, algorithm, and run-id hash;
* **Pair plot** and **Traces** tabs, rendered as inline SVG (dense scatter
  artists rasterized) so a phone can pinch-zoom into any panel and stay crisp,
  each with a subtle clean-PNG download link;
* a **Diagnostics** tab — camdl's authoritative end-of-stage telemetry: the
  aggregated verdict (R̂ / acceptance / max-tree-depth findings), per-chain
  mixing bars with a healthy band, a per-chain ESS heatmap, and the
  R̂/ESS/per-chain-ESS table;
* a **Source** tab — the syntax-highlighted ``.camdl`` model and ``fit.toml``;
* a shared **diagnostics** panel below every tab, always visible: camdl's
  verdict strip (when the stage has finished) over the watcher's live arviz
  read (warnings + per-parameter table). Authoritative numbers supersede the
  live estimate the moment camdl writes its summary.

Run from your camdl project root::

    uv run shiny run camdl_watch.app:app --port 8804 --host 127.0.0.1

Store dir is read from the ``CAMDL_WATCH_STORE`` env var, else defaults to
``results/fits`` under the current working directory.
"""

from __future__ import annotations

import html
import os
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import numpy as np
from shiny import App, reactive, render, ui

from . import diagnostics as diag_mod
from . import ingest
from . import plots
from .grouping import ParamGroups, group_params
from .state import ChainBuffer, RunState, Severity, Status
from .highlight import HIGHLIGHT_CSS, highlight_camdl, highlight_toml
from .sources import read_run_sources
from .svg_render import fig_to_png, fig_to_svg

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Default store: ``results/fits`` under the directory you launch from (your
# camdl project root). Override with the ``CAMDL_WATCH_STORE`` env var to point
# anywhere.
_DEFAULT_STORE = Path.cwd() / "results" / "fits"
STORE = Path(os.environ.get("CAMDL_WATCH_STORE", str(_DEFAULT_STORE)))

POLL_MS = 10000  # 10s heartbeat — keep the dashboard light under CPU contention

_STATUS_COLOR = {
    "running": "#e67e22", "warming": "#2980b9", "done": "#27ae60",
    "failed": "#c0392b", "stalled": "#7f8c8d",
}

# selectize.js render: the option label is already-built HTML (a colored
# `[status]` span + grey model stem), injected raw so it stays styled in both
# the dropdown options and the selected item.
_RUN_OPTION_RENDER = (
    "{"
    "  option: function(data, escape) {"
    "    return '<div class=\"option\">' + data.label + '</div>';"
    "  },"
    "  item: function(data, escape) {"
    "    return '<div class=\"item\">' + data.label + '</div>';"
    "  }"
    "}"
)

_CSS = """
.run-bar { margin: 0.25rem 0 0.75rem; }
.svg-wrap { width: 100%; overflow-x: auto; }
.svg-wrap svg { width: 100%; height: auto; display: block; }
.diag-section { margin-top: 0.75rem; }
.diag-section .shiny-data-frame { overflow-x: auto; }
.fig-dl { font-size: 0.8rem; color: #999; margin: 0.1rem 0 0.4rem; }
.fig-dl a { color: #777; text-decoration: underline; }
.src-block .codehl { border: 1px solid #eee; border-radius: 4px;
                     background: #fafafa; overflow-x: auto; }
.src-block .codehl pre { margin: 0; padding: .6rem .8rem; font-size: .8rem;
                         line-height: 1.45;
                         font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.src-section { margin: 0 0 1rem; }
.src-head { display: flex; align-items: center; gap: .6rem; margin: .3rem 0 .15rem; }
.src-title { font-weight: 600; }
.src-sub { font-size: .78rem; color: #999; margin: 0 0 .25rem; }
.src-missing { color: #c0392b; margin: .25rem 0; }
.copy-btn { font-size: .72rem; color: #555; background: #f3f3f3; border: 1px solid #ddd;
            border-radius: 4px; padding: .1rem .5rem; cursor: pointer; line-height: 1.4; }
.copy-btn:hover { background: #e9e9e9; }
.app-home { color: inherit; text-decoration: none; cursor: pointer; }
.app-home:hover { text-decoration: underline; }
.auth-table { border-collapse: collapse; font-size: .82rem; margin: .1rem 0 .6rem; }
.auth-table th, .auth-table td { padding: .12rem .55rem; text-align: right;
                                 border-bottom: 1px solid #eee; white-space: nowrap; }
.auth-table th { color: #777; font-weight: 600; }
@media (max-width: 600px) { body { font-size: 0.95rem; } }
"""

# Clipboard copy for the Source-tab code blocks. navigator.clipboard only works
# in a secure context (https/localhost), and the dashboard is reached over plain
# http (Tailscale/LAN), so we fall back to the execCommand path there.
_COPY_JS = """
function camdlCopy(btn) {
  var section = btn.closest('.src-section');
  var block = section && section.querySelector('.codehl');
  if (!block) return;
  var text = block.innerText;
  var orig = btn.getAttribute('data-orig') || btn.textContent;
  btn.setAttribute('data-orig', orig);
  var done = function () {
    btn.textContent = 'copied ✓';
    setTimeout(function () { btn.textContent = orig; }, 1200);
  };
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(done, function () {});
  } else {
    var ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.top = '0'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.focus(); ta.select();
    try { document.execCommand('copy'); done(); } catch (e) {}
    document.body.removeChild(ta);
  }
}
"""

# ---------------------------------------------------------------------------
# Process-wide run registry (persists across reactive recomputes).
# ---------------------------------------------------------------------------

_RUNS: dict[str, RunState] = {}


def _refresh_registry() -> dict[str, RunState]:
    """Discover runs and tail-read any new rows into the registry."""
    metas = ingest.discover_runs(STORE, include_warming=True)
    now = time.time()
    seen: set[str] = set()
    for meta in metas:
        seen.add(meta.run_id)
        rs = _RUNS.get(meta.run_id)
        if rs is None:
            rs = RunState(meta=meta)
            for cid, path in meta.chain_paths.items():
                rs.chains[cid] = ChainBuffer(cid=cid, path=path)
            rs.priors = ingest.extract_priors(meta)
            _RUNS[meta.run_id] = rs
        elif rs.meta.posterior_dir != meta.posterior_dir:
            # The fit relaunched/resumed into a new stage dir — follow it, so
            # liveness/draws are read off the live stage, not the old one.
            rs.meta = meta
            rs.chains = {cid: ChainBuffer(cid=cid, path=path)
                         for cid, path in meta.chain_paths.items()}
            rs.updated_at = 0.0
            rs.last_growth_at = 0.0
        grew = 0
        max_mtime = rs.updated_at
        for buf in rs.chains.values():
            grew += ingest.tail_chain(buf)
            if buf.path.exists():
                max_mtime = max(max_mtime, buf.path.stat().st_mtime)
        if grew:
            rs.last_growth_at = now
        rs.updated_at = max_mtime
        rs.progress = ingest.read_progress(meta.posterior_dir)
        rs.summary = ingest.read_chain_summary(meta.posterior_dir)
        rs.status = _classify(rs, now)
    # Reconcile runs that dropped out of discovery. Two cases:
    #   * the run dir was pruned off disk (the user cleaning the store, camdl GC)
    #     -> a zombie: its buffers still hold frozen draws and a now-dead lock,
    #     so leaving it in would re-classify it as a stale "[done]" with no
    #     summary. Drop it so it leaves the dropdown.
    #   * the dir is still there but undiscoverable (a warming run whose sampler
    #     died with no draws) -> settle its status from the heartbeat/lock, and
    #     refresh the summary in case the stage just finished + got cleaned.
    gone = [rid for rid, rs in _RUNS.items()
            if rid not in seen and not rs.meta.run_dir.exists()]
    for rid in gone:
        del _RUNS[rid]
    for rid, rs in _RUNS.items():
        if rid in seen:
            continue
        rs.progress = ingest.read_progress(rs.meta.posterior_dir)
        rs.summary = ingest.read_chain_summary(rs.meta.posterior_dir)
        if rs.progress is not None or rs.status in (Status.RUNNING, Status.WARMING):
            rs.status = _classify(rs, now)
    return _RUNS


def _classify(rs: RunState, now: float) -> Status:
    """Status from camdl's progress.json heartbeat (gh#278) when present —
    its ``liveness()`` policy: terminal states win regardless of freshness; a
    ``running`` heartbeat is live if fresh, else presumed dead. Falls back to
    the `.lock` PID + draws for runs that predate the heartbeat.
    """
    prog = rs.progress
    if prog is not None:
        if prog.state == "done":
            return Status.DONE
        if prog.state == "failed":
            return Status.FAILED
        if prog.state == "running":
            if not ingest.progress_is_fresh(prog, now):
                return Status.STALLED  # heartbeat stale -> presumed dead / hung
            return Status.WARMING if prog.phase == "burn_in" else Status.RUNNING
        return Status.DONE
    # No heartbeat: liveness from the `.lock` PID, never trace mtime (a slow
    # PGAS sweep can be minutes; staleness != done).
    live = ingest.stage_is_live(rs.meta.posterior_dir)
    has_draws = any(buf.n for buf in rs.chains.values())
    if has_draws:
        return Status.RUNNING if live else Status.DONE
    # No draws and the process is gone: a completed fit always writes draws, so
    # zero-draws-and-dead means it died/was killed in burn-in — not "done".
    return Status.WARMING if live else Status.STALLED


def _store_signature() -> tuple:
    """Cheap signature driving ``reactive.poll``: per-chain (path, size, mtime)
    plus each ``progress.json`` (path, mtime). The heartbeat lets us refresh
    burn-in progress and liveness even while the trace isn't growing."""
    sig = []
    if not STORE.is_dir():
        return ()
    for run_dir in sorted(STORE.iterdir()):
        if not run_dir.is_dir():
            continue
        for tp in run_dir.glob("[0-9]*-posterior-*/seed_*/chain_*/trace.tsv"):
            try:
                st = tp.stat()
                sig.append((str(tp), st.st_size, int(st.st_mtime)))
            except OSError:
                continue
        for pp in run_dir.glob("[0-9]*-posterior-*/seed_*/progress.json"):
            try:
                sig.append((str(pp), int(pp.stat().st_mtime)))
            except OSError:
                continue
    return tuple(sig)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.output_ui("store_info"),
        ui.hr(),
        ui.input_slider("warmup_pct", "Warm-up cutoff (% of sweeps)", 0, 95, 50, step=5),
        ui.output_ui("warmup_info"),
        ui.input_radio_buttons(
            "prior_xlim", "Pair-plot prior x-limits",
            {"prior": "show prior breadth", "posterior": "fit to posterior"},
            selected="posterior",
        ),
        ui.input_numeric("bulk_thresh", "bulk-ESS warn threshold", 400, min=1, step=50),
        ui.output_ui("objective_select"),  # its own hr-bounded section (when present)
        ui.hr(),
        ui.output_ui("param_select"),
        width=320,
        title="Controls",
        open="desktop",  # open on desktop (like the old app), collapsed on mobile
    ),
    ui.head_content(
        ui.tags.meta(name="viewport", content="width=device-width, initial-scale=1"),
        ui.tags.style(HIGHLIGHT_CSS),
        ui.tags.style(_CSS),
        ui.tags.script(_COPY_JS),
    ),
    # Top bar: run selector (full-width, clean on mobile) + compact badge. The
    # dropdown searches the model stem too (see _update_choices), so model-name
    # lookups work even though the visible label is the config stem.
    ui.div(
        ui.input_selectize(
            "run_id", "Run", choices={}, width="100%",
            options={
                "render": ui.js_eval(_RUN_OPTION_RENDER),
                "searchField": ["label", "value"],
            },
        ),
        ui.output_ui("run_badge"),
        class_="run-bar",
    ),
    ui.navset_tab(
        ui.nav_panel(
            "Pair plot",
            ui.output_ui("pair_svg"),
            ui.div("[ ", ui.download_link("dl_pair", "download PNG"), " ]", class_="fig-dl"),
        ),
        ui.nav_panel(
            "Traces",
            ui.output_ui("trace_svg"),
            ui.div("[ ", ui.download_link("dl_trace", "download PNG"), " ]", class_="fig-dl"),
        ),
        ui.nav_panel(
            "Diagnostics",
            ui.output_ui("diag_tab"),
        ),
        ui.nav_panel("Source", ui.output_ui("source_view")),
        id="active_tab",
    ),
    # Diagnostics summary: shared below every tab, always visible. camdl's
    # authoritative verdict (when the stage has finished) sits above the
    # watcher's live arviz read.
    ui.div(
        ui.hr(),
        ui.h5("Diagnostics", style="margin-bottom:0.4rem"),
        ui.output_ui("verdict_strip"),
        ui.output_ui("warnings_panel"),
        ui.output_ui("diag_source_note"),
        ui.output_data_frame("diag_table"),
        class_="diag-section",
    ),
    title=ui.tags.a(
        "camdl-watch", href="./", class_="app-home",
        title="reload — back to the default view",
    ),
)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

def server(input, output, session):
    @reactive.poll(lambda: _store_signature(), POLL_MS)
    def store_tick():
        _refresh_registry()
        return time.time()

    @reactive.calc
    def runs():
        store_tick()
        return dict(_RUNS)

    @reactive.effect
    def _update_choices():
        rs = runs()
        ordered = sorted(rs.items(), key=lambda kv: kv[1].updated_at, reverse=True)
        # The label carries a grey model stem so the dropdown's text search
        # matches model names (searchField=["label","value"]); "value" is the
        # run_id, so hash search works too.
        choices = {
            rid: (
                f"{r.meta.display_label} "
                f"<span style='color:#aaa;font-size:0.85em'>· {r.meta.model}</span> "
                f"<span style='color:{_STATUS_COLOR.get(r.status.value, '#888')};"
                f"font-weight:600'>[{r.status.value}]</span>"
            )
            for rid, r in ordered
        }
        if choices:
            sel = input.run_id() if input.run_id() in choices else next(iter(choices))
            ui.update_selectize("run_id", choices=choices, selected=sel)

    @reactive.calc
    def current() -> RunState | None:
        rs = runs()
        rid = input.run_id()
        return rs.get(rid) or (next(iter(rs.values())) if rs else None)

    # ---- parameter selection / grouping -----------------------------------

    @reactive.calc
    def current_groups() -> tuple[str, ParamGroups] | None:
        run = current()
        if run is None:
            return None
        return run.meta.run_id, group_params(list(run.params))

    def _objectives(run: RunState) -> list[str]:
        """Selected objective columns, canonical order; defaults to the primary
        (observation log-lik). Each gets a trace panel and a pair-plot row."""
        sel = input.objectives() if "objectives" in input else None
        return plots.resolve_objectives(run, list(sel) if sel else None)

    @render.ui
    def objective_select():
        # The pair/trace objective axis. Defaults to the observation
        # log-likelihood (the data-fit signal) over the complete-data
        # log-posterior — which for PGAS is dominated by the resampled path.
        # Multi-select: each checked series gets its own trace panel; the pair
        # plot uses the first (primary).
        run = current()
        if run is None:
            return None
        opts = plots.objective_options(run)
        if len(opts) <= 1:
            return None  # nothing to choose (e.g. a warming run with no draws)
        choices = {k: lbl for k, lbl in opts}
        cur = input.objectives() if "objectives" in input else None
        sel = [k for k in choices if cur and k in cur] or [next(iter(choices))]
        return ui.div(
            ui.hr(),
            ui.h6("Objective axis", style="margin:.2rem 0 .35rem"),
            ui.input_checkbox_group("objectives", None, choices=choices, selected=sel),
        )

    @render.ui
    def param_select():
        cg = current_groups()
        if cg is None:
            return ui.p("no params")
        _run_id, groups = cg
        blocks: list = [ui.h5("Parameters", style="margin-bottom:0.25em")]
        if groups.scalars:
            blocks.append(
                ui.input_checkbox_group(
                    "sel_scalars",
                    ui.span("scalars / hyperparameters", style="font-weight:600"),
                    choices={p: p for p in groups.scalars},
                    selected=list(groups.scalars),
                )
            )
        for base, members in groups.families.items():
            cb = ui.input_checkbox_group(
                f"fam_{base}", None,
                choices={m: m.removeprefix(base + "_") for m in members},
                selected=[],
            )
            # `fam_all_<base>` is the master toggle: checked -> the whole family
            # is included (overriding individual leaves); unchecked -> the
            # individual picks below apply. Individual picks persist, so toggling
            # all on then off restores them.
            blocks.append(
                ui.div(
                    ui.input_checkbox(
                        f"fam_all_{base}",
                        ui.span(
                            ui.span(base, style="font-weight:600"),
                            ui.span(f"  (all {len(members)})", style="color:#888"),
                        ),
                        value=False,
                    ),
                    ui.tags.details(
                        ui.tags.summary(
                            ui.span("individual leaves", style="color:#888;font-size:0.85em"),
                            style="cursor:pointer",
                        ),
                        ui.div(cb, style="margin-left:1em;margin-top:0.25em"),
                        style="margin:0.1em 0 0 1.4em",
                    ),
                    style="margin:0.35em 0",
                )
            )
        return ui.div(*blocks)

    @reactive.calc
    def selected_params() -> list[str]:
        run = current()
        cg = current_groups()
        if run is None or cg is None:
            return []
        _run_id, groups = cg
        chosen: set[str] = set()
        if groups.scalars:
            sc = input.sel_scalars() if "sel_scalars" in input else None
            chosen.update(sc if sc is not None else groups.scalars)
        for base, members in groups.families.items():
            all_on = input[f"fam_all_{base}"]() if f"fam_all_{base}" in input else False
            if all_on:  # master toggle wins over individual leaves
                chosen.update(members)
                continue
            picked = input[f"fam_{base}"]() if f"fam_{base}" in input else None
            if picked:
                chosen.update(picked)
        if not chosen:
            chosen.update(groups.default_selection())
        return [p for p in run.params if p in chosen]

    def _warmup_cutoff(run: RunState) -> int:
        lo = run.min_iter() or 0
        hi = run.max_iter() or lo
        return int(lo + (hi - lo) * input.warmup_pct() / 100.0)

    @reactive.calc
    def diagnostics():
        run = current()
        if run is None:
            return None
        return diag_mod.compute_diagnostics(run, _warmup_cutoff(run), params=selected_params())

    # ---- renders -----------------------------------------------------------

    @render.ui
    def store_info():
        return ui.markdown(f"**Store:** `{STORE}`  \n**Runs:** {len(runs())}")

    @render.ui
    def run_badge():
        run = current()
        if run is None:
            return ui.p("no runs found", style="color:#999")
        m = run.meta
        color = _STATUS_COLOR.get(run.status.value, "#888")
        prog = _progress_blurb(run)
        return ui.HTML(
            f"<div style='font-size:0.85em;color:#444'>"
            f"<span style='color:{color};font-weight:700'>[{run.status.value}]</span> "
            f"&nbsp;<b>{m.algorithm}/{m.backend.value}</b> "
            f"&nbsp;·&nbsp; {len(run.chains)} chains "
            f"&nbsp;·&nbsp; {prog}<br>"
            f"<span style='color:#777'>model:</span> {m.model} "
            f"&nbsp;·&nbsp; <code style='font-size:0.9em;color:#888'>{m.run_id}</code>"
            f"</div>"
        )

    @render.ui
    def warmup_info():
        run = current()
        if run is None:
            return ui.p("")
        return ui.markdown(f"cutoff at sweep **{_warmup_cutoff(run)}**")

    @render.ui
    def pair_svg():
        if input.active_tab() != "Pair plot":  # one SVG in the DOM at a time
            return None
        store_tick()  # refresh with new data while this tab is visible
        run = current()
        if run is None or not run.chains:
            return ui.p("no data yet", style="color:#999")
        if run.max_iter() is None:  # warming up: no draws to plot yet
            return _warming_notice(run)
        warmup = _warmup_cutoff(run)
        pdata = plots.build_plot_data(run, warmup, params=selected_params(),
                                      objectives=_objectives(run))
        if not pdata.chains:
            return ui.p("no post-warmup draws yet", style="color:#999")
        fig = plots.enhanced_pair_plot(
            pdata,
            prior_xlim_mode=input.prior_xlim(),
            title=f"{run.meta.display_label} — post-warmup (sweep ≥ {warmup})",
        )
        return ui.HTML(f'<div class="svg-wrap">{fig_to_svg(fig, min_pts=50)}</div>')

    @render.ui
    def trace_svg():
        if input.active_tab() != "Traces":
            return None
        store_tick()
        run = current()
        if run is None or not run.chains:
            return ui.p("no data yet", style="color:#999")
        if run.max_iter() is None:  # warming up: no draws to plot yet
            return _warming_notice(run)
        warmup = _warmup_cutoff(run)
        fig = plots.trace_grid(
            run, warmup=warmup, title=run.meta.display_label,
            params=selected_params(), objectives=_objectives(run),
        )
        return ui.HTML(f'<div class="svg-wrap">{fig_to_svg(fig, min_pts=200)}</div>')

    @render.ui
    def source_view():
        if input.active_tab() != "Source":
            return None
        run = current()
        if run is None:
            return ui.p("no run selected", style="color:#999")
        src = read_run_sources(run.meta.run_dir)
        mp = html.escape(str(src.model_path)) if src.model_path else ""
        model = _source_section(
            f"model · {run.meta.model}.camdl",
            f"<code style='color:#777'>{mp}</code>"
            f" &nbsp;·&nbsp; read live from source (not stored in the CAS)",
            highlight_camdl(src.model_text) if src.model_text is not None else None,
            f"model source not found{(' at <code>' + mp + '</code>') if mp else ''}",
        )
        tp = html.escape(str(src.toml_path)) if src.toml_path else ""
        fit_toml = _source_section(
            "fit.toml",
            f"<code style='color:#777'>{tp}</code> &nbsp;·&nbsp; mirrored in the run store",
            highlight_toml(src.toml_text) if src.toml_text is not None else None,
            "fit.toml.original not found",
        )
        return ui.HTML(model + fit_toml)

    # ---- clean-PNG downloads (subtle links under each figure) --------------
    # Rebuilt fresh on click, honoring the current run / warm-up / param
    # selection — independent of the inline SVG renders above.

    def _run_slug() -> str:
        run = current()
        return run.meta.run_id if run else "run"

    @render.download(filename=lambda: f"pairplot_{_run_slug()}.png")
    def dl_pair():
        run = current()
        if run is None or not run.chains:
            return
        warmup = _warmup_cutoff(run)
        pdata = plots.build_plot_data(run, warmup, params=selected_params(),
                                      objectives=_objectives(run))
        if not pdata.chains:
            return
        fig = plots.enhanced_pair_plot(
            pdata,
            prior_xlim_mode=input.prior_xlim(),
            title=f"{run.meta.display_label} — post-warmup (sweep ≥ {warmup})",
        )
        yield fig_to_png(fig)

    @render.download(filename=lambda: f"traces_{_run_slug()}.png")
    def dl_trace():
        run = current()
        if run is None or not run.chains:
            return
        warmup = _warmup_cutoff(run)
        fig = plots.trace_grid(
            run, warmup=warmup, title=run.meta.display_label,
            params=selected_params(), objectives=_objectives(run),
        )
        yield fig_to_png(fig)

    @render.ui
    def warnings_panel():
        run = current()
        d = diagnostics()
        if run is None or d is None:
            return ui.p("no data yet", style="color:#999")
        ws = diag_mod.derive_warnings(
            d, run, bulk_ess_thresh=float(input.bulk_thresh()), summary=run.summary)
        colors = {"error": "#c0392b", "warn": "#e67e22", "info": "#16a085"}
        rows = []
        for w in ws:
            tag = f"[{w.param}] " if w.param else ""
            rows.append(
                f"<li style='color:{colors[w.severity.value]}'>"
                f"<b>{w.severity.value.upper()}</b> {tag}{w.message}</li>"
            )
        # MH reports an accept rate; PGAS has none — show its trajectory-renewal
        # rate (the mixing analog) instead of a bare "n/a".
        if d.acceptance is not None:
            acc = f"acceptance = {d.acceptance:.3f}"
        elif d.renewal is not None:
            acc = f"trajectory renewal = {d.renewal:.3f}"
        else:
            acc = "acceptance = n/a"
        plateau = {True: "plateaued", False: "NOT plateaued", None: "n/a"}[d.plateaued]
        return ui.HTML(
            f"<div style='margin-bottom:0.5em'><b>Post-warmup draws/chain:</b> {d.n_tail} "
            f"&nbsp;|&nbsp; {acc} &nbsp;|&nbsp; ll {plateau} "
            f"&nbsp;|&nbsp; logpost: {d.logpost_label}</div>"
            f"<ul style='margin-top:0'>{''.join(rows)}</ul>"
        )

    @render.ui
    def verdict_strip():
        run = current()
        if run is None:
            return None
        h = _verdict_block_html(run.summary)
        return ui.HTML(h) if h else None

    @render.ui
    def diag_source_note():
        # Where the table's R̂/ESS come from: camdl's authoritative stage summary
        # once it exists, else the watcher's live arviz estimate.
        run = current()
        if run is None:
            return None
        if run.summary is not None and run.summary.rhat:
            return ui.HTML(
                f"<div style='font-size:.8rem;color:#777;margin:.1rem 0 .3rem'>"
                f"R̂ &amp; ESS below are camdl's authoritative <b>{html.escape(run.summary.stage or 'stage')}</b> "
                f"values; mean/sd/tail-ESS/MCSE/sep remain the live arviz estimate.</div>")
        return ui.HTML(
            "<div style='font-size:.8rem;color:#777;margin:.1rem 0 .3rem'>"
            "Live arviz estimate (no camdl stage summary yet).</div>")

    @render.data_frame
    def diag_table():
        import polars as pl

        d = diagnostics()
        run = current()
        if d is None:
            return render.DataGrid(pl.DataFrame({"info": ["no data"]}))
        summ = run.summary if run is not None else None
        rows = []
        for p, pd in d.per_param.items():
            rhat, _ = diag_mod.effective_rhat(d, summ, p)
            ess, _ = diag_mod.effective_ess(d, summ, p)
            rows.append(
                {
                    "param": p,
                    "mean": _fmt(pd.mean),
                    "sd": _fmt(pd.sd),
                    "R̂": _fmt(rhat, 3),
                    "ESS": ("—" if ess is None else _fmt(ess, 0)),
                    "tail_ESS": _fmt(pd.tail_ess, 0),
                    "MCSE": _fmt(pd.mcse),
                    "sep": _fmt(d.chain_separation.get(p, float("nan")), 2),
                }
            )
        return render.DataGrid(pl.DataFrame(rows), height="420px")

    @render.ui
    def diag_tab():
        if input.active_tab() != "Diagnostics":  # render lazily, like the others
            return None
        store_tick()
        run = current()
        if run is None:
            return ui.p("no run selected", style="color:#999")
        d = diagnostics()
        warmup = _warmup_cutoff(run)
        sel = selected_params()
        parts: list[str] = []

        # 1. camdl's verdict (aggregated findings), or a live-run note.
        verdict = _verdict_block_html(run.summary)
        if verdict:
            parts.append(verdict)
        elif run.summary is None:
            parts.append("<div style='color:#888;margin:.2rem 0'>No camdl stage "
                         "summary yet — showing the watcher's live estimate. The "
                         "authoritative verdict appears when the stage finishes.</div>")

        # PMMH ships a concrete MAP point estimate; surface it.
        summ = run.summary
        if summ is not None and summ.map_loglik is not None:
            chain = f" (chain {summ.map_chain})" if summ.map_chain is not None else ""
            parts.append(f"<div style='font-size:.85rem;color:#444;margin:.1rem 0 .4rem'>"
                         f"<b>MAP</b> log-lik {summ.map_loglik:.1f}{chain}</div>")

        # 2. Per-chain mixing bars (camdl acceptance, else live accept/renewal).
        mix = diag_mod.per_chain_mixing(run, warmup)
        if mix is not None:
            label, values, labels, band = mix
            fig = plots.mixing_bars(values, labels, xlabel=label, band=band,
                                    title=f"per-chain {label}")
            parts.append("<div style='font-weight:600;margin:.5rem 0 .1rem'>Per-chain mixing</div>")
            parts.append(f'<div class="svg-wrap" style="max-width:560px">{fig_to_svg(fig)}</div>')

        # 3. Per-chain ESS heatmap (camdl) — which chain drags ESS down.
        if summ is not None and summ.ess_per_chain:
            fig = plots.ess_heatmap(summ.ess_per_chain, params=sel or None,
                                    healthy_ess=float(input.bulk_thresh()),
                                    title="per-chain ESS (camdl)")
            parts.append("<div style='font-weight:600;margin:.6rem 0 .1rem'>Per-chain ESS</div>")
            parts.append(f'<div class="svg-wrap" style="max-width:720px">{fig_to_svg(fig)}</div>')

        # 4. Authoritative per-param table (R̂ / combined ESS / per-chain ESS).
        parts.append(_auth_table_html(run, d, sel, float(input.bulk_thresh())))
        return ui.HTML("".join(parts))


_SEV_COLOR = {"error": "#c0392b", "warn": "#e67e22", "info": "#16a085"}

# Short, accurate names for each finding kind — so the verdict reports *which*
# check failed rather than assuming every error is a convergence (R̂) failure.
_KIND_LABEL = {
    "rhat_high": "R̂",
    "acceptance_rate_unhealthy": "acceptance",
    "max_tree_depth_hits": "tree depth",
    "divergent_transitions": "divergences",
    "low_ess": "ESS",
    "ess_low": "ESS",
}


def _kind_label(kind: str) -> str:
    return _KIND_LABEL.get(kind, kind.replace("_", " "))


def _verdict_block_html(summary) -> str:
    """camdl's aggregated verdict as an HTML block, or ``""`` for a live run
    with no stage summary yet. Used in the always-visible strip and the tab.

    The header names the worst-severity *checks* that flagged (e.g.
    ``acceptance, divergences``) rather than a blanket "not converged" — a high
    acceptance rate or tree-depth saturation is a sampler-health issue, not an
    R̂ convergence failure, and saying otherwise contradicts a healthy R̂."""
    if summary is None:
        return ""
    if not summary.findings:
        return ("<div style='color:#16a085;margin:.2rem 0'>"
                "camdl verdict: no findings (within thresholds).</div>")
    groups = diag_mod.summarize_findings(summary.findings)  # sorted worst-first
    worst = groups[0].severity if groups else Severity.INFO
    flagged = [g for g in groups if g.severity is worst]
    verdict = ", ".join(dict.fromkeys(_kind_label(g.kind) for g in flagged)) or "flagged"
    stage = html.escape(summary.stage or "stage")
    head = (f"<div style='font-weight:600;margin:.2rem 0 .1rem'>camdl verdict · {stage} · "
            f"<span style='color:{_SEV_COLOR.get(worst.value, '#888')}'>{verdict}</span></div>")
    items = "".join(
        f"<li style='color:{_SEV_COLOR[g.severity.value]}'>{html.escape(g.headline)}</li>"
        for g in groups
    )
    return head + f"<ul style='margin:.1rem 0 .45rem;padding-left:1.2rem'>{items}</ul>"


def _auth_table_html(run: RunState, diag, params: list[str], thresh: float) -> str:
    """Per-parameter table: R̂ + combined ESS (camdl-authoritative when present,
    else live arviz) and, when camdl reports it, per-chain ESS — red where a
    parameter or a single chain falls below ``thresh`` (ESS) or 1.1 (R̂)."""
    summ = run.summary
    keep = set(params) if params else set(run.params)
    cols = [p for p in run.params if p in keep]
    epc = summ.ess_per_chain if summ is not None else None
    ncol = max((len(v) for v in epc.values()), default=0) if epc else 0

    head = "<th style='text-align:left'>param</th><th>R̂</th><th>ESS</th>"
    head += "".join(f"<th>c{j}</th>" for j in range(ncol))

    body = []
    for p in cols:
        rhat, _ = diag_mod.effective_rhat(diag, summ, p)
        ess, _ = diag_mod.effective_ess(diag, summ, p)
        rcol = "#c0392b" if (np.isfinite(rhat) and rhat > 1.1) else "#222"
        ess_txt = "—" if ess is None else f"{ess:.0f}"
        ecol = "#c0392b" if (ess is not None and np.isfinite(ess) and ess < thresh) else "#222"
        cells = (f"<td style='text-align:left'>{html.escape(p)}</td>"
                 f"<td style='color:{rcol}'>{_fmt(rhat, 3)}</td>"
                 f"<td style='color:{ecol}'>{ess_txt}</td>")
        pc = (epc.get(p, []) if epc else [])
        for j in range(ncol):
            if j < len(pc):
                c = "#c0392b" if pc[j] < thresh else "#222"
                cells += f"<td style='color:{c}'>{pc[j]:.0f}</td>"
            else:
                cells += "<td>—</td>"
        body.append(f"<tr>{cells}</tr>")

    table = (f"<table class='auth-table'><thead><tr>{head}</tr></thead>"
             f"<tbody>{''.join(body)}</tbody></table>")
    return ("<div style='font-weight:600;margin:.6rem 0 .1rem'>Per-parameter</div>"
            f"<div style='overflow-x:auto'>{table}</div>")


_PHASE_LABEL = {"burn_in": "burn-in", "sampling": "sampling",
                "optimizing": "optimizing", "profiling": "profiling"}


def _progress_blurb(run: RunState) -> str:
    """Badge progress: the heartbeat's phase·step/total when available (real
    burn-in progress, gh#278), else the sweep counter, else 'no draws yet'."""
    p = run.progress
    if p is not None and p.state == "failed":
        return f"<i>failed: {html.escape(p.reason or 'unknown')}</i>"
    if p is not None and p.state == "done":
        # Finished cleanly. The last recorded sweep is target-1 (0-indexed, and
        # thinned), so a "2999/3000" framing reads as incomplete — report the
        # completed sweep total instead.
        n = run.meta.target_sweeps or (
            (run.max_iter() + 1) if run.max_iter() is not None else None)
        return f"{n} sweeps" if n else "complete"
    if p is not None and p.state == "running" and p.step is not None and p.total:
        label = _PHASE_LABEL.get(p.phase, p.phase or "running")
        return f"{label} · {p.step}/{p.total}"
    if run.max_iter() is None:
        bi = f" (burn-in {run.meta.declared_burn_in})" if run.meta.declared_burn_in else ""
        return f"<i>no draws yet{bi}</i>"
    sweep = f"{run.max_iter()}" + (f" / {run.meta.target_sweeps}" if run.meta.target_sweeps else "")
    return f"sweep {sweep}"


def _source_section(title: str, subtitle_html: str, code_html: str | None,
                    missing_html: str) -> str:
    """One Source-tab block: a title + copy button, a subtitle, and the
    highlighted code (or a 'not found' notice)."""
    head_title = f'<span class="src-title">{html.escape(title)}</span>'
    if code_html is None:
        return (f'<div class="src-section"><div class="src-head">{head_title}</div>'
                f'<div class="src-missing">{missing_html}</div></div>')
    return (
        f'<div class="src-section">'
        f'<div class="src-head">{head_title}'
        f'<button class="copy-btn" onclick="camdlCopy(this)">copy</button></div>'
        f'<div class="src-sub">{subtitle_html}</div>'
        f'<div class="src-block">{code_html}</div>'
        f'</div>'
    )


def _warming_notice(run: RunState):
    """Placeholder shown on the plot tabs while a run is still in burn-in."""
    p = run.progress
    if p is not None and p.state == "running" and p.step is not None and p.total:
        return ui.p(f"warming up — burn-in {p.step}/{p.total} (no draws yet)",
                    style="color:#2980b9")
    return ui.p("warming up — no draws yet (still in burn-in)", style="color:#2980b9")


def _fmt(x: float, nd: int = 4) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    if nd == 0:
        return f"{x:.0f}"
    return f"{x:.{nd}g}"


app = App(app_ui, server)
