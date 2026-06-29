/**
 * Shared scenario ink — keeps the scenario overlay colors consistent across the
 * Quantities table/ribbons and the Predictive ribbons. `baseline` / `as_fitted`
 * are the dark *reference* arm; intervention scenarios get distinct hues.
 */
export const SCENARIO_REFERENCE = '#171717' // neutral-900

const PALETTE = [
  '#1d4ed8', '#b45309', '#047857', '#be123c',
  '#6d28d9', '#0e7490', '#a16207', '#9f1239',
] as const

/** Stable scenario→color, assigned in the given order. */
export function buildScenarioColors(scenarios: string[]): Map<string, string> {
  const m = new Map<string, string>()
  let i = 0
  for (const s of scenarios) {
    if (s === 'baseline' || s === 'as_fitted') m.set(s, SCENARIO_REFERENCE)
    else m.set(s, PALETTE[i++ % PALETTE.length]!)
  }
  return m
}
