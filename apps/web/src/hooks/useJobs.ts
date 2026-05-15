/**
 * useJobs — manages job list with polling.
 */
import { useState, useEffect, useCallback, useDeferredValue } from 'react'
import axios from 'axios'
import { listJobs, cancelJob, retryJob, deleteJob, uploadJob, uploadJobs, checkHealth } from '@/services/api'
import type { JobListItem, ClipOrderMode, JobFilterStatus } from '@/types'
import { POLLING_INTERVAL_MS } from '@/utils/constants'

function getErrorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
    if (typeof error.message === 'string' && error.message.trim()) return error.message
  }
  if (error instanceof Error && error.message) return error.message
  return fallback
}

export function useJobs() {
  const [jobs, setJobs] = useState<JobListItem[]>([])
  const [hasJobs, setHasJobs] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadFileName, setUploadFileName] = useState<string | null>(null)
  const [clipOrderMode, setClipOrderMode] = useState<ClipOrderMode>('timeline')
  const [clipOrderModeTouched, setClipOrderModeTouched] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const deferredSearchQuery = useDeferredValue(searchQuery)
  const [statusFilter, setStatusFilter] = useState<JobFilterStatus>('all')

  const handleClipOrderModeChange = useCallback((mode: ClipOrderMode) => {
    setClipOrderModeTouched(true)
    setClipOrderMode(mode)
  }, [])

  const fetchJobs = useCallback(async () => {
    try {
      const hasActiveFilters = !!deferredSearchQuery.trim() || statusFilter !== 'all'
      if (!hasActiveFilters) {
        const data = await listJobs()
        setJobs(data)
        setHasJobs(data.length > 0)
      } else {
        const [filtered, allJobs] = await Promise.all([
          listJobs({
            q: deferredSearchQuery,
            status: statusFilter,
          }),
          listJobs(),
        ])
        setJobs(filtered)
        setHasJobs(allJobs.length > 0)
      }
      setError(null)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to fetch jobs')
    } finally {
      setLoading(false)
    }
  }, [deferredSearchQuery, statusFilter])

  // Initial fetch + polling
  useEffect(() => {
    fetchJobs()
    const interval = setInterval(fetchJobs, POLLING_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [fetchJobs])

  // Sync frontend default mode with backend config (unless user already changed it).
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const health = await checkHealth()
        if (cancelled || clipOrderModeTouched) return
        const mode = health.clip_plan_order_mode === 'priority' ? 'priority' : 'timeline'
        setClipOrderMode(mode)
      } catch {
        // Keep local fallback mode when health check is unavailable.
      }
    })()
    return () => {
      cancelled = true
    }
  }, [clipOrderModeTouched])

  const handleUpload = useCallback(async (files: File[], name?: string, mode?: ClipOrderMode) => {
    if (!files.length) return
    const resolvedMode = mode || clipOrderMode

    setLoading(true)
    setError(null)
    setUploading(true)
    setUploadProgress(0)
    setUploadFileName(
      name || (files.length > 1 ? `${files.length} videos` : files[0].name)
    )
    try {
      if (files.length === 1) {
        await uploadJob(files[0], name, resolvedMode, p => {
          setUploadProgress(p)
        })
      } else {
        await uploadJobs(files, name, resolvedMode, p => {
          setUploadProgress(p)
        })
      }
      setUploadProgress(1)
      await fetchJobs()
    } catch (e: unknown) {
      setError(getErrorMessage(e, 'Upload failed'))
    } finally {
      setTimeout(() => {
        setUploading(false)
        setUploadProgress(0)
        setUploadFileName(null)
      }, 350)
      setLoading(false)
    }
  }, [clipOrderMode, fetchJobs])

  const handleCancel = useCallback(async (jobId: string) => {
    await cancelJob(jobId)
    await fetchJobs()
  }, [fetchJobs])

  const handleRetry = useCallback(async (jobId: string) => {
    await retryJob(jobId)
    await fetchJobs()
  }, [fetchJobs])

  const handleDelete = useCallback(async (jobId: string) => {
    await deleteJob(jobId)
    await fetchJobs()
  }, [fetchJobs])

  return {
    jobs, hasJobs, loading, error,
    uploading, uploadProgress, uploadFileName,
    clipOrderMode,
    setClipOrderMode: handleClipOrderModeChange,
    searchQuery,
    setSearchQuery,
    statusFilter,
    setStatusFilter,
    refresh: fetchJobs,
    onUpload: handleUpload,
    onCancel: handleCancel,
    onRetry: handleRetry,
    onDelete: handleDelete,
  }
}
