import { apiFetch } from '../lib/apiClient'
import type { TaxonomyInterestOption, TaxonomyTreeItem } from '../types'

interface BackendTaxonomyTreeItem {
  id: string
  name: string
  slug: string
  path: string
  depth: number
  description: string | null
  is_system: boolean
  is_archived: boolean
  children?: BackendTaxonomyTreeItem[]
}

interface InitializeTaxonomyPayload {
  interestSlugs: string[]
  customDescription: string
}

function mapTreeItem(item: BackendTaxonomyTreeItem): TaxonomyTreeItem {
  return {
    id: item.id,
    name: item.name,
    slug: item.slug,
    path: item.path,
    depth: item.depth,
    description: item.description,
    isSystem: item.is_system,
    isArchived: item.is_archived,
    children: (item.children ?? []).map(mapTreeItem),
  }
}

export async function fetchTaxonomyTree(): Promise<TaxonomyTreeItem[]> {
  const res = await apiFetch('/api/v1/taxonomy/categories/tree')
  if (!res.ok) throw new Error('Failed to fetch taxonomy tree')
  const data: BackendTaxonomyTreeItem[] = await res.json()
  return data.map(mapTreeItem)
}

export async function fetchTaxonomyInterestOptions(): Promise<TaxonomyInterestOption[]> {
  const res = await apiFetch('/api/v1/taxonomy/interest-options')
  if (!res.ok) throw new Error('Failed to fetch taxonomy interest options')
  return res.json()
}

export async function initializeTaxonomyFromInterests(payload: InitializeTaxonomyPayload) {
  const res = await apiFetch('/api/v1/taxonomy/initialize/interests', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      interest_slugs: payload.interestSlugs,
      custom_description: payload.customDescription.trim() || null,
    }),
  })
  if (!res.ok) throw new Error('Failed to initialize taxonomy')
  return res.json()
}
