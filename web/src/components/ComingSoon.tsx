import { MutedNotice } from '@/components/States'

/** Placeholder for tabs landing in later milestones (predictive, traces, …). */
export function ComingSoon({ label }: { label: string }) {
  return (
    <MutedNotice
      title={`${label} — coming soon`}
      detail="This view ships in a later milestone."
    />
  )
}
