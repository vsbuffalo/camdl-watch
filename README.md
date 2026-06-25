# camdl-watch

A live, local MCMC-diagnostics dashboard for [camdl](https://github.com/vsbuffalo/camdl)
fits. Point it at a fit store and it watches each chain's `trace.tsv` as the
sampler appends, continuously re-rendering trace plots, a pair plot, the
syntax-highlighted model + fit config, and a diagnostics table (R̂, bulk/tail-ESS,
MCSE, acceptance / trajectory-renewal). Concurrent runs are auto-discovered, and
a run still in burn-in shows up the moment it starts.

Self-contained and read-only on the store — it never touches your fits.

## Install

With [uv](https://docs.astral.sh/uv/):

```sh
# Install the `camdl-watch` command on your PATH:
uv tool install git+https://github.com/vsbuffalo/camdl-watch

# Or run it once without installing:
uvx --from git+https://github.com/vsbuffalo/camdl-watch camdl-watch --port 8804

# Or add it to a project's dev dependencies:
uv add --dev git+https://github.com/vsbuffalo/camdl-watch
```

From a local checkout, swap the git URL for the path (add `--editable` to track edits).

## Usage

Run from your camdl project root and open the printed URL:

```sh
camdl-watch --port 8804
```

Flags:

- `--port` / `-p` — TCP port (default `8804`).
- `--host` — interface to bind; use `--host 0.0.0.0` to view from a phone over
  the LAN / Tailscale (default `127.0.0.1`).
- `--store` / `-s` — the fit store to watch (the directory of run dirs).
  Defaults to `results/fits` under the current directory.

```sh
camdl-watch --port 8804 --host 0.0.0.0 --store /path/to/results/fits
```

`--store` just sets the `CAMDL_WATCH_STORE` env var, so that works too;
`python -m camdl_watch ...` is equivalent to the `camdl-watch` command.

## What it shows

- **Pair plot** — lower-triangle scatter, per-chain colored diagonal histograms,
  a prior overlay, and a bottom row of each parameter against the objective
  (observation log-likelihood by default).
- **Traces** — per-parameter and log-posterior trace panels, all chains overlaid,
  warm-up region shaded.
- **Source** — the syntax-highlighted `.camdl` model and `fit.toml`.
- **Diagnostics** — camdl's end-of-stage verdict over a live arviz read: a
  warnings panel, acceptance / trajectory-renewal rate, and a per-parameter
  table of mean, sd, R̂, bulk/tail-ESS, MCSE.

Plots render as inline SVG, so a phone can pinch-zoom any panel and the text
stays crisp.

## Develop

```sh
uv run --extra dev pytest -q
```
