# Proposal: v2 results viewer — React/TypeScript over a FastAPI seam

Date: 2026-06-25
Project: camdl-watch
Status: proposed
Tags: architecture, frontend, stack, fastapi, react, sidecars

## Problem

camdl-watch today is a *live MCMC monitor*: a Shiny-for-Python app that tails
each chain's `trace.tsv` and re-renders matplotlib SVGs of traces, a pair plot,
and a diagnostics table while a sampler runs. It does that job well. It is the
wrong foundation for the product we now want.

The next product is a *results viewer*: a browser surface for **finished** fits
that answers "what did this fit conclude" — parameter estimates labelled with
their meaning and citations, posterior-predictive overlays against the observed
data, generated quantities — and that looks and feels like a real application on
a phone, an iPad, and a desktop. Two forces make the current stack a dead end
for that:

1. **UX ceiling.** The mobile experience is poor, and the ceiling is set by
   matplotlib SVGs and server-rendered widgets, not by anything we control. No
   Python all-in-one UI framework reaches the "smooth, finnicky-about-controls,
   different styling per device" bar. Owning that ceiling means owning the UI
   layer.

2. **The metadata is finally rich enough to be worth surfacing well.** Recent
   camdl work ships, per finished fit, a `fit.meta.json` whose `docs` field
   carries the model's `#'` declaration comments (a human description, a display
   `@symbol` such as β/γ, and an optional `@ref` citation per parameter,
   compartment, transition, observation, and dimension) and a `schema` field
   describing observation streams and dimension levels; alongside it,
   `predictive/<stream>.tsv` and `observed/<stream>.tsv` hold the
   posterior-predictive quantile ribbons and the data they are checked against.
   With this, the canonical figures can be generated from metadata alone — no
   per-model plot configuration, and no plotting in the modelling language.

This proposal selects a stack for that viewer, lays out a v2 tree that lets the
current app keep running untouched, and defines a CLI and a cutover path so v2
can be served beside v1 and then replace it when it is solid.

## Goals and non-goals

**Goals.** A typed, future-facing foundation; excellent responsive UX across
phone/iPad/desktop; figures auto-derived from sidecar metadata (no hooks, no
language changes); the existing Python core (ingest, diagnostics) reused as-is;
v1 frozen and runnable on the public default branch throughout the transition; a
clean cutover by merge.

**Non-goals (explicitly deferred).** A desktop-packaged app; a plugin/hook
registry for bespoke plots; live-streaming (SSE/WebSocket) of running fits;
migrating the live monitor onto the new stack. Each is a clean later addition on
this foundation, not a prerequisite. The viewer is built against finished fits
first, where the sidecar payoff is largest.

## Options considered

**A. Stay single-language, escape Shiny.** Plotly Dash (React under the hood,
interactive charts, all-Python), Reflex (Python compiled to React), or
FastHTML + HTMX. *Rejected as the foundation.* Dash and Reflex raise the floor
but cap the ceiling: their component models fight bespoke, premium controls, and
HTMX's server-roundtrip-per-interaction is the wrong model for a rich
client-side data explorer. They would be the right call for a throwaway tool;
they are not the "solid, future-facing" base we are deciding to invest in.

**B. Split: typed React/TypeScript frontend over a thin Python API.**
*Recommended.* The Python core stays the program; a thin FastAPI projects it as
typed JSON; a React + TypeScript SPA owns the UI. This is the stack a UX
engineer who is finnicky about controls actually reaches for, and it is the most
agent-tractable UI stack in existence, which matters because the UI is built
agentically (direction and taste from a human; component code from agents). It
also *is* the middle-layer/UI separation the project already believes in —
Shiny smushes the two together; an API seam makes the separation honest.

The cost of B — two processes, a build step, an API contract, and reimplementing
the results-viewer charts in a JS grammar — is real and is bought deliberately
here because this is the moment to build a real foundation, not a quick monitor.

## Recommended stack

- **Backend / seam:** FastAPI (uvicorn). Pydantic models on the boundary are a
  re-projection of the existing `state.py` ADTs, so the types we already have
  become the wire contract. FastAPI's OpenAPI schema feeds `openapi-typescript`
  to generate the frontend's types — one source of truth, typed on both ends.
- **Frontend:** Vite + React + TypeScript (SPA). Not Next.js — its SSR/server-
  component model fights a separate Python data service and adds concepts a
  local-first scientific tool does not need.
- **Controls / shell:** shadcn/ui (Radix primitives + Tailwind). This is where
  "feels like a real app on iPad" lives: accessible components whose code we
  own, and Tailwind breakpoints give per-device styling for free — precisely
  Shiny's worst weakness.
- **Data fetching:** TanStack Query (replaces `reactive.poll`; `refetchInterval`
  covers the only polling we still need for finished fits).
- **Figures:** Observable Plot as the workhorse — a real grammar of graphics,
  crisp SVG on retina/mobile, natural for our charts (forest = dot + CI rule;
  posterior-predictive = band via `y1/y2`; trace = line; pair = dot). `visx` is
  the reach-down escape hatch for bespoke interactive panels; dense pair-plot
  scatter (10k+ points), the one case SVG chokes on, is rasterized for that
  single panel server-side or drawn on a canvas layer.
- **Later, not now:** Tauri to package a desktop app (tiny Rust-shell binaries
  loading the same web build; culturally aligned with camdl's Rust toolchain).

**Correctness guardrail.** No statistic is ever recomputed in JavaScript. R̂,
ESS, acceptance, quantiles are computed in Python (arviz / camdl-authoritative)
and shipped as numbers; the frontend only draws. Scientific truth stays in the
Python core; the frontend is pure presentation.

## Branch strategy

The two versions are kept apart by git, not by an in-tree directory split, which
the public-repo setting makes the cleaner choice: `uv tool install git+…` tracks
the default branch, so `main` stays the working Shiny v1 and the rewrite lives on
a `v2` branch that is invisible to existing installs until merged. The branch
*is* v2 — no `v2/` path prefix, no dual-CLI shim, no Shiny carried as dead
weight. Cutover is a merge of `v2 → main` (dropping `app.py` and the `shiny`
dependency in that change); v1 is preserved in git history, not as in-tree
furniture.

`main` is frozen-v1 and not under active change, so all work happens on `v2` and
merges at the end; a genuine v1 bug is backported to `main` as the exception, not
the workflow.

## Repository layout (on the `v2` branch)

The shared Python core stays where it is and grows *additively*; the FastAPI app
joins it as a subpackage and the React app sits at the top level.

```
camdl_watch/                 # shared core (extended) + FastAPI backend
  ingest.py state.py diagnostics.py grouping.py plots.py
  sources.py highlight.py svg_render.py
  docs.py                    # NEW (core): ModelDocs/DocBlock + base-name resolve
  schema.py                  # NEW (core): ObsSchema (streams, dimension levels)
  predictive.py              # NEW (core): predictive/observed readers
  api/                       # NEW: FastAPI app + routes + Pydantic wire models
    app.py models.py routes.py
  cli.py                     # single launcher -> FastAPI (serves built web + /api)
  app.py                     # Shiny v1 — retained until parity, then removed at merge
web/                         # Vite + React + TS frontend
  package.json vite.config.ts tsconfig.json
  src/api/types.ts           # generated from the OpenAPI schema
  src/...
  dist/                      # built bundle, served by FastAPI in prod (gitignored)
Makefile                     # NEW: dev / build / serve targets
```

The store-reading seam stays single (`ingest.py` remains "the only module that
knows the run-store layout"); the new readers are core modules beside it. Core
additions are new modules and new *optional* fields on existing dataclasses, so
v1's Shiny code paths keep working unchanged on the branch (runnable for
side-by-side comparison via `uv run shiny run camdl_watch.app:app`) until they
are removed at cutover.

## CLI and coexistence

`camdl-watch` stays a single command; on the `v2` branch it launches uvicorn
serving `/api/*` plus the built `web/dist/` as static files on one port — the
"just show me the results" path. Flags are as today (`--store`, `--host`,
`--port`); `--host 0.0.0.0` keeps it reachable from a phone over Tailscale/LAN.

Running both versions at once needs no in-tree machinery:

- **v1** — the already-installed tool from public `main`: `camdl-watch --port 8804`.
- **v2** — from the branch checkout: `uv run camdl-watch --port 8800`, or a
  `git worktree add ../camdl-watcher-v2 v2` for a fully separate directory.

Dev orchestration (uvicorn reload + Vite HMR with an `/api` proxy, two
processes) lives in Makefile targets, not the Python launcher:

```
make dev         # uvicorn (reload) + vite dev server, /api proxied to uvicorn
make build       # vite build -> web/dist
make serve       # camdl-watch (serves dist + api on one port)
```

FastAPI/uvicorn are added to the project dependencies on the branch (the rewrite
needs them); the now-unused `shiny`/`arviz`-for-rendering surface is trimmed at
cutover.

## API surface (initial)

Pydantic wire types project the existing ADTs; routes are read-only over the
store. OpenAPI generates `web/src/api/types.ts`.

```
GET /api/runs                          -> [RunSummary]   # id, label, model,
                                         algorithm/backend, status, updated_at
GET /api/runs/{id}                     -> RunDetail      # meta + docs + schema +
                                         status + verdict/findings + params
                                         (each with resolved prior + DocBlock)
GET /api/runs/{id}/draws?params=&warmup= -> columnar posterior (param -> per-chain)
GET /api/runs/{id}/predictive/{stream} -> {ribbon quantiles, observed series}
GET /api/runs/{id}/diagnostics         -> R̂/ESS table (camdl-authoritative else live)
GET /api/runs/{id}/source              -> raw model + fit.toml text (frontend highlights)
# later: GET /api/runs/{id}/stream     -> SSE live tail
```

### Sidecar fields this depends on

From `fit.meta.json`: `docs` (`{parameters,compartments,transitions,observations,
dimensions} -> {name -> {text, symbol, ref}}`) and `schema`
(`{dimensions: {dim -> {levels:[...]}}, streams: [{name, index_dims,
value_column, value_kind, likelihood}]}`). Docs are keyed by *declaration* name
(`k_raw`); estimated coordinates are expanded (`k_raw_Bo`), so `docs.py` resolves
an expanded coordinate to its `DocBlock` by longest base-name prefix — the same
trick `ingest._resolve_ir_for_param` already uses for priors. Per-fit predictive
artifacts: `predictive/<stream>.tsv` (q05…q95 by time × stratum) and
`observed/<stream>.tsv`.

### Core types (sketch)

```python
@dataclass(frozen=True)
class DocBlock:
    text: str | None
    symbol: str | None
    reference: str | None        # JSON "ref"

@dataclass(frozen=True)
class ModelDocs:
    parameters: dict[str, DocBlock]
    compartments: dict[str, DocBlock]
    transitions: dict[str, DocBlock]
    observations: dict[str, DocBlock]
    dimensions: dict[str, DocBlock]
    def for_param(self, coord: str) -> DocBlock | None: ...   # base-name resolve
```

`docs` and `schema` thread onto `RunMeta` as optional fields; the existing param
table, pair plot, and traces become doc-aware (symbol axis labels, description
tooltips, citations) the moment they are wired.

## Plotting: hookless

With `docs` (symbols, descriptions, citations) + `schema` (streams, dimension
levels) + the draws/predictive data, the metadata *is* the plot spec. The viewer
auto-generates the canonical set — caterpillar/forest labelled with symbols and
citations, posterior-predictive ribbons per stream and stratum, traces, pair —
with zero registration and nothing in the modelling language. In a typed React
app a "custom plot" is just another typed component, so a hook registry stops
being an architectural feature; it is dropped from scope.

## Milestones (agent-parallelizable)

- **M0 — Scaffold.** `v2` branch; `camdl_watch/api/` + top-level `web/`; FastAPI
  and uvicorn deps; Makefile dev/build/serve; `camdl-watch` launching the API
  with FastAPI "hello" and a Vite "hello" wired (dev proxy + prod static serve).
  *Proves the two-process plumbing end to end.*
- **M1 — Core extensions (shared).** `docs.py`, `schema.py`, `predictive.py`;
  additive `docs`/`schema` fields on `RunMeta`; unit tests against camdl golden
  fixtures. *Independent of the frontend.*
- **M2 — API.** Pydantic models + routes for runs / detail / draws /
  diagnostics / source; OpenAPI → TS type codegen. *Depends on M1.*
- **M3 — Frontend shell.** shadcn install; responsive layout; run selector;
  tabs; TanStack Query client; generated types wired. *Independent of M1/M2;
  runs against a stub.*
- **M4 — First screen.** Doc-labelled forest/caterpillar plot (Observable Plot):
  symbols, descriptions, `@ref` citations. *The validation screen — proves the
  whole foundation on real pixels.* Depends on M2 + M3.
- **M5 — Parity + new screens.** Traces, pair, posterior-predictive ribbons,
  diagnostics table, source view.
- **M6 — Live mode + cutover.** SSE live tail; flip `_DEFAULT` to `v2`; retire
  v1.

M1 and M3 fan out in parallel immediately; M2 follows M1; M4 joins the two.

## Tradeoffs and risks

- **Two languages / a build step.** Mitigated: the Python core barely changes;
  the API is thin and generated into TS types; the React surface is built
  agentically. The new *concepts* for the maintainer are the API contract
  (generated) and Tailwind classes (agent-written).
- **Chart reimplementation.** The results-viewer figures are rebuilt in
  Observable Plot; `plots.py`/`svg_render.py` stay serving the v1 monitor (and
  the one rasterized pair-scatter panel) until/unless the monitor is migrated.
- **Scope creep toward "rewrite everything at once."** Held off by freezing v1
  and building the viewer against finished fits first; live-mode and cutover are
  the last milestone, not the first.
