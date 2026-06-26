import type { RunSummary } from '@/api/client'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from '@/components/ui/select'
import { StatusBadge } from '@/components/StatusBadge'

interface RunSelectProps {
  runs: RunSummary[]
  value: string | undefined
  onChange: (runId: string) => void
}

export function RunSelect({ runs, value, onChange }: RunSelectProps) {
  const selected = runs.find((r) => r.run_id === value)

  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger
        className="min-w-0 sm:w-[22rem]"
        aria-label="Select a run"
      >
        {selected ? (
          <span className="flex min-w-0 items-center gap-2">
            <StatusBadge status={selected.status} />
            <span className="truncate font-mono text-[13px] text-neutral-900">
              {selected.label}
            </span>
          </span>
        ) : (
          <span className="text-neutral-400">Select a run…</span>
        )}
      </SelectTrigger>
      <SelectContent>
        {runs.map((run) => (
          <SelectItem key={run.run_id} value={run.run_id}>
            <span className="flex items-center gap-2">
              <StatusBadge status={run.status} />
              <span className="truncate font-mono text-[13px]">{run.label}</span>
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
