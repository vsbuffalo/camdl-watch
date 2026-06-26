import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * Quiet, centered notice for empty / error / unreachable states. `bordered`
 * (default) draws its own dashed frame for standalone use; pass `bordered={false}`
 * when it sits inside an existing panel and shouldn't double up borders.
 */
export function MutedNotice({
  title,
  detail,
  className,
  bordered = true,
}: {
  title: string
  detail?: ReactNode
  className?: string
  bordered?: boolean
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-1 px-6 py-12 text-center',
        bordered &&
          'rounded-none border border-dashed border-neutral-200 bg-[#fafafa]',
        className,
      )}
    >
      <p className="text-sm font-medium text-neutral-500">{title}</p>
      {detail && <p className="max-w-sm text-xs text-neutral-400">{detail}</p>}
    </div>
  )
}

/** Placeholder rows that occupy the same rhythm as the forest while loading. */
export function ForestSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="divide-y divide-neutral-100">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="px-3 py-2.5">
          <div className="h-[5.5rem] animate-pulse rounded-none bg-neutral-100" />
        </div>
      ))}
    </div>
  )
}
