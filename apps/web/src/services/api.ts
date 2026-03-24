/**
 * Centralized API client using axios.
 * All backend communication goes through this module.
 */
import axios from 'axios'
import type {
  JobListItem, JobDetail, JobCreateResponse,
  RebuildRequest, HealthCheck, SourceInfo
} from '@/types'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

const api = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,
})

// ─── Jobs API ────────────────────────────────────────────────────────────────

export async function uploadJob(
  file: File,
  name?: string,
  onProgress?: (progress: number) => void,
): Promise<JobCreateResponse> {
  const form = new FormData()
  form.append('file', file)
  if (name) form.append('name', name)
  const { data } = await api.post<JobCreateResponse>('/api/jobs', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000, // longer timeout for upload
    onUploadProgress: evt => {
      if (!onProgress) return
      const total = evt.total ?? file.size
      if (!total) return
      onProgress(Math.max(0, Math.min(1, evt.loaded / total)))
    },
  })
  return data
}

export async function uploadJobs(
  files: File[],
  name?: string,
  onProgress?: (progress: number) => void,
): Promise<JobCreateResponse> {
  const form = new FormData()
  for (const file of files) {
    form.append('files', file)
  }
  if (name) form.append('name', name)

  const totalSize = files.reduce((sum, f) => sum + (f.size || 0), 0)
  const { data } = await api.post<JobCreateResponse>('/api/jobs/multi', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 240000,
    onUploadProgress: evt => {
      if (!onProgress) return
      const total = evt.total ?? totalSize
      if (!total) return
      onProgress(Math.max(0, Math.min(1, evt.loaded / total)))
    },
  })
  return data
}

export async function listJobs(): Promise<JobListItem[]> {
  const { data } = await api.get<JobListItem[]>('/api/jobs')
  return data
}

export async function getJob(jobId: string): Promise<JobDetail> {
  const { data } = await api.get<JobDetail>(`/api/jobs/${jobId}`)
  return data
}

export async function rebuildJob(jobId: string, request: RebuildRequest): Promise<void> {
  await api.post(`/api/jobs/${jobId}/rebuild`, request)
}

export async function cancelJob(jobId: string): Promise<void> {
  await api.post(`/api/jobs/${jobId}/cancel`)
}

export async function retryJob(jobId: string): Promise<void> {
  await api.post(`/api/jobs/${jobId}/retry`)
}

export async function deleteJob(jobId: string): Promise<void> {
  await api.delete(`/api/jobs/${jobId}`)
}

export async function addSource(
  jobId: string,
  file: File,
  onProgress?: (progress: number) => void,
): Promise<SourceInfo[]> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post<SourceInfo[]>(`/api/jobs/${jobId}/sources`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
    onUploadProgress: evt => {
      if (!onProgress) return
      const total = evt.total ?? file.size
      if (!total) return
      onProgress(Math.max(0, Math.min(1, evt.loaded / total)))
    },
  })
  return data
}

export function getSourceUrl(jobId: string, sourceIndex: number): string {
  return `${BASE_URL}/api/jobs/${jobId}/source?source_index=${sourceIndex}`
}

export function getDownloadUrl(jobId: string): string {
  return `${BASE_URL}/api/jobs/${jobId}/download`
}

export async function checkHealth(): Promise<HealthCheck> {
  const { data } = await api.get<HealthCheck>('/api/health')
  return data
}
