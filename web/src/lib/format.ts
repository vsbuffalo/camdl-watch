/**
 * Display formatting helpers. These never *compute* statistics — every number
 * shown is shipped authoritative from the Python core; we only render it.
 */

function trimZeros(s: string): string {
  if (!s.includes('.')) return s
  return s.replace(/\.?0+$/, '')
}

/**
 * Format a posterior summary value with magnitude-aware precision. Small/huge
 * magnitudes fall back to scientific notation so a forest readout never shows
 * a wall of zeros.
 */
export function fmtValue(x: number | null | undefined): string {
  if (x == null || !Number.isFinite(x)) return '—'
  const a = Math.abs(x)
  if (a !== 0 && (a < 1e-3 || a >= 1e5)) return x.toExponential(2)
  let decimals: number
  if (a >= 100) decimals = 1
  else if (a >= 10) decimals = 2
  else decimals = 3
  return trimZeros(x.toFixed(decimals))
}

/** Compact form for axis ticks: a touch coarser than {@link fmtValue}. */
export function fmtTick(x: number): string {
  if (!Number.isFinite(x)) return ''
  const a = Math.abs(x)
  if (a !== 0 && (a < 1e-3 || a >= 1e4)) return x.toExponential(1)
  let decimals: number
  if (a >= 100) decimals = 0
  else if (a >= 10) decimals = 1
  else decimals = 2
  return trimZeros(x.toFixed(decimals))
}

/** R-hat to three decimals; the convergence threshold lives in the caller. */
export function fmtRhat(x: number | null | undefined): string {
  if (x == null || !Number.isFinite(x)) return '—'
  return x.toFixed(3)
}

/** Effective sample size as a rounded integer. */
export function fmtEss(x: number | null | undefined): string {
  if (x == null || !Number.isFinite(x)) return '—'
  return Math.round(x).toLocaleString()
}
