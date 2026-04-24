const PALETTE: Array<{ bg: string; text: string }> = [
  { bg: 'rgba(99,  102, 241, 0.18)', text: '#818cf8' }, // indigo
  { bg: 'rgba(236, 72,  153, 0.18)', text: '#f472b6' }, // pink
  { bg: 'rgba(34,  197, 94,  0.18)', text: '#4ade80' }, // green
  { bg: 'rgba(251, 146, 60,  0.18)', text: '#fb923c' }, // orange
  { bg: 'rgba(20,  184, 166, 0.18)', text: '#2dd4bf' }, // teal
  { bg: 'rgba(168, 85,  247, 0.18)', text: '#c084fc' }, // purple
  { bg: 'rgba(239, 68,  68,  0.18)', text: '#f87171' }, // red
  { bg: 'rgba(234, 179, 8,   0.18)', text: '#facc15' }, // yellow
  { bg: 'rgba(56,  189, 248, 0.18)', text: '#38bdf8' }, // sky
]

function hash(name: string): number {
  let h = 0
  for (let i = 0; i < name.length; i++) {
    h = (h * 31 + name.charCodeAt(i)) & 0xffff
  }
  return h
}

export function getTagColor(name: string) {
  return PALETTE[hash(name) % PALETTE.length]
}
