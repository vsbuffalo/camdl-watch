import { useEffect, useMemo, useRef, useState } from 'react'
import * as Plot from '@observablehq/plot'
import type { ObservedPoint, PredictivePoint } from '@/api/client'
import { usePredictive, useRun } from '@/api/queries'
import { ForestSkeleton, MutedNotice } from '@/components/States'
import { Card } from '@/components/ui/card'
import { fmtTick } from '@/lib/format'
import { cn } from '@/lib/utils'

/**
 * Per-horizon ribbon ink. Multiple forecast horizons overlay in one panel, so
 * each gets its own hue (nested 90% → IQR bands + a median line) and the bands
 * are drawn semi-transparent so overlap blends legibly. `free_forward` reads
 * blue, `one_step` green; anything else falls back to neutral grey.
 */
const HORIZON_INK: Record<
  string,
  { band90: string; bandIqr: string; median: string }
> = {
  free_forward: { band90: '#dbeafe', bandIqr: '#93c5fd', median: '#2563eb' },
  one_step: { band90: '#dcfce7', bandIqr: '#86efac', median: '#16a34a' },
}
const HORIZON_FALLBACK = {
  band90: '#ececec', // neutral 90% band
  bandIqr: '#d4d4d4', // neutral IQR band (neutral-300)
  median: '#737373', // neutral-500 median
} as const

function horizonInk(h: string) {
  return HORIZON_INK[h] ?? HORIZON_FALLBACK
}

const BAND_OPACITY = 0.5 // semi-transparent so two overlaid horizons blend

/**
 * Observed data is the thing being checked against every forecast, so it stays
 * a single neutral-dark series — distinct from all of the coloured predictions.
 */
const OBSERVED = '#171717' // neutral-900
const AXIS = '#737373' // neutral-500 — tick labels

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
  const parts = Object.entries(stratum).map(([k, v]) => `${k}=${v}`)
  return parts.join(' · ')
}

/** One forecast horizon's ribbon points (already filtered to this stratum). */
type HorizonSeries = { horizon: string; pred: PredictivePoint[] }

/**
 * One stratum's posterior-predictive check. Each checked horizon draws its own
 * colour-coded 90%/IQR ribbon (semi-transparent, so overlaps blend) and median
 * line; the observed series is drawn once, in neutral-dark, as a dot + faint
 * connecting line (nulls skipped). Self-measuring (seeded synchronously so it
 * draws under headless capture) like the other plots.
 */
function PredictivePanel({
  title,
  series,
  observed,
}: {
  title: string
  series: HorizonSeries[]
  observed: ObservedPoint[]
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

    // Areas/lines connect in data order — sort by time. Observed skips holes.
    const obs = observed
      .filter((o) => o.value != null && Number.isFinite(o.value))
      .sort((a, b) => a.time - b.time)

    // One band-pair + median per checked horizon; then the shared observed.
    const marks: Plot.Markish[] = []
    for (const hs of series) {
      const ink = horizonInk(hs.horizon)
      const pred = [...hs.pred].sort((a, b) => a.time - b.time)
      marks.push(
        Plot.areaY(pred, {
          x: 'time',
          y1: 'q05',
          y2: 'q95',
          fill: ink.band90,
          fillOpacity: BAND_OPACITY,
        }),
        Plot.areaY(pred, {
          x: 'time',
          y1: 'q25',
          y2: 'q75',
          fill: ink.bandIqr,
          fillOpacity: BAND_OPACITY,
        }),
        Plot.line(pred, {
          x: 'time',
          y: 'q50',
          stroke: ink.median,
          strokeWidth: 1.25,
        }),
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
      style: {
        background: 'transparent',
        color: AXIS,
        fontSize: '10px',
        fontFamily: MONO,
      },
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
  }, [series, observed, width])

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

/**
 * Flat, mono checkbox group — multi-select horizons that overlay in the panel.
 * Matches the terminal register: a dark accent tick, mono labels, the checked
 * label darkened.
 */
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

/** Mono swatch legend mapping each checked horizon (+ observed) to its colour. */
function HorizonLegend({ horizons }: { horizons: readonly string[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px] text-neutral-400">
      {horizons.map((h) => (
        <span key={h} className="flex items-center gap-1">
          <span
            className="inline-block h-2 w-3 rounded-[1px]"
            style={{ background: horizonInk(h).median }}
          />
          {h || '∅'}
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

  // Horizons are multi-select (checkboxes) so several forecasts can overlay.
  // `selected === null` means "use the default": ALL horizons on (so a fit's
  // free_forward + one_step show overlaid out of the box). Treatment stays
  // single-select and only surfaces when ambiguous.
  const [selected, setSelected] = useState<readonly string[] | null>(null)
  const [treatment, setTreatment] = useState<string>()

  const horizons = data?.horizons ?? []
  const selectedHorizons = useMemo(() => {
    const set = new Set(selected ?? horizons)
    // Canonical `horizons` order keeps draw order + legend order stable.
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

  // Group the checked horizons' (and treatment's) predictive points by stratum;
  // one panel per stratum, each panel overlaying every checked horizon. Observed
  // is horizon-agnostic, indexed by the same stratum key.
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
        byHorizon: Map<string, PredictivePoint[]>
      }
    >()
    for (const p of data.predictive) {
      if (!wanted.has(p.horizon)) continue
      if (needTreatment && p.treatment !== activeTreatment) continue
      const key = JSON.stringify(p.stratum)
      let g = groups.get(key)
      if (!g) {
        g = { key, stratum: p.stratum, byHorizon: new Map() }
        groups.set(key, g)
      }
      const arr = g.byHorizon.get(p.horizon)
      if (arr) arr.push(p)
      else g.byHorizon.set(p.horizon, [p])
    }

    return [...groups.values()].map((g) => ({
      key: g.key,
      stratum: g.stratum,
      series: selectedHorizons
        .filter((h) => g.byHorizon.has(h))
        .map((h) => ({ horizon: h, pred: g.byHorizon.get(h)! })),
      obs: obsByKey.get(g.key) ?? [],
    }))
  }, [data, selectedHorizons, needTreatment, activeTreatment])

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
        {horizons.length > 0 && (
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
        {selectedHorizons.length > 0 && (
          <HorizonLegend horizons={selectedHorizons} />
        )}
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
          />
        )
      })}
    </Card>
  )
}
