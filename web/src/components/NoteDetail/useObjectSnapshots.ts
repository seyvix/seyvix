import { useEffect, useMemo, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchSnapshotArtifacts, fetchSnapshotJobs, type SnapshotArtifact, type SnapshotJob } from '../../api/enrichment'
import type { NoteObject, SnapshotView } from '../../types'
import { isActiveJob, isFinishedJob, JOB_PROGRESS_POLL_MS } from './format'

export type AssetViewKind = 'markdown' | 'pdf' | 'webpage_html'
export type AssetView = SnapshotView & { kind: AssetViewKind }

function isAssetView(view: SnapshotView): view is AssetView {
  return view.kind === 'markdown' || view.kind === 'pdf' || view.kind === 'webpage_html'
}

/** Convert supported artifact types to viewer tabs; unknown types remain non-rendered. */
function artifactView(artifact: SnapshotArtifact): AssetView | null {
  if (artifact.status !== 'ready') return null
  switch (artifact.artifact_type) {
    case 'markdown': return { kind: 'markdown', label: 'Текст', url: artifact.url }
    case 'pdf': return { kind: 'pdf', label: 'PDF', url: artifact.url }
    case 'webpage_html': return { kind: 'webpage_html', label: 'Website', url: artifact.url }
    default: return null
  }
}

export interface ObjectSnapshots {
  views: AssetView[]
  jobs: SnapshotJob[]
}

/**
 * Snapshot jobs/artifacts of one object. Both queries are per note (shared by all objects).
 * Job progress polls slowly only while a job is pending/processing; finished results arrive
 * through the change feed, and a job finishing here refreshes the artifacts once.
 */
export function useObjectSnapshots(obj: NoteObject, noteId: string, enabled: boolean): ObjectSnapshots {
  const queryClient = useQueryClient()
  const jobsQuery = useQuery({
    queryKey: ['snapshot-jobs', noteId],
    queryFn: () => fetchSnapshotJobs(noteId),
    enabled,
    refetchInterval: query => (query.state.data?.some(isActiveJob) ? JOB_PROGRESS_POLL_MS : false),
  })
  const artifactsQuery = useQuery({
    queryKey: ['snapshot-artifacts', noteId],
    queryFn: () => fetchSnapshotArtifacts(noteId),
    enabled,
  })

  const jobs = useMemo(
    () => (jobsQuery.data ?? []).filter(job => job.source_asset_id === obj.id),
    [jobsQuery.data, obj.id],
  )

  const views = useMemo(() => {
    const byKind = new Map<AssetViewKind, AssetView>()
    for (const view of obj.snapshotViews ?? []) {
      if (isAssetView(view)) byKind.set(view.kind, view)
    }
    for (const artifact of artifactsQuery.data ?? []) {
      if (artifact.source_asset_id !== obj.id) continue
      const view = artifactView(artifact)
      if (view) byKind.set(view.kind, view)
    }
    return Array.from(byKind.values())
  }, [artifactsQuery.data, obj.id, obj.snapshotViews])

  // React to active → finished transitions only (not to every refetch of an already-finished job).
  const activeJobIdsRef = useRef(new Set<string>())
  useEffect(() => {
    const previouslyActive = activeJobIdsRef.current
    const justFinished = jobs.some(job => previouslyActive.has(job.id) && isFinishedJob(job))
    activeJobIdsRef.current = new Set(jobs.filter(isActiveJob).map(job => job.id))
    if (!justFinished) return
    queryClient.invalidateQueries({ queryKey: ['snapshot-artifacts', noteId] })
    queryClient.invalidateQueries({ queryKey: ['note'] })
  }, [jobs, noteId, queryClient])

  return { views, jobs }
}
