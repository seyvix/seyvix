import { apiFetch } from '../lib/apiClient.ts'
import { readJson } from '../lib/apiError.ts'
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
  const data = await readJson<BackendTaxonomyTreeItem[]>(res, 'Failed to fetch taxonomy tree')
  return data.map(mapTreeItem)
}

export async function fetchTaxonomyInterestOptions(): Promise<TaxonomyInterestOption[]> {
  const res = await apiFetch('/api/v1/taxonomy/interest-options')
  return readJson<TaxonomyInterestOption[]>(res, 'Failed to fetch taxonomy interest options')
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
  return readJson<unknown>(res, 'Failed to initialize taxonomy')
}
