/**
 * useJobs — manages job list with polling.
 */
import { useState, useEffect, useCallback } from 'react'
import axios from 'axios'
import { listJobs, cancelJob, retryJob, deleteJob, uploadJob, uploadJobs } from '@/services/api'
import type { JobListItem } from '@/types'
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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadFileName, setUploadFileName] = useState<string | null>(null)

  const fetchJobs = useCallback(async () => {
    try {
      const data = await listJobs()
      setJobs(data)
      setError(null)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to fetch jobs')
    } finally {
      setLoading(false)
    }
  }, [])

  // Initial fetch + polling
  useEffect(() => {
    fetchJobs()
    const interval = setInterval(fetchJobs, POLLING_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [fetchJobs])

  const handleUpload = useCallback(async (files: File[], name?: string) => {
    if (!files.length) return

    setLoading(true)
    setError(null)
    setUploading(true)
    setUploadProgress(0)
    setUploadFileName(
      name || (files.length > 1 ? `${files.length} videos` : files[0].name)
    )
    try {
      if (files.length === 1) {
        await uploadJob(files[0], name, p => {
          setUploadProgress(p)
        })
      } else {
        await uploadJobs(files, name, p => {
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
  }, [fetchJobs])

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
    setJobs(prev => prev.filter(j => j.id !== jobId))
  }, [])

  return {
    jobs, loading, error,
    uploading, uploadProgress, uploadFileName,
    refresh: fetchJobs,
    onUpload: handleUpload,
    onCancel: handleCancel,
    onRetry: handleRetry,
    onDelete: handleDelete,
  }
}
