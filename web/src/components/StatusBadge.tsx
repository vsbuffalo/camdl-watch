import { cn } from '@/lib/utils'

/**
 * A run's lifecycle state as a terminal status light: a small SQUARE swatch
 * (not a pill) plus a lowercase mono label. Color is sparing and muted —
 * running=amber, warming=blue, done=emerald, failed=red, stalled=neutral.
 */
const STATUS: Record<string, { swatch: string; label: string }> = {
  running: { swatch: 'bg-amber-500', label: 'running' },
  warming: { swatch: 'bg-blue-500', label: 'warming' },
  done: { swatch: 'bg-emerald-500', label: 'done' },
  failed: { swatch: 'bg-red-500', label: 'failed' },
  stalled: { swatch: 'bg-neutral-400', label: 'stalled' },
}

export function StatusBadge({
  status,
  className,
}: {
  status: string
  className?: string
}) {
  const meta = STATUS[status] ?? { swatch: 'bg-neutral-400', label: status }
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 font-mono text-[11px] lowercase text-neutral-600',
        className,
      )}
    >
      <span className={cn('size-2 shrink-0', meta.swatch)} aria-hidden />
      {meta.label}
    </span>
  )
}
