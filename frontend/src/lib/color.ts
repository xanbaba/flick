export function oklchToRgb(L: number, C: number, h: number): [number, number, number] {
  const a = C * Math.cos((h * Math.PI) / 180)
  const b = C * Math.sin((h * Math.PI) / 180)
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3
  const lin = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ]
  return lin.map((x) => {
    const c = Math.max(0, Math.min(1, x))
    return Math.round(255 * (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055))
  }) as [number, number, number]
}

export const hex = (L: number, C: number, h: number): string =>
  '#' +
  oklchToRgb(L, C, h)
    .map((v) => v.toString(16).padStart(2, '0'))
    .join('')

export const KIND_OKLCH: Record<string, [number, number, number]> = {
  Person: [0.8, 0.13, 25],
  Place: [0.78, 0.11, 250],
  Thing: [0.85, 0.12, 95],
  Activity: [0.76, 0.13, 305],
  Need: [0.8, 0.14, 60],
  Memory: [0.8, 0.1, 200],
}

export const KIND_HEX: Record<string, string> = Object.fromEntries(
  Object.entries(KIND_OKLCH).map(([k, v]) => [k, hex(...v)]),
)

export const ACCENT_HEX = hex(0.87, 0.17, 158)

export const CHANNELS = ['O1', 'Oz', 'O2', 'POz', 'PO3', 'PO4', 'Pz', 'CPz']
export const CHANNEL_COLORS = [25, 55, 85, 120, 155, 190, 220, 250].map((h) => hex(0.78, 0.1, h))
