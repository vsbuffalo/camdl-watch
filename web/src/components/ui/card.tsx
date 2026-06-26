import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

/**
 * A flat, rectangular panel — 1px hairline border, no shadow, softly rounded
 * corners. Sub-regions merge into one frame via internal `border-t`/`border-b`
 * rules rather than floating as separate cards.
 */
export function Card({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      className={cn('rounded-sm border border-neutral-200 bg-white', className)}
      {...props}
    />
  )
}

export function CardHeader({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      className={cn(
        'flex flex-col gap-0.5 border-b border-neutral-100 px-3 py-2',
        className,
      )}
      {...props}
    />
  )
}

export function CardTitle({ className, ...props }: ComponentProps<'h3'>) {
  return (
    <h3
      className={cn(
        'text-[10px] font-medium uppercase tracking-wider text-neutral-400',
        className,
      )}
      {...props}
    />
  )
}

export function CardContent({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('px-3 py-3', className)} {...props} />
}
