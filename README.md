# camdl-watch

A live, local MCMC-diagnostics dashboard for camdl fits. Watches the
content-addressed run store, tail-reads each chain's `trace.tsv` as the sampler
appends, and continuously re-renders trace plots, an enhanced pair plot, a
syntax-highlighted view of the model and fit config, and a diagnostics table
(R̂, bulk/tail-ESS, MCSE, acceptance / trajectory-renewal). Multiple concurrent
runs are auto-discovered, and a run still in burn-in shows up the moment it
starts.

Self-contained: its own `uv` project, vendored plot styling, no import from
your analysis package. Read-only on the run store — point it at any camdl
project's fit store and it just watches.

## Run

From your camdl project root:

```sh
uv run shiny run camdl_watch.app:app --port 8804 --host 127.0.0.1
```

Then open <http://127.0.0.1:8804>. Bind `--host 0.0.0.0` to view from a phone
over the LAN / Tailscale. Pick any free port; check first with
`lsof -iTCP:8804 -sTCP:LISTEN -n -P`.

The store directory defaults to `results/fits` under the current working
directory; override with the `CAMDL_WATCH_STORE` env var:

```sh
CAMDL_WATCH_STORE=/path/to/results/fits uv run shiny run camdl_watch.app:app --port 8804
```

## What it shows

Plots render as **inline SVG** — dense scatter clouds are rasterized, but axes,
ticks, and labels stay vector, so a phone can pinch-zoom into any panel and the
text stays crisp. Each figure carries a subtle clean-PNG download link.

- **Pair plot tab** — the headline figure. Lower-triangle scatter + per-chain
  colored diagonal histograms, one bottom row of `param` vs *each* selected
  objective axis (with its marginal on the diagonal), and a light-gray prior
  overlay on each parameter diagonal. Toggle the x-limits between *show prior breadth* and *fit to
  posterior*. The objective axis defaults to the **observation log-likelihood**
  (the data-fit signal: `obs_ll` $=p(y\mid x,\theta)$ for PGAS; the bare
  `log_likelihood` $=p(y\mid\theta)$ for MH/PMMH) rather than the complete-data
  log-posterior, which for PGAS is dominated by the resampled latent trajectory.
  Switch it in the sidebar.
- **Traces tab** — per-parameter + log_posterior trace panels, all chains
  overlaid, decimated to ~5k points, warm-up region shaded.
- **Source tab** — the syntax-highlighted `.camdl` model (read live from its
  recorded path — the model is *not* stored in the CAS) and the `fit.toml`
  (mirrored in the run store as `fit.toml.original`).
- **Diagnostics** (shared, below the tabs) — a warnings panel (R̂ > 1.1,
  bulk-ESS below threshold, chains separated, ll not plateaued), the post-warmup
  acceptance rate (MH) or trajectory-renewal rate (PGAS), and a per-parameter
  table of mean, sd, R̂, bulk/tail-ESS, MCSE, and a chain-separation ratio. All
  numbers are arviz (rank-normalized split-R̂, bulk/tail-ESS, MCSE) on the
  post-warmup tail.

Run status comes from camdl's per-run **heartbeat** (`progress.json`, gh#278):
**warming** (running, burn-in — with live `step/total`), **running** (running,
sampling), **done** / **failed** (clean terminal states), or **stalled**
(heartbeat went stale → presumed dead / hung). The badge shows the heartbeat's
`phase · step/total`, so burn-in progress is visible *before* any draws. Runs
that predate the heartbeat (e.g. mh/ode, not yet wired) fall back to the
seed-dir `.lock` PID (never trace mtime — a slow PGAS sweep can be minutes, and
staleness ≠ done); a no-heartbeat run that dies in burn-in with zero draws reads
as `stalled` (died), not `done` — a fit that finishes always writes draws. Among
several stage dirs from a relaunch, the live one is followed.

## Controls (sidebar)

- **Run** selector — a dropdown searchable by model stem, config stem,
  algorithm, and run-id hash; each option badged running / warming / done /
  failed / stalled.
- **Warm-up cutoff** — percent of the sweep range to discard before computing
  diagnostics and the plots.
- **Pair-plot prior x-limits** — show prior breadth vs fit to posterior.
- **Objective axis** — a checkbox group (its own section) of the log-quantities
  the run wrote: observation log-lik (default), complete-data log-posterior, and
  (PGAS) transition log-lik. Each checked series gets its own **trace panel** and
  its own **pair-plot bottom row** (`param` vs that series, plus its marginal);
  the objective×objective cells are blanked, so extra series add rows without
  cluttering the scatter matrix.
- **bulk-ESS warn threshold**.
- **Parameters** — scalars / hyperparameters selected by default; each indexed
  family (e.g. the 14 `k_raw_<patch>` leaves) collapses behind an "all" master
  toggle, with the individual leaves underneath.

## Architecture

Middle-out; the UI is the thinnest layer.

- `ingest.py` — the seam. `discover_runs`, tail-safe `tail_chain`,
  `extract_priors`, `read_progress` (the gh#278 heartbeat) + `stage_is_live`
  (heartbeat-first, `.lock`-PID fallback), plus `sample_prior` /
  `log_prior_density`. The only module that knows the store
  layout (`<run>-<hash>/NN-posterior-<hash>/seed_*/chain_k/trace.tsv`), handles
  torn final lines, picks the non-empty posterior dir, surfaces live burn-in
  runs, and normalizes the PGAS `sweep` / MH `step` schemas.
- `diagnostics.py` — pure, arviz-backed. `compute_diagnostics`,
  `derive_warnings`, ll-plateau test, chain separation, acceptance /
  trajectory-renewal.
- `plots.py` — vendored/evolved pair plot + trace grid.
- `highlight.py` — Pygments lexer for the camdl DSL (token lists ported from the
  camdl tree-sitter `queries/highlights.scm` and the skylighting `camdl.xml`),
  plus TOML rendering.
- `sources.py` — read a run's model + `fit.toml` for the Source tab.
- `svg_render.py` — matplotlib figure → responsive inline SVG / clean PNG
  (dense artists rasterized).
- `state.py` — the dataclasses (`RunState`, `ChainBuffer`, `PriorSpec`,
  `Diagnostics`, ...).
- `app.py` — the Shiny projection.

## Prior extraction

`fit.meta.json` records each param's prior *source* (`fit_toml` | `model_ir`).
We resolve the distribution args by:

- parsing the `[estimate]` block of `fit.toml.original` for `fit_toml` params
  (`prior = { log_normal = { mu, sigma } }`, `beta`, etc.); and
- parsing the `parameters { ... }` block of the model `.camdl` file for
  `model_ir` params (`~ normal(mu=, sigma=)`, `~ half_normal(sigma=)`),
  expanding indexed params (`k_raw[patch]` -> `k_raw_Bo`, ...).

Falls back to a flat prior on the declared bounds, else Normal(0, 1). Supported
families: Normal, LogNormal, HalfNormal, Beta, Gamma, Uniform, Flat.

## Tests

```sh
uv run pytest -q
```

Covers tail-safety (torn-line recovery, incremental == full), discovery against
the real store (skipping the empty resume stub, surfacing only live burn-in
runs), prior extraction, diagnostics-vs-direct-arviz agreement, status
classification (liveness over mtime), and plot smoke renders.
