import type { RunSummary } from '@/api/client'
import { RunSelect } from '@/components/RunSelect'
import { StatusBadge } from '@/components/StatusBadge'

interface RunBarProps {
  runs: RunSummary[]
  value: string | undefined
  onChange: (runId: string) => void
  loading: boolean
  error: boolean
}

function RunArea({ runs, value, onChange, loading, error }: RunBarProps) {
  if (error) {
    return (
      <span className="font-mono text-[11px] text-neutral-400">
        backend offline
      </span>
    )
  }
  if (loading) {
    return (
      <div className="h-8 w-full animate-pulse rounded-none bg-neutral-100 sm:w-[22rem]" />
    )
  }
  if (runs.length === 0) {
    return <span className="font-mono text-[11px] text-neutral-400">no runs</span>
  }
  return <RunSelect runs={runs} value={value} onChange={onChange} />
}

/**
 * Dense monospace identity line — the "ticker" — reading the selected run's
 * identity and shape: `run_id · ALGO/BACKEND · N CHAINS · M PARAMS` plus a
 * status light. Flows and wraps on narrow screens so it never overflows.
 */
function Ticker({ run }: { run: RunSummary }) {
  const sep = <span className="text-neutral-300">·</span>
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 py-1.5 font-mono text-[11px] text-neutral-500">
      <span className="text-neutral-700">{run.run_id}</span>
      {sep}
      <span className="uppercase">
        {run.algorithm}/{run.backend}
      </span>
      {sep}
      <span className="tabular-nums">{run.n_chains} CHAINS</span>
      {sep}
      <span className="tabular-nums">{run.n_params} PARAMS</span>
      <StatusBadge status={run.status} className="ml-auto" />
    </div>
  )
}

/**
 * Live progress for a running/warming/failed run, from camdl's `progress.json`
 * heartbeat: the phase + sweep counter + a thin completion bar, or — on a clean
 * failure — the reason. Nothing for a finished run (its scores speak instead).
 */
function ProgressBlurb({ run }: { run: RunSummary }) {
  const p = run.progress
  if (!p) return null

  if (run.status === 'failed' || p.state === 'failed') {
    return (
      <div className="flex flex-wrap items-center gap-x-1.5 py-1 font-mono text-[11px] text-red-600">
        <span className="uppercase tracking-wide">failed</span>
        {p.reason && (
          <span className="min-w-0 truncate text-red-500">· {p.reason}</span>
        )}
      </div>
    )
  }

  const live = run.status === 'running' || run.status === 'warming'
  if (!live) return null

  const phase = p.phase ? p.phase.replace(/_/g, '-') : p.state
  const counter =
    p.step != null && p.total != null
      ? `${p.step.toLocaleString()}/${p.total.toLocaleString()}`
      : null

  return (
    <div className="py-1">
      <div className="flex flex-wrap items-center gap-x-2 font-mono text-[11px] text-neutral-500">
        <span className="uppercase tracking-wide text-neutral-700">{phase}</span>
        {counter && (
          <>
            <span className="text-neutral-300">·</span>
            <span className="tabular-nums">{counter}</span>
          </>
        )}
        {p.pct != null && (
          <span className="tabular-nums text-neutral-400">{p.pct}%</span>
        )}
      </div>
      {p.pct != null && (
        <div className="mt-1 h-1 w-full max-w-[22rem] overflow-hidden bg-neutral-100">
          <div
            className="h-full bg-blue-700 transition-[width] duration-500"
            style={{ width: `${p.pct}%` }}
          />
        </div>
      )}
    </div>
  )
}

/**
 * The Explore workspace's selector bar: the run dropdown over its identity
 * ticker (and, for a live or failed run, a progress blurb). Lives in the
 * content column and is left-aligned with the panels below it.
 */
export function RunBar(props: RunBarProps) {
  const { runs, value } = props
  const selected = runs.find((r) => r.run_id === value)

  return (
    <div className="mb-4 border-b border-neutral-200 pb-1">
      <div className="flex min-w-0 items-center py-1">
        <RunArea {...props} />
      </div>
      {selected && <Ticker run={selected} />}
      {selected && <ProgressBlurb run={selected} />}
    </div>
  )
}
