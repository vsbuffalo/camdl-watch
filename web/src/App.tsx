import { useState } from 'react'
import type { RunSummary } from '@/api/client'
import { useRuns } from '@/api/queries'
import { AppHeader } from '@/components/AppHeader'
import { PosteriorTab } from '@/components/PosteriorTab'
import { PairTab } from '@/components/PairTab'
import { PredictiveTab } from '@/components/PredictiveTab'
import { TracesTab } from '@/components/TracesTab'
import { SourceTab } from '@/components/SourceTab'
import { ComingSoon } from '@/components/ComingSoon'
import { ForestSkeleton, MutedNotice } from '@/components/States'
import { Card } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

const TABS = [
  { value: 'posterior', label: 'Posterior' },
  { value: 'pair', label: 'Pair' },
  { value: 'predictive', label: 'Predictive' },
  { value: 'traces', label: 'Traces' },
  { value: 'diagnostics', label: 'Diagnostics' },
  { value: 'source', label: 'Source' },
] as const

function ResultsTabs({ run }: { run: RunSummary }) {
  return (
    <div>
      <Tabs defaultValue="posterior" className="w-full">
        <TabsList>
          {TABS.map((tab) => (
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
        <TabsContent value="traces">
          <TracesTab runId={run.run_id} />
        </TabsContent>
        <TabsContent value="diagnostics">
          <ComingSoon label="Diagnostics" />
        </TabsContent>
        <TabsContent value="source">
          <SourceTab runId={run.run_id} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function App() {
  const { data, isPending, isError } = useRuns()
  const runs = data ?? []
  const [selectedId, setSelectedId] = useState<string>()
  const selected =
    runs.find((r) => r.run_id === selectedId) ?? runs[0] ?? undefined

  return (
    <div className="min-h-screen bg-white text-neutral-900 antialiased">
      <AppHeader
        runs={runs}
        value={selected?.run_id}
        onChange={setSelectedId}
        loading={isPending}
        error={isError}
      />

      <main className="mx-auto w-full max-w-6xl px-4 py-4 sm:px-6 sm:py-6">
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
      </main>
    </div>
  )
}

export default App
