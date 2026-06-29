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
import { buildScenarioColors, SCENARIO_REFERENCE } from '@/lib/scenario'
import { cn } from '@/lib/utils'

const AXIS = '#737373'
const PANEL_HEIGHT = 190
const MONO = 'var(--font-mono)'

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

/** A small scenario swatch + name — the shared legend/chip ink. */
function ScenarioChip({ scenario, color }: { scenario: string; color: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className="inline-block size-2 shrink-0 rounded-[1px]"
        style={{ background: color }}
        aria-hidden
      />
      <span className="text-neutral-600">{scenario}</span>
    </span>
  )
}

// ── Series quantities — scenario-overlaid banded ribbons ────────────────────

interface ScenarioSeries {
  scenario: string
  color: string
  points: QuantityBandPoint[]
}

/** One stratum's banded trajectory, overlaid by scenario. A lone scenario gets
 *  the full 90%/IQR ribbon; multiple scenarios get a faint 90% band + a colored
 *  median line each (so 5 arms stay legible). */
function BandPanel({ title, series }: { title: string; series: ScenarioSeries[] }) {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  const solo = series.length === 1

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
    const marks: Plot.Markish[] = []
    for (const s of series) {
      const pts = [...s.points].sort((a, b) => a.time - b.time)
      if (solo) {
        marks.push(
          Plot.areaY(pts, { x: 'time', y1: 'q05', y2: 'q95', fill: s.color, fillOpacity: 0.16 }),
          Plot.areaY(pts, { x: 'time', y1: 'q25', y2: 'q75', fill: s.color, fillOpacity: 0.22 }),
        )
      } else {
        marks.push(
          Plot.areaY(pts, { x: 'time', y1: 'q05', y2: 'q95', fill: s.color, fillOpacity: 0.1 }),
        )
      }
      marks.push(Plot.line(pts, { x: 'time', y: 'q50', stroke: s.color, strokeWidth: 1.3 }))
    }
    marks.push(Plot.ruleY([0], { stroke: '#e5e5e5', strokeWidth: 0.5 }))

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
      marks,
    })
    el.replaceChildren(node)
    return () => {
      node.remove()
    }
  }, [series, width, solo])

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

function SeriesQuantity({
  runId,
  q,
  colorOf,
}: {
  runId: string
  q: QuantityInfo
  colorOf: (scenario: string) => string
}) {
  const { data, isPending, isError } = useQuantitySeries(runId, q.name)
  const tag = sourceTag(q.source)

  // One panel per stratum cell; within a panel, one ribbon per scenario.
  const panels = useMemo(() => {
    if (!data) return []
    const byStratum = new Map<
      string,
      { stratum: Record<string, string>; byScenario: Map<string, QuantityBandPoint[]> }
    >()
    for (const p of data.points) {
      const key = JSON.stringify(p.stratum)
      let g = byStratum.get(key)
      if (!g) {
        g = { stratum: p.stratum, byScenario: new Map() }
        byStratum.set(key, g)
      }
      const arr = g.byScenario.get(p.scenario)
      if (arr) arr.push(p)
      else g.byScenario.set(p.scenario, [p])
    }
    const order = data.scenarios.length ? data.scenarios : ['as_fitted']
    return [...byStratum.values()].map((g) => ({
      stratum: g.stratum,
      series: order
        .filter((s) => g.byScenario.has(s))
        .map((s) => ({ scenario: s, color: colorOf(s), points: g.byScenario.get(s)! })),
    }))
  }, [data, colorOf])

  const hasSymbol = Boolean(q.symbol && q.symbol !== q.name)
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 px-3 py-2">
        <span className="text-sm font-semibold text-neutral-900">
          {q.symbol ?? q.name}
        </span>
        {hasSymbol && (
          <span className="font-mono text-[11px] font-medium text-neutral-400">
            {q.name}
          </span>
        )}
        {tag && (
          <span className="font-mono text-[10px] uppercase tracking-wide text-neutral-400">
            {tag}
          </span>
        )}
        {q.description ? (
          <span className="text-xs font-medium text-neutral-500" title={q.description}>
            {q.description}
          </span>
        ) : (
          <span className="font-mono text-[10px] text-neutral-400">banded over draws</span>
        )}
        {q.reference && (
          <span className="ml-auto hidden shrink-0 text-[11px] italic text-neutral-400 sm:inline">
            {q.reference}
          </span>
        )}
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
        panels.map((p) => (
          <BandPanel
            key={JSON.stringify(p.stratum)}
            title={stratumLabel(p.stratum) || 'all'}
            series={p.series}
          />
        ))}
    </Card>
  )
}

// ── Scalar quantities — one censoring-aware table, faceted by scenario ──────

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

function ScalarTable({
  runId,
  showScenario,
  colorOf,
  infoOf,
}: {
  runId: string
  showScenario: boolean
  colorOf: (scenario: string) => string
  infoOf: Map<string, QuantityInfo>
}) {
  const { data, isPending, isError } = useQuantityScalars(runId)
  const hasStrata = useMemo(
    () => (data?.rows ?? []).some((r) => Object.keys(r.stratum).length > 0),
    [data],
  )

  // Group rows by quantity (the name shows once per group), preserving order.
  const groups = useMemo(() => {
    const m = new Map<string, QuantityScalarRow[]>()
    for (const r of data?.rows ?? []) {
      const arr = m.get(r.name)
      if (arr) arr.push(r)
      else m.set(r.name, [r])
    }
    return [...m.entries()]
  }, [data])

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
              {showScenario && <th className="px-2 py-2 text-left font-medium">scenario</th>}
              <th className="px-2 py-2 text-left font-medium">reduce</th>
              {hasStrata && <th className="px-2 py-2 text-left font-medium">stratum</th>}
              <th className="px-3 py-2 text-right font-medium">median [90%]</th>
              <th className="px-3 py-2 text-right font-medium">censored</th>
            </tr>
          </thead>
          <tbody>
            {groups.map(([name, rows]) =>
              rows.map((r, i) => {
                const censored = r.p_censored == null ? null : Math.round(r.p_censored * 100)
                const first = i === 0
                return (
                  <tr
                    key={`${name}-${r.scenario}-${JSON.stringify(r.stratum)}`}
                    className={cn(first && 'border-t border-neutral-100')}
                  >
                    <td className="px-3 py-1.5 text-left align-top">
                      {first &&
                        (() => {
                          const info = infoOf.get(name)
                          const hasSymbol = Boolean(info?.symbol && info.symbol !== name)
                          return (
                            <>
                              <div className="flex items-baseline gap-1.5">
                                <span className="font-semibold text-neutral-900">
                                  {info?.symbol ?? name}
                                </span>
                                {hasSymbol && (
                                  <span className="font-mono text-[10px] text-neutral-400">
                                    {name}
                                  </span>
                                )}
                                {sourceTag(r.source) && (
                                  <span className="font-mono text-[10px] uppercase tracking-wide text-neutral-400">
                                    {sourceTag(r.source)}
                                  </span>
                                )}
                              </div>
                              {info?.description && (
                                <div
                                  className="mt-0.5 max-w-[20rem] truncate text-[11px] font-normal text-neutral-500"
                                  title={info.description}
                                >
                                  {info.description}
                                </div>
                              )}
                            </>
                          )
                        })()}
                    </td>
                    {showScenario && (
                      <td className="px-2 py-1.5 text-left">
                        <ScenarioChip scenario={r.scenario} color={colorOf(r.scenario)} />
                      </td>
                    )}
                    <td className="px-2 py-1.5 text-left text-neutral-500">
                      {first ? (r.reduce ?? '—') : ''}
                    </td>
                    {hasStrata && (
                      <td className="px-2 py-1.5 text-left text-neutral-600">
                        {stratumLabel(r.stratum) || '—'}
                      </td>
                    )}
                    <td className="px-3 py-1.5 text-right">
                      <ScalarBand q50={r.q50} q05={r.q05} q95={r.q95} />
                    </td>
                    <td
                      className={cn(
                        'px-3 py-1.5 text-right',
                        censored && censored > 0 ? 'text-amber-600' : 'text-neutral-400',
                      )}
                    >
                      {censored == null ? '—' : `${censored}%`}
                    </td>
                  </tr>
                )
              }),
            )}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

// ── Tab ─────────────────────────────────────────────────────────────────────

/**
 * Generated quantities (`camdl fit predict`'s `quantities/` sidecar): named,
 * non-scored reductions of what the model produces, banded over draws and — for
 * a scenario-aware predict — overlaid by scenario. The manifest's `shape` drives
 * the layout: `scalar` quantities collapse into one table (a row per scenario),
 * `series` quantities each get a scenario-overlaid ribbon.
 */
export function QuantitiesTab({ runId }: { runId: string }) {
  const run = useRun(runId)
  const quantities = run.data?.available_quantities ?? []
  const scenarios = run.data?.quantity_scenarios ?? []
  const series = quantities.filter((q) => q.shape === 'series')
  const scalars = quantities.filter((q) => q.shape === 'scalar')

  const colorMap = useMemo(() => buildScenarioColors(scenarios), [scenarios])
  const colorOf = (s: string) => colorMap.get(s) ?? SCENARIO_REFERENCE
  const showScenario = scenarios.length > 1
  const infoOf = useMemo(
    () => new Map(quantities.map((q) => [q.name, q])),
    [quantities],
  )

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
      {showScenario && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-1 font-mono text-[11px]">
          <span className="text-[10px] uppercase tracking-wide text-neutral-400">
            Scenarios
          </span>
          {scenarios.map((s) => (
            <ScenarioChip key={s} scenario={s} color={colorOf(s)} />
          ))}
        </div>
      )}
      {scalars.length > 0 && (
        <ScalarTable
          runId={runId}
          showScenario={showScenario}
          colorOf={colorOf}
          infoOf={infoOf}
        />
      )}
      {series.map((q) => (
        <SeriesQuantity key={q.name} runId={runId} q={q} colorOf={colorOf} />
      ))}
    </div>
  )
}
