import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { RunSummary } from '@/api/client'
import { useRun, useRuns } from '@/api/queries'
import { RunBar } from '@/components/RunBar'
import { PosteriorTab } from '@/components/PosteriorTab'
import { PairTab } from '@/components/PairTab'
import { PredictiveTab } from '@/components/PredictiveTab'
import { QuantitiesTab } from '@/components/QuantitiesTab'
import { TracesTab } from '@/components/TracesTab'
import { DiagnosticsTab } from '@/components/DiagnosticsTab'
import { SourceTab } from '@/components/SourceTab'
import { ForestSkeleton, MutedNotice } from '@/components/States'
import { Card } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

/** The single-fit tab grid — the inner navigation level of the Explore
 *  workspace. One run, examined deeply across its diagnostics. The Quantities
 *  tab appears (after Predictive) only when the fit has a quantities sidecar. */
function ResultsTabs({ run }: { run: RunSummary }) {
  const detail = useRun(run.run_id)
  const hasQuantities =
    (detail.data?.available_quantities?.length ?? 0) > 0

  const tabs = [
    { value: 'posterior', label: 'Posterior' },
    { value: 'pair', label: 'Pair' },
    { value: 'predictive', label: 'Predictive' },
    ...(hasQuantities ? [{ value: 'quantities', label: 'Quantities' }] : []),
    { value: 'traces', label: 'Traces' },
    { value: 'diagnostics', label: 'Diagnostics' },
    { value: 'source', label: 'Source' },
  ]

  return (
    <Tabs defaultValue="posterior" className="w-full">
      <TabsList>
        {tabs.map((tab) => (
          <TabsTrigger key={tab.value} value={tab.value}>
            {tab.label}
          </TabsTrigger>
        ))}
      </TabsList>

      <TabsContent value="posterior">
        <PosteriorTab runId={run.run_id} />
      </TabsContent>
      <TabsContent value="pair">
        <PairTab runId={run.run_id} />
      </TabsContent>
      <TabsContent value="predictive">
        <PredictiveTab runId={run.run_id} />
      </TabsContent>
      {hasQuantities && (
        <TabsContent value="quantities">
          <QuantitiesTab runId={run.run_id} />
        </TabsContent>
      )}
      <TabsContent value="traces">
        <TracesTab runId={run.run_id} />
      </TabsContent>
      <TabsContent value="diagnostics">
        <DiagnosticsTab runId={run.run_id} />
      </TabsContent>
      <TabsContent value="source">
        <SourceTab runId={run.run_id} />
      </TabsContent>
    </Tabs>
  )
}

/**
 * Explore one fit: a run selector + its identity ticker over the six-tab
 * single-fit viewer. Owns run discovery and selection — the Compare workspace
 * owns its own (multi-)selection independently.
 */
export function ExploreWorkspace() {
  const { data, isPending, isError } = useRuns()
  const runs = data ?? []
  const [selectedId, setSelectedId] = useState<string>()
  const selected =
    runs.find((r) => r.run_id === selectedId) ?? runs[0] ?? undefined

  // Live monitoring: while the open run is still sampling, refresh its data (and
  // the run list, for the progress blurb) on a short interval so the tabs track
  // the fit instead of freezing at load. Finished runs don't poll.
  const queryClient = useQueryClient()
  const liveId =
    selected && (selected.status === 'running' || selected.status === 'warming')
      ? selected.run_id
      : undefined
  useEffect(() => {
    if (!liveId) return
    const t = setInterval(() => {
      queryClient.invalidateQueries({ queryKey: ['runs'] })
      queryClient.invalidateQueries({
        predicate: (q) =>
          Array.isArray(q.queryKey) && q.queryKey.includes(liveId),
      })
    }, 5000)
    return () => clearInterval(t)
  }, [liveId, queryClient])

  return (
    <div>
      <RunBar
        runs={runs}
        value={selected?.run_id}
        onChange={setSelectedId}
        loading={isPending}
        error={isError}
      />

      {isError ? (
        <MutedNotice
          title="Backend not reachable"
          detail="Couldn't reach /api. Is camdl-watch running and serving this store?"
        />
      ) : isPending ? (
        <Card className="overflow-hidden">
          <ForestSkeleton />
        </Card>
      ) : runs.length === 0 ? (
        <MutedNotice
          title="No runs found"
          detail="This store has no discoverable fits yet."
        />
      ) : selected ? (
        <ResultsTabs run={selected} />
      ) : null}
    </div>
  )
}
