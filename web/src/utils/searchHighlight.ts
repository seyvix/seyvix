import type { SearchHighlightRange, SearchMatch } from '../types'

export function normalizedHighlightRanges(match: SearchMatch): SearchHighlightRange[] {
  const ranges = match.highlightRanges ?? match.highlight_ranges ?? []
  return [...ranges]
    .filter(range => range.start >= 0 && range.end > range.start && range.end <= match.text.length)
    .sort((left, right) => left.start - right.start)
}
