export type DropPlacement = 'before' | 'after'

export function moveSlug(
  slugs: string[],
  sourceSlug: string,
  targetSlug: string,
  placement: DropPlacement,
): string[] {
  if (sourceSlug === targetSlug) return slugs
  const sourceIndex = slugs.indexOf(sourceSlug)
  const targetIndex = slugs.indexOf(targetSlug)
  if (sourceIndex === -1 || targetIndex === -1) return slugs

  const next = slugs.filter(slug => slug !== sourceSlug)
  const targetIndexAfterRemoval = next.indexOf(targetSlug)
  const insertIndex = placement === 'before' ? targetIndexAfterRemoval : targetIndexAfterRemoval + 1
  next.splice(insertIndex, 0, sourceSlug)
  return next
}

export function orderBySlugs<T extends { slug: string }>(items: T[], orderedSlugs: string[]): T[] {
  const bySlug = new Map(items.map(item => [item.slug, item]))
  const ordered = orderedSlugs
    .map(slug => bySlug.get(slug))
    .filter((item): item is T => Boolean(item))
  const orderedSet = new Set(orderedSlugs)
  return [...ordered, ...items.filter(item => !orderedSet.has(item.slug))]
}
