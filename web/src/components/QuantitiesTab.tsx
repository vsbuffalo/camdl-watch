import { useEffect, useMemo, useRef, useState } from 'react'
import * as Plot from '@observablehq/plot'
import type {
  QuantityBandPoint,
  QuantityInfo,
  QuantityScalarRow,
} from '@/api/client'
import { useQuantityScalars, useQuantitySeries, useRun } from '@/api/queries'
import { ForestSkeleton, MutedNotice } from '@/components/States'
import { Card } from '@/components/ui/card'
import { fmtTick, fmtValue } from '@/lib/format'
import { cn } from '@/lib/utils'

const BAND = { band90: '#dbeafe', bandIqr: '#93c5fd', median: '#2563eb' } as const
const AXIS = '#737373'
const PANEL_HEIGHT = 180
const MONO = 'var(--font-mono)'

/** A short provenance tag for non-state quantities (observations / derived). */
function sourceTag(source: string): string | null {
  if (source === 'observations') return 'obs'
  if (source === 'derived') return 'derived'
  return null
}

function stratumLabel(stratum: Record<string, string>): string {
  return Object.entries(stratum)
    .map(([k, v]) => `${k}=${v}`)
    .join(' · ')
}

// ── Series quantities — one banded ribbon per stratum cell ──────────────────

/** One stratum's banded trajectory: nested 90%/IQR ribbons + a median line. */
function BandPanel({
  title,
  points,
}: {
  title: string
  points: QuantityBandPoint[]
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    setWidth(Math.round(el.getBoundingClientRect().width))
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0
      if (w > 0) setWidth(Math.round(w))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    const el = ref.current
    if (!el || width <= 0) return
    const pts = [...points].sort((a, b) => a.time - b.time)
    const node = Plot.plot({
      width,
      height: PANEL_HEIGHT,
      marginTop: 8,
      marginBottom: 22,
      marginLeft: 46,
      marginRight: 12,
      style: { background: 'transparent', color: AXIS, fontSize: '10px', fontFamily: MONO },
      x: { label: null, tickSize: 2, tickPadding: 4, ticks: 6 },
      y: {
        label: null,
        tickSize: 2,
        tickPadding: 4,
        ticks: 5,
        tickFormat: (d: number) => fmtTick(d),
        grid: true,
      },
      marks: [
        Plot.areaY(pts, { x: 'time', y1: 'q05', y2: 'q95', fill: BAND.band90, fillOpacity: 0.6 }),
        Plot.areaY(pts, { x: 'time', y1: 'q25', y2: 'q75', fill: BAND.bandIqr, fillOpacity: 0.55 }),
        Plot.line(pts, { x: 'time', y: 'q50', stroke: BAND.median, strokeWidth: 1.25 }),
        Plot.ruleY([0], { stroke: '#e5e5e5', strokeWidth: 0.5 }),
      ],
    })
    el.replaceChildren(node)
    return () => {
      node.remove()
    }
  }, [points, width])

  return (
    <div className="border-t border-neutral-100 px-3 py-2">
      <div className="font-mono text-[10px] text-neutral-500">{title}</div>
      <div
        ref={ref}
        className="mt-1 w-full min-w-0 overflow-x-auto"
        style={{ minHeight: PANEL_HEIGHT }}
        role="img"
        aria-label={title}
      />
    </div>
  )
}

function SeriesQuantity({ runId, q }: { runId: string; q: QuantityInfo }) {
  const { data, isPending, isError } = useQuantitySeries(runId, q.name)
  const tag = sourceTag(q.source)

  // One panel per stratum cell (none → a single panel).
  const strata = useMemo(() => {
    if (!data) return []
    const groups = new Map<string, { stratum: Record<string, string>; points: QuantityBandPoint[] }>()
    for (const p of data.points) {
      const key = JSON.stringify(p.stratum)
      const g = groups.get(key)
      if (g) g.points.push(p)
      else groups.set(key, { stratum: p.stratum, points: [p] })
    }
    return [...groups.values()]
  }, [data])

  return (
    <Card className="overflow-hidden">
      <div className="flex items-baseline gap-2 px-3 py-2">
        <span className="font-mono text-sm font-semibold text-neutral-900">{q.name}</span>
        {tag && (
          <span className="font-mono text-[10px] uppercase tracking-wide text-neutral-400">
            {tag}
          </span>
        )}
        <span className="font-mono text-[10px] text-neutral-400">banded over draws</span>
      </div>
      {isPending && <ForestSkeleton rows={1} />}
      {isError && (
        <MutedNotice
          bordered={false}
          title="Couldn't load this quantity"
          detail="The backend returned an error reading its TSV."
        />
      )}
      {data &&
        strata.map((s) => (
          <BandPanel
            key={JSON.stringify(s.stratum)}
            title={stratumLabel(s.stratum) || 'all'}
            points={s.points}
          />
        ))}
    </Card>
  )
}

// ── Scalar quantities — one censoring-aware table ───────────────────────────

function ScalarBand({
  q50,
  q05,
  q95,
}: {
  q50: number | null | undefined
  q05: number | null | undefined
  q95: number | null | undefined
}) {
  if (q50 == null) {
    return <span className="text-neutral-400">— censored —</span>
  }
  return (
    <span>
      <span className="font-semibold text-neutral-900">{fmtValue(q50)}</span>{' '}
      <span className="text-neutral-500">
        [{fmtValue(q05)}, {fmtValue(q95)}]
      </span>
    </span>
  )
}

function ScalarRow({ r, hasStrata }: { r: QuantityScalarRow; hasStrata: boolean }) {
  const tag = sourceTag(r.source)
  const censored =
    r.p_censored == null ? null : Math.round(r.p_censored * 100)
  return (
    <tr className="border-b border-neutral-100 last:border-b-0">
      <td className="px-3 py-2 text-left">
        <span className="font-semibold text-neutral-900">{r.name}</span>
        {tag && (
          <span className="ml-2 font-mono text-[10px] uppercase tracking-wide text-neutral-400">
            {tag}
          </span>
        )}
      </td>
      <td className="px-2 py-2 text-left text-neutral-500">{r.reduce ?? '—'}</td>
      {hasStrata && (
        <td className="px-2 py-2 text-left text-neutral-600">
          {stratumLabel(r.stratum) || '—'}
        </td>
      )}
      <td className="px-3 py-2 text-right">
        <ScalarBand q50={r.q50} q05={r.q05} q95={r.q95} />
      </td>
      <td
        className={cn(
          'px-3 py-2 text-right',
          censored && censored > 0 ? 'text-amber-600' : 'text-neutral-400',
        )}
      >
        {censored == null ? '—' : `${censored}%`}
      </td>
    </tr>
  )
}

function ScalarTable({ runId }: { runId: string }) {
  const { data, isPending, isError } = useQuantityScalars(runId)
  const hasStrata = useMemo(
    () => (data?.rows ?? []).some((r) => Object.keys(r.stratum).length > 0),
    [data],
  )

  if (isPending) return <ForestSkeleton rows={2} />
  if (isError)
    return (
      <MutedNotice
        bordered={false}
        title="Couldn't load the scalar quantities"
        detail="The backend returned an error reading the quantities TSVs."
      />
    )
  if (!data || data.rows.length === 0) return null

  return (
    <Card className="overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full border-collapse font-mono text-[12px] tabular-nums">
          <thead>
            <tr className="border-b border-neutral-200 text-[10px] uppercase tracking-wide text-neutral-400">
              <th className="px-3 py-2 text-left font-medium">Quantity</th>
              <th className="px-2 py-2 text-left font-medium">reduce</th>
              {hasStrata && <th className="px-2 py-2 text-left font-medium">stratum</th>}
              <th className="px-3 py-2 text-right font-medium">median [90%]</th>
              <th className="px-3 py-2 text-right font-medium">censored</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <ScalarRow
                key={`${r.name}-${JSON.stringify(r.stratum)}`}
                r={r}
                hasStrata={hasStrata}
              />
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

// ── Tab ─────────────────────────────────────────────────────────────────────

/**
 * Generated quantities (`camdl fit predict`'s `quantities/` sidecar): named,
 * non-scored reductions of what the model produces, banded over draws. The
 * manifest's `shape` drives the layout — `scalar` quantities (attack rate, peak,
 * time-to-event) collapse into one table up top; `series` quantities (prevalence,
 * Rₑ(t)) each get a banded ribbon below.
 */
export function QuantitiesTab({ runId }: { runId: string }) {
  const run = useRun(runId)
  const quantities = run.data?.available_quantities ?? []
  const series = quantities.filter((q) => q.shape === 'series')
  const scalars = quantities.filter((q) => q.shape === 'scalar')

  if (run.isPending) {
    return (
      <Card className="overflow-hidden">
        <ForestSkeleton rows={2} />
      </Card>
    )
  }

  if (quantities.length === 0) {
    return (
      <MutedNotice
        title="No generated quantities"
        detail={
          <>
            This fit has no <span className="font-mono">quantities</span> sidecar.
            Add a <span className="font-mono">quantities {'{}'}</span> block to the
            model and run <span className="font-mono">camdl fit predict</span>.
          </>
        }
      />
    )
  }

  return (
    <div className="space-y-4">
      {scalars.length > 0 && <ScalarTable runId={runId} />}
      {series.map((q) => (
        <SeriesQuantity key={q.name} runId={runId} q={q} />
      ))}
    </div>
  )
}
