import type { ComponentProps } from 'react'
import * as TabsPrimitive from '@radix-ui/react-tabs'
import { cn } from '@/lib/utils'

export const Tabs = TabsPrimitive.Root

export function TabsList({
  className,
  ...props
}: ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      className={cn(
        'flex w-full items-center gap-5 border-b border-neutral-200',
        'overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden',
        className,
      )}
      {...props}
    />
  )
}

export function TabsTrigger({
  className,
  ...props
}: ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        'shrink-0 border-b-2 border-transparent pb-2 -mb-px text-sm text-neutral-500',
        'transition-colors hover:text-neutral-800',
        'focus:outline-none focus-visible:text-neutral-900',
        'disabled:pointer-events-none disabled:opacity-50',
        'data-[state=active]:border-neutral-900 data-[state=active]:text-neutral-900 data-[state=active]:font-medium',
        className,
      )}
      {...props}
    />
  )
}

export function TabsContent({
  className,
  ...props
}: ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      className={cn('mt-4 focus:outline-none', className)}
      {...props}
    />
  )
}
