export interface OrderedNoteRef {
  id: string
  slug: string
  estimatedHeight?: number
}

export interface ReorderPayloadItem {
  slug: string
  position: number
}

export interface MasonryGridMetrics {
  cols: number
  itemWidth: number
  contentWidth: number
}

export interface MasonryColumnPickerState {
  activeCols: number
  maxSelectableCols: number
}

export interface MasonryLayoutInput {
  heights: readonly number[]
  cols: number
  itemWidth: number
  gap: number
}

export interface MasonryLayoutResult {
  slots: number[]
  height: number
}

const MIN_READABLE_CARD_WIDTH = 156
const MOBILE_MAX_CARD_WIDTH = 420
const GRID_GAP = 8
const DESKTOP_PADDING = 32
const MOBILE_PADDING = 24

export function orderNotesByIds<T extends OrderedNoteRef>(
  notes: readonly T[],
  orderedIds: readonly string[],
): T[] {
  const notesById = new Map(notes.map(note => [note.id, note]))
  const usedIds = new Set<string>()
  const next: T[] = []

  for (const id of orderedIds) {
    const note = notesById.get(id)
    if (!note || usedIds.has(id)) continue
    next.push(note)
    usedIds.add(id)
  }

  for (const note of notes) {
    if (!usedIds.has(note.id)) next.push(note)
  }

  return next
}

export function toReorderPayload(notes: readonly OrderedNoteRef[]): ReorderPayloadItem[] {
  return notes.map((note, index) => ({
    slug: note.slug,
    position: (index + 1) * 10,
  }))
}

export function calculateMasonryGridMetrics(containerWidth: number, requestedCols: number): MasonryGridMetrics {
  const padding = containerWidth <= 640 ? MOBILE_PADDING : DESKTOP_PADDING
  const availableWidth = Math.max(160, containerWidth - padding)
  if (containerWidth <= 640) {
    const requestedMobileCols = Math.max(1, Math.min(3, Math.floor(requestedCols)))
    const maxColumnsByWidth = Math.max(
      1,
      Math.floor((availableWidth + GRID_GAP) / (MIN_READABLE_CARD_WIDTH + GRID_GAP)),
    )
    const cols = Math.max(1, Math.min(requestedMobileCols, maxColumnsByWidth))
    const itemWidth = cols === 1
      ? Math.min(MOBILE_MAX_CARD_WIDTH, availableWidth)
      : Math.floor((availableWidth - GRID_GAP * (cols - 1)) / cols)
    const contentWidth = itemWidth * cols + GRID_GAP * (cols - 1)
    return { cols, itemWidth, contentWidth }
  }

  const minCardWidth = Math.min(MIN_READABLE_CARD_WIDTH, availableWidth)
  const maxColumnsByWidth = Math.max(1, Math.floor((availableWidth + GRID_GAP) / (minCardWidth + GRID_GAP)))
  const cols = Math.max(1, Math.min(requestedCols, maxColumnsByWidth))
  const widthFromColumns = Math.floor((availableWidth - GRID_GAP * (cols - 1)) / cols)
  const itemWidth = widthFromColumns
  const contentWidth = itemWidth * cols + GRID_GAP * (cols - 1)

  return { cols, itemWidth, contentWidth }
}

export function calculateMasonryColumnPickerState(
  containerWidth: number,
  requestedCols: number,
  options: readonly number[],
): MasonryColumnPickerState {
  const normalizedOptions = options
    .map(option => Math.floor(option))
    .filter(option => option > 0)

  const maxOption = normalizedOptions.length > 0 ? Math.max(...normalizedOptions) : 1
  const maxSelectableCols = calculateMasonryGridMetrics(containerWidth, maxOption).cols
  const activeCols = calculateMasonryGridMetrics(containerWidth, requestedCols).cols

  return {
    activeCols: Math.max(1, Math.min(activeCols, maxOption)),
    maxSelectableCols: Math.max(1, Math.min(maxSelectableCols, maxOption)),
  }
}

export function buildMasonryLayoutSlots({ heights, cols, itemWidth, gap }: MasonryLayoutInput): MasonryLayoutResult {
  const safeCols = Math.max(1, Math.floor(cols))
  const columnHeights = Array.from({ length: safeCols }, () => 0)
  const slots: number[] = []

  for (const height of heights) {
    let columnIndex = 0
    for (let index = 1; index < columnHeights.length; index += 1) {
      if (columnHeights[index] < columnHeights[columnIndex]) columnIndex = index
    }

    slots.push(columnIndex * (itemWidth + gap), columnHeights[columnIndex])
    columnHeights[columnIndex] += Math.max(0, height) + gap
  }

  return {
    slots,
    height: Math.max(0, ...columnHeights) - (heights.length > 0 ? gap : 0),
  }
}
