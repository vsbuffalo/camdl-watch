import { useState } from 'react'
import { GlobalHeader, type Workspace } from '@/components/GlobalHeader'
import { ExploreWorkspace } from '@/components/ExploreWorkspace'
import { CompareWorkspace } from '@/components/CompareWorkspace'

/**
 * App shell: the persistent header with the workspace nav, and the active
 * workspace below it. Each workspace owns its own data, selection, and inner
 * tabs — App only switches between them. New top-level modes plug in here.
 */
function App() {
  const [workspace, setWorkspace] = useState<Workspace>('explore')

  return (
    <div className="min-h-screen bg-white text-neutral-900 antialiased">
      <GlobalHeader workspace={workspace} onWorkspace={setWorkspace} />

      <main className="mx-auto w-full max-w-6xl px-4 py-4 sm:px-6 sm:py-6">
        {workspace === 'explore' ? <ExploreWorkspace /> : <CompareWorkspace />}
      </main>
    </div>
  )
}

export default App
