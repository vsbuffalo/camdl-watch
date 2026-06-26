import { useEffect, useMemo, useRef, useState } from 'react'
import { useDraws, usePosterior, useRun } from '@/api/queries'
import { PairPlot } from '@/components/PairPlot'
import { PairSettings } from '@/components/PairSettings'
import { WarmupControl } from '@/components/WarmupControl'
import { ForestSkeleton, MutedNotice } from '@/components/States'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'

const DEFAULT_WARMUP_PCT = 50
// Cap draws for the pair plot: ~N²/2 scatter panels × this many points, so keep
// it lighter than the Posterior tab to stay responsive.
const PAIR_MAX_DRAWS = 800

export function PairTab({ runId }: { runId: string }) {
  const [warmupPct, setWarmupPct] = useState(DEFAULT_WARMUP_PCT)
  const run = useRun(runId)
  const draws = useDraws(runId, warmupPct, PAIR_MAX_DRAWS)
  // Posterior summaries supply the diagonal median overlays and symbol labels.
  const posterior = usePosterior(runId, warmupPct)

  const groups = run.data?.groups

  // Which params are plotted. Initialized to the run's recommended set (scalars
  // + hyperparams; family leaves hidden) and RESET whenever the run changes —
  // tracked by a ref so a same-run refetch never clobbers the user's edits.
  const [selection, setSelection] = useState<Set<string>>(() => new Set())
  const initedRun = useRef<string | null>(null)
  useEffect(() => {
    if (!groups || !draws.data || initedRun.current === runId) return
    const objs = draws.data.objectives ?? []
    const base = [...groups.default_selection]
    if (objs.includes('log_posterior')) base.push('log_posterior')
    setSelection(new Set(base))
    initedRun.current = runId
  }, [groups, draws.data, runId])

  // Render only the selected variables: estimated params first, then objectives
  // (e.g. log_posterior / log_likelihood), in that order, filtered to the
  // selection. The pair plot handles the objective columns as ordinary variables.
  const visibleParams = useMemo(() => {
    const candidates = draws.data
      ? [...draws.data.params, ...draws.data.objectives]
      : []
    return candidates.filter((p) => selection.has(p))
  }, [draws.data, selection])

  return (
    <Card
      className={cn(
        'overflow-hidden transition-opacity',
        draws.isPlaceholderData && 'opacity-60',
      )}
    >
      <WarmupControl
        value={warmupPct}
        onChange={setWarmupPct}
        cutoff={posterior.data?.warmup_cutoff ?? draws.data?.warmup_cutoff ?? null}
        nTail={posterior.data?.n_tail ?? null}
      />

      {groups && (
        <PairSettings
          groups={groups}
          objectives={draws.data?.objectives ?? []}
          selection={selection}
          onChange={setSelection}
        />
      )}

      {draws.isPending && <ForestSkeleton rows={3} />}

      {draws.isError && (
        <MutedNotice
          bordered={false}
          title="Couldn't load the draws"
          detail="The backend returned an error for this run. It may still be warming up."
        />
      )}

      {draws.data && draws.data.n_draws === 0 && (
        <MutedNotice
          bordered={false}
          title="No posterior draws yet"
          detail="This run hasn't produced post-warmup draws. Check back once it has sampled past the cutoff."
        />
      )}

      {draws.data && draws.data.n_draws > 0 && (
        <div className="p-3">
          <PairPlot
            draws={draws.data}
            posterior={posterior.data}
            params={visibleParams}
          />
        </div>
      )}
    </Card>
  )
}
