import type { components } from './types'

/**
 * Typed wire aliases, derived from the OpenAPI-generated schemas so the
 * frontend and the FastAPI core share one source of truth. Never widen these
 * by hand — regenerate `types.ts` from the schema instead.
 */
export type RunSummary = components['schemas']['RunSummary']
export type RunDetail = components['schemas']['RunDetail']
export type PosteriorResponse = components['schemas']['PosteriorResponse']
export type ParamPosterior = components['schemas']['ParamPosterior']
export type DrawsResponse = components['schemas']['DrawsResponse']
/** Row-aligned posterior draws — the substrate for densities and the pair plot. */
export type Draws = DrawsResponse
export type StreamInfo = components['schemas']['StreamInfo']
export type DimensionInfo = components['schemas']['DimensionInfo']
export type FindingGroup = components['schemas']['FindingGroup']
export type SourceResponse = components['schemas']['SourceResponse']
export type SourceFile = components['schemas']['SourceFile']
export type PredictiveResponse = components['schemas']['PredictiveResponse']
export type PredictivePoint = components['schemas']['PredictivePoint']
export type ObservedPoint = components['schemas']['ObservedPoint']
export type TracesResponse = components['schemas']['TracesResponse']
export type ParamTrace = components['schemas']['ParamTrace']
export type TraceSeries = components['schemas']['TraceSeries']

/** The closed set of run lifecycle states the UI badges. */
export type RunStatus =
  | 'running'
  | 'warming'
  | 'done'
  | 'failed'
  | 'stalled'

async function getJson<T>(path: string): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, { headers: { Accept: 'application/json' } })
  } catch (cause) {
    // Network-level failure (backend down, DNS, CORS): surface a clear message
    // rather than a cryptic TypeError.
    throw new ApiError('backend not reachable', { cause })
  }
  if (!res.ok) {
    throw new ApiError(`request failed (HTTP ${res.status})`, { status: res.status })
  }
  return (await res.json()) as T
}

/** A failed `/api` call, carrying an HTTP status when one was received. */
export class ApiError extends Error {
  readonly status?: number
  constructor(message: string, opts?: { status?: number; cause?: unknown }) {
    super(message, opts?.cause ? { cause: opts.cause } : undefined)
    this.name = 'ApiError'
    this.status = opts?.status
  }
}

/** Every discoverable run, newest first. */
export function getRuns(): Promise<RunSummary[]> {
  return getJson<RunSummary[]>('/api/runs')
}

/** One run's metadata, schema, and verdict. */
export function getRun(runId: string): Promise<RunDetail> {
  return getJson<RunDetail>(`/api/runs/${encodeURIComponent(runId)}`)
}

/** Doc-labelled posterior summary — the per-row overlay/label payload. */
export function getPosterior(
  runId: string,
  warmupPct: number,
): Promise<PosteriorResponse> {
  const id = encodeURIComponent(runId)
  return getJson<PosteriorResponse>(
    `/api/runs/${id}/posterior?warmup_pct=${warmupPct}`,
  )
}

/**
 * Row-aligned post-warmup draws — feeds the marginal densities and the
 * pair/corner plot. `max_draws` is capped server-side; the default suits the
 * Posterior tab, while the Pair tab passes a smaller cap for scatter perf.
 */
export function getDraws(
  runId: string,
  warmupPct: number,
  maxDraws = 1200,
): Promise<DrawsResponse> {
  const id = encodeURIComponent(runId)
  return getJson<DrawsResponse>(
    `/api/runs/${id}/draws?warmup_pct=${warmupPct}&max_draws=${maxDraws}`,
  )
}

/**
 * The fit's sources: the `.camdl` model (read live from its recorded path) and
 * the mirrored `fit.toml`, both Pygments-highlighted server-side. Carries the
 * token stylesheet to inject once.
 */
export function getSource(runId: string): Promise<SourceResponse> {
  const id = encodeURIComponent(runId)
  return getJson<SourceResponse>(`/api/runs/${id}/source`)
}

/**
 * One stream's posterior-predictive ribbons + observed series. 404s when the
 * stream has no predictive artifact (`camdl fit predict` hasn't run).
 */
export function getPredictive(
  runId: string,
  stream: string,
): Promise<PredictiveResponse> {
  const id = encodeURIComponent(runId)
  const s = encodeURIComponent(stream)
  return getJson<PredictiveResponse>(`/api/runs/${id}/predictive/${s}`)
}

/**
 * Per-parameter, per-chain iteration traces (thinned) for the trace grid — the
 * raw mixing view. `max_points` is capped server-side per chain.
 */
export function getTraces(
  runId: string,
  warmupPct: number,
  maxPoints = 600,
): Promise<TracesResponse> {
  const id = encodeURIComponent(runId)
  return getJson<TracesResponse>(
    `/api/runs/${id}/traces?warmup_pct=${warmupPct}&max_points=${maxPoints}`,
  )
}
