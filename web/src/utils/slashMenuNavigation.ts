export function moveSlashMenuSelection(currentIndex: number, itemCount: number, direction: 1 | -1): number {
  if (itemCount <= 0) return 0
  const normalized = Math.max(0, Math.min(currentIndex, itemCount - 1))
  return (normalized + direction + itemCount) % itemCount
}
