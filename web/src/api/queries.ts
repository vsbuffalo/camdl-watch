import { useQuery } from '@tanstack/react-query'
import {
  getDraws,
  getPosterior,
  getPredictive,
  getRun,
  getRuns,
  getSource,
  getTraces,
} from './client'

/** Query-key factory — keeps cache keys consistent across the app. */
export const qk = {
  runs: ['runs'] as const,
  run: (id: string) => ['run', id] as const,
  posterior: (id: string, warmupPct: number) =>
    ['posterior', id, warmupPct] as const,
  draws: (id: string, warmupPct: number, maxDraws: number) =>
    ['draws', id, warmupPct, maxDraws] as const,
  source: (id: string) => ['source', id] as const,
  predictive: (id: string, stream: string) =>
    ['predictive', id, stream] as const,
  traces: (id: string, warmupPct: number) => ['traces', id, warmupPct] as const,
}

/** List of runs for the selector. Refetches occasionally so new fits appear. */
export function useRuns() {
  return useQuery({
    queryKey: qk.runs,
    queryFn: getRuns,
    refetchInterval: 30_000,
  })
}

/** One run's detail (schema, findings). */
export function useRun(runId: string | undefined) {
  return useQuery({
    queryKey: qk.run(runId ?? '∅'),
    queryFn: () => getRun(runId as string),
    enabled: Boolean(runId),
  })
}

/** The doc-labelled posterior summary — overlays, labels, and numbers. */
export function usePosterior(runId: string | undefined, warmupPct: number) {
  return useQuery({
    queryKey: qk.posterior(runId ?? '∅', warmupPct),
    queryFn: () => getPosterior(runId as string, warmupPct),
    enabled: Boolean(runId),
    placeholderData: (prev) => prev,
  })
}

/**
 * Row-aligned posterior draws for the marginal densities and pair plot.
 * `maxDraws` defaults to the Posterior tab's cap; the Pair tab passes a
 * smaller one to keep the scatter panels light.
 */
export function useDraws(
  runId: string | undefined,
  warmupPct: number,
  maxDraws = 1200,
) {
  return useQuery({
    queryKey: qk.draws(runId ?? '∅', warmupPct, maxDraws),
    queryFn: () => getDraws(runId as string, warmupPct, maxDraws),
    enabled: Boolean(runId),
    placeholderData: (prev) => prev,
  })
}

/** The fit's model + fit.toml sources, highlighted server-side. */
export function useSource(runId: string | undefined) {
  return useQuery({
    queryKey: qk.source(runId ?? '∅'),
    queryFn: () => getSource(runId as string),
    enabled: Boolean(runId),
  })
}

/**
 * One stream's posterior-predictive ribbons + observed series. Disabled until a
 * stream is chosen; 404s surface as `isError` (stream has no predictive yet).
 */
export function usePredictive(
  runId: string | undefined,
  stream: string | undefined,
) {
  return useQuery({
    queryKey: qk.predictive(runId ?? '∅', stream ?? '∅'),
    queryFn: () => getPredictive(runId as string, stream as string),
    enabled: Boolean(runId && stream),
    placeholderData: (prev) => prev,
  })
}

/** Per-parameter, per-chain iteration traces for the trace grid. */
export function useTraces(runId: string | undefined, warmupPct: number) {
  return useQuery({
    queryKey: qk.traces(runId ?? '∅', warmupPct),
    queryFn: () => getTraces(runId as string, warmupPct),
    enabled: Boolean(runId),
    placeholderData: (prev) => prev,
  })
}
