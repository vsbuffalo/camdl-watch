import type { RunSummary } from '@/api/client'
import { RunSelect } from '@/components/RunSelect'
import { StatusBadge } from '@/components/StatusBadge'

interface AppHeaderProps {
  runs: RunSummary[]
  value: string | undefined
  onChange: (runId: string) => void
  loading: boolean
  error: boolean
}

function RunArea({ runs, value, onChange, loading, error }: AppHeaderProps) {
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
    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 border-t border-neutral-100 py-1.5 font-mono text-[11px] text-neutral-500">
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

export function AppHeader(props: AppHeaderProps) {
  const { runs, value } = props
  const selected = runs.find((r) => r.run_id === value)

  return (
    <header className="sticky top-0 z-40 border-b border-neutral-200 bg-white">
      <div className="mx-auto w-full max-w-4xl px-4 sm:px-6">
        <div className="flex items-center justify-between gap-4 py-2.5">
          <div className="flex shrink-0 items-center gap-2">
            <span className="size-3 shrink-0 bg-neutral-900" aria-hidden />
            {/* Mobile: stack onto two tight lines so it never gets squished. */}
            <span className="flex flex-col text-sm font-semibold leading-[0.95] tracking-tight text-neutral-900 sm:hidden">
              <span>camdl</span>
              <span className="text-neutral-400">-watch</span>
            </span>
            {/* ≥sm: single-line wordmark. */}
            <span className="hidden text-sm font-semibold tracking-tight text-neutral-900 sm:inline">
              camdl<span className="text-neutral-400">-watch</span>
            </span>
          </div>
          <div className="flex min-w-0 flex-1 justify-end">
            <RunArea {...props} />
          </div>
        </div>
        {selected && <Ticker run={selected} />}
      </div>
    </header>
  )
}
