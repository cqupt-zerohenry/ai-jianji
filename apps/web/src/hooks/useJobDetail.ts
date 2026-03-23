/**
 * useJobDetail — fetches and polls a single job detail with timelines.
 */
import { useState, useEffect, useCallback } from 'react'
import { getJob } from '@/services/api'
import type { JobDetail } from '@/types'
import { POLLING_INTERVAL_MS } from '@/utils/constants'

export function useJobDetail(jobId: string | null) {
  const [job, setJob] = useState<JobDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetch = useCallback(async () => {
    if (!jobId) return
    setLoading(true)
    try {
      const data = await getJob(jobId)
      setJob(data)
      setError(null)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to fetch job')
    } finally {
      setLoading(false)
    }
  }, [jobId])

  useEffect(() => {
    if (!jobId) { setJob(null); return }
    fetch()
  }, [jobId, fetch])

  // Poll while in progress
  useEffect(() => {
    if (!job) return
    if (job.status === 'processing' || job.status === 'queued') {
      const interval = setInterval(fetch, POLLING_INTERVAL_MS)
      return () => clearInterval(interval)
    }
  }, [job?.status, fetch])

  return { job, loading, error, refresh: fetch }
}
