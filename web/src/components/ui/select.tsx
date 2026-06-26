import type { ComponentProps } from 'react'
import * as SelectPrimitive from '@radix-ui/react-select'
import { cn } from '@/lib/utils'
import { Check, ChevronDown } from './icons'

export const Select = SelectPrimitive.Root
export const SelectValue = SelectPrimitive.Value
export const SelectGroup = SelectPrimitive.Group

export function SelectTrigger({
  className,
  children,
  ...props
}: ComponentProps<typeof SelectPrimitive.Trigger>) {
  return (
    <SelectPrimitive.Trigger
      className={cn(
        'flex w-full items-center justify-between gap-2 rounded-none border border-neutral-200',
        'bg-white px-2.5 py-1.5 text-sm text-neutral-900',
        'transition-colors hover:bg-neutral-50',
        'focus:outline-none focus-visible:border-neutral-400',
        'data-[state=open]:border-neutral-400 data-[placeholder]:text-neutral-400',
        className,
      )}
      {...props}
    >
      {children}
      <SelectPrimitive.Icon asChild>
        <ChevronDown className="size-4 shrink-0 text-neutral-400" />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  )
}

export function SelectContent({
  className,
  children,
  position = 'popper',
  ...props
}: ComponentProps<typeof SelectPrimitive.Content>) {
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        position={position}
        sideOffset={6}
        className={cn(
          'z-50 max-h-[var(--radix-select-content-available-height)] min-w-[var(--radix-select-trigger-width)]',
          'overflow-hidden rounded-none border border-neutral-200 bg-white',
          'data-[state=open]:animate-in data-[state=closed]:animate-out',
          className,
        )}
        {...props}
      >
        <SelectPrimitive.Viewport className="p-0">
          {children}
        </SelectPrimitive.Viewport>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  )
}

export function SelectItem({
  className,
  children,
  ...props
}: ComponentProps<typeof SelectPrimitive.Item>) {
  return (
    <SelectPrimitive.Item
      className={cn(
        'relative flex w-full cursor-pointer select-none items-center gap-2 rounded-none',
        'border-b border-neutral-100 py-1.5 pl-2.5 pr-8 text-sm text-neutral-800 outline-none last:border-b-0',
        'data-[highlighted]:bg-neutral-100 data-[state=checked]:font-medium',
        'data-[disabled]:pointer-events-none data-[disabled]:opacity-50',
        className,
      )}
      {...props}
    >
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
      <SelectPrimitive.ItemIndicator className="absolute right-2 inline-flex items-center">
        <Check className="size-4 text-neutral-500" />
      </SelectPrimitive.ItemIndicator>
    </SelectPrimitive.Item>
  )
}
