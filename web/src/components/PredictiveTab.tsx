import { useEffect, useMemo, useRef, useState } from 'react'
import * as Plot from '@observablehq/plot'
import type { ObservedPoint, PredictivePoint } from '@/api/client'
import { usePredictive, useRun } from '@/api/queries'
import { ForestSkeleton, MutedNotice } from '@/components/States'
import { Card } from '@/components/ui/card'
import { fmtTick } from '@/lib/format'
import { buildScenarioColors, SCENARIO_REFERENCE } from '@/lib/scenario'
import { cn } from '@/lib/utils'

// Horizon ink (used when there is no scenario overlay): free_forward reads blue,
// one_step green, anything else neutral.
const HORIZON_MEDIAN: Record<string, string> = {
  free_forward: '#2563eb',
  one_step: '#16a34a',
}
const HORIZON_FALLBACK = '#737373'
const horizonColor = (h: string) => HORIZON_MEDIAN[h] ?? HORIZON_FALLBACK

const OBSERVED = '#171717' // neutral-900 — the data, distinct from every prediction
const AXIS = '#737373'
const PANEL_HEIGHT = 220
const MONO = 'var(--font-mono)'

/** Flat underline segmented control — matches the tab register. */
function Segmented({
  label,
  options,
  value,
  onChange,
}: {
  label: string
  options: readonly string[]
  value: string
  onChange: (v: string) => void
}) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <span className="text-[10px] font-medium uppercase tracking-wider text-neutral-400">
        {label}
      </span>
      <div className="flex flex-wrap items-center gap-3">
        {options.map((opt) => (
          <button
            key={opt}
            type="button"
            onClick={() => onChange(opt)}
            className={cn(
              '-mb-px border-b-2 border-transparent pb-0.5 font-mono text-xs transition-colors',
              opt === value
                ? 'border-neutral-900 text-neutral-900'
                : 'text-neutral-500 hover:text-neutral-800',
            )}
          >
            {opt || '∅'}
          </button>
        ))}
      </div>
    </div>
  )
}

/** Human label for a stratum object — `district=Bombali · age=u5`, or empty. */
function stratumLabel(stratum: Record<string, string>): string {
  return Object.entries(stratum)
    .map(([k, v]) => `${k}=${v}`)
    .join(' · ')
}

/** One overlaid ribbon (a scenario, or a horizon): its color + points. */
type OverlaySeries = { key: string; color: string; pred: PredictivePoint[] }

/**
 * One stratum's posterior-predictive check. Each overlaid arm draws its own
 * color-coded ribbon (90% always, IQR when ≤2 arms so heavy overlap stays
 * legible) + median line; the observed series is drawn once in neutral-dark.
 * Self-measuring like the other plots.
 */
function PredictivePanel({
  title,
  series,
  observed,
  dense,
}: {
  title: string
  series: OverlaySeries[]
  observed: ObservedPoint[]
  dense: boolean
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

    const obs = observed
      .filter((o) => o.value != null && Number.isFinite(o.value))
      .sort((a, b) => a.time - b.time)

    const marks: Plot.Markish[] = []
    for (const s of series) {
      const pred = [...s.pred].sort((a, b) => a.time - b.time)
      marks.push(
        Plot.areaY(pred, {
          x: 'time',
          y1: 'q05',
          y2: 'q95',
          fill: s.color,
          fillOpacity: dense ? 0.16 : 0.1,
        }),
      )
      if (dense) {
        marks.push(
          Plot.areaY(pred, {
            x: 'time',
            y1: 'q25',
            y2: 'q75',
            fill: s.color,
            fillOpacity: 0.24,
          }),
        )
      }
      marks.push(
        Plot.line(pred, { x: 'time', y: 'q50', stroke: s.color, strokeWidth: 1.3 }),
      )
    }
    marks.push(
      Plot.line(obs, {
        x: 'time',
        y: 'value',
        stroke: OBSERVED,
        strokeWidth: 0.75,
        strokeOpacity: 0.4,
      }),
      Plot.dot(obs, {
        x: 'time',
        y: 'value',
        fill: OBSERVED,
        r: 2,
        stroke: 'white',
        strokeWidth: 0.4,
      }),
      Plot.ruleY([0], { stroke: '#e5e5e5', strokeWidth: 0.5 }),
    )

    const node = Plot.plot({
      width,
      height: PANEL_HEIGHT,
      marginTop: 10,
      marginBottom: 24,
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
  }, [series, observed, width, dense])

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

/** Flat, mono checkbox group — multi-select horizons that overlay in the panel. */
function HorizonChecks({
  options,
  selected,
  onToggle,
}: {
  options: readonly string[]
  selected: readonly string[]
  onToggle: (h: string) => void
}) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <span className="text-[10px] font-medium uppercase tracking-wider text-neutral-400">
        Horizon
      </span>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {options.map((opt) => {
          const on = selected.includes(opt)
          return (
            <label
              key={opt}
              className="flex cursor-pointer items-center gap-1.5 font-mono text-xs"
            >
              <input
                type="checkbox"
                checked={on}
                onChange={() => onToggle(opt)}
                className="size-3 accent-neutral-800"
              />
              <span className={on ? 'text-neutral-900' : 'text-neutral-500'}>
                {opt || '∅'}
              </span>
            </label>
          )
        })}
      </div>
    </div>
  )
}

/** Swatch legend mapping each overlaid arm (+ observed) to its colour. */
function Legend({ arms }: { arms: { label: string; color: string }[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px] text-neutral-400">
      {arms.map((a) => (
        <span key={a.label} className="flex items-center gap-1">
          <span
            className="inline-block h-2 w-3 rounded-[1px]"
            style={{ background: a.color }}
          />
          {a.label || '∅'}
        </span>
      ))}
      <span className="flex items-center gap-1">
        <span
          className="inline-block size-2 rounded-full"
          style={{ background: OBSERVED }}
        />
        observed
      </span>
    </div>
  )
}

export function PredictiveTab({ runId }: { runId: string }) {
  const run = useRun(runId)
  const availableStreams = useMemo(
    () => run.data?.available_streams ?? [],
    [run.data],
  )

  const [stream, setStream] = useState<string>()
  const activeStream =
    stream && availableStreams.includes(stream)
      ? stream
      : (availableStreams[0] ?? undefined)

  const { data, isPending, isError, isPlaceholderData } = usePredictive(
    runId,
    activeStream,
  )

  const [selected, setSelected] = useState<readonly string[] | null>(null)
  const [treatment, setTreatment] = useState<string>()

  const horizons = data?.horizons ?? []
  const scenarios = useMemo(() => data?.scenarios ?? [], [data])
  // Color by scenario once there's more than one (the comparison axis); else by
  // horizon, the original behaviour.
  const byScenario = scenarios.length > 1
  const scenarioColors = useMemo(
    () => buildScenarioColors(scenarios),
    [scenarios],
  )

  const selectedHorizons = useMemo(() => {
    const set = new Set(selected ?? horizons)
    return horizons.filter((h) => set.has(h))
  }, [selected, horizons])

  const toggleHorizon = (h: string) =>
    setSelected(
      selectedHorizons.includes(h)
        ? selectedHorizons.filter((x) => x !== h)
        : [...selectedHorizons, h],
    )

  const treatments = data?.treatments ?? []
  const needTreatment = treatments.length > 1
  const activeTreatment =
    treatment && treatments.includes(treatment)
      ? treatment
      : (treatments[0] ?? '')

  // Group the checked predictive points by stratum; within each stratum, one
  // overlaid arm per (scenario, horizon). Colored by scenario when overlaying
  // scenarios, else by horizon.
  const strata = useMemo(() => {
    if (!data) return []
    const obsByKey = new Map<string, ObservedPoint[]>()
    for (const o of data.observed) {
      const key = JSON.stringify(o.stratum)
      const arr = obsByKey.get(key)
      if (arr) arr.push(o)
      else obsByKey.set(key, [o])
    }

    const wanted = new Set(selectedHorizons)
    const groups = new Map<
      string,
      {
        key: string
        stratum: Record<string, string>
        byArm: Map<string, { scenario: string; horizon: string; pred: PredictivePoint[] }>
      }
    >()
    for (const p of data.predictive) {
      if (!wanted.has(p.horizon)) continue
      if (needTreatment && p.treatment !== activeTreatment) continue
      const key = JSON.stringify(p.stratum)
      let g = groups.get(key)
      if (!g) {
        g = { key, stratum: p.stratum, byArm: new Map() }
        groups.set(key, g)
      }
      const armKey = `${p.scenario}|${p.horizon}`
      const arm = g.byArm.get(armKey)
      if (arm) arm.pred.push(p)
      else g.byArm.set(armKey, { scenario: p.scenario, horizon: p.horizon, pred: [p] })
    }

    return [...groups.values()].map((g) => ({
      key: g.key,
      stratum: g.stratum,
      series: [...g.byArm.values()].map((a): OverlaySeries => ({
        key: `${a.scenario}|${a.horizon}`,
        color: byScenario
          ? (scenarioColors.get(a.scenario) ?? SCENARIO_REFERENCE)
          : horizonColor(a.horizon),
        pred: a.pred,
      })),
      obs: obsByKey.get(g.key) ?? [],
    }))
  }, [data, selectedHorizons, needTreatment, activeTreatment, byScenario, scenarioColors])

  // Legend arms: scenarios actually shown (in canonical order) when overlaying
  // scenarios, else the checked horizons.
  const legendArms = useMemo(() => {
    if (byScenario) {
      const shown = new Set<string>()
      for (const s of strata) for (const a of s.series) shown.add(a.key.split('|')[0]!)
      return scenarios
        .filter((sc) => shown.has(sc))
        .map((sc) => ({ label: sc, color: scenarioColors.get(sc) ?? SCENARIO_REFERENCE }))
    }
    return selectedHorizons.map((h) => ({ label: h, color: horizonColor(h) }))
  }, [byScenario, strata, scenarios, scenarioColors, selectedHorizons])

  if (run.isPending) {
    return (
      <Card className="overflow-hidden">
        <ForestSkeleton rows={2} />
      </Card>
    )
  }

  if (availableStreams.length === 0) {
    return (
      <MutedNotice
        title="No predictive artifact"
        detail={
          <>
            Run <span className="font-mono">camdl fit predict</span> for this fit
            to generate posterior-predictive checks.
          </>
        }
      />
    )
  }

  return (
    <Card
      className={cn(
        'overflow-hidden transition-opacity',
        isPlaceholderData && 'opacity-60',
      )}
    >
      <div className="flex flex-col gap-2 px-3 py-2.5">
        {availableStreams.length > 1 && (
          <Segmented
            label="Stream"
            options={availableStreams}
            value={activeStream ?? ''}
            onChange={(v) => {
              setStream(v)
              setSelected(null)
              setTreatment(undefined)
            }}
          />
        )}
        {horizons.length > 1 && (
          <HorizonChecks
            options={horizons}
            selected={selectedHorizons}
            onToggle={toggleHorizon}
          />
        )}
        {needTreatment && (
          <Segmented
            label="Treatment"
            options={treatments}
            value={activeTreatment}
            onChange={setTreatment}
          />
        )}
        {legendArms.length > 0 && <Legend arms={legendArms} />}
      </div>

      {isPending && (
        <div className="border-t border-neutral-100">
          <ForestSkeleton rows={2} />
        </div>
      )}

      {isError && (
        <div className="border-t border-neutral-100">
          <MutedNotice
            bordered={false}
            title="Couldn't load the predictive check"
            detail="The backend returned an error for this stream. The predictive artifact may be missing or still being written."
          />
        </div>
      )}

      {data && strata.length === 0 && !isPending && (
        <div className="border-t border-neutral-100">
          <MutedNotice
            bordered={false}
            title="No predictive points"
            detail="This stream's predictive artifact has no points for the selected horizon(s)."
          />
        </div>
      )}

      {strata.map((s) => {
        const lbl = stratumLabel(s.stratum)
        const title = lbl || activeStream || 'observed'
        return (
          <PredictivePanel
            key={s.key}
            title={title}
            series={s.series}
            observed={s.obs}
            dense={s.series.length <= 2}
          />
        )
      })}
    </Card>
  )
}
