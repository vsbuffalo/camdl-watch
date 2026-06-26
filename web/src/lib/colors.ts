/**
 * Subtle categorical palette for chains — muted 700-ish hues, not a rainbow.
 * Shared so every chain-coloured view (the pair-plot scatter, the trace grid)
 * agrees on which colour is which chain. At low opacity these read as quiet
 * tints; the point is to *detect* separation between chains (poor mixing), not
 * to dazzle.
 */
export const CHAIN_COLORS = [
  '#475569', // slate-600
  '#0f766e', // teal-700
  '#b45309', // amber-700
  '#9f1239', // rose-800
  '#4338ca', // indigo-700
  '#15803d', // green-700
  '#7e22ce', // purple-700
  '#a16207', // yellow-700
] as const
