/**
 * EditorPage — the main workbench page.
 * Combines TaskPanel (left sidebar) + EditorWorkspace (main area).
 *
 * Receives job-list state from App so that the parent can decide
 * whether to show this page or the WelcomePage.
 */
import React, { useState, useCallback, useEffect } from 'react'
import { Activity, Loader2 } from 'lucide-react'
import { TaskPanel } from '@/components/panels/TaskPanel'
import { EditorWorkspace } from '@/containers/EditorWorkspace'
import { useJobDetail } from '@/hooks/useJobDetail'
import { getDownloadUrl } from '@/services/api'
import type { JobListItem } from '@/types'

interface EditorPageProps {
  jobs: JobListItem[]
  loading: boolean
  error: string | null
  uploading: boolean
  uploadProgress: number
  uploadFileName: string | null
  onUpload: (files: File[], name?: string) => Promise<void>
  onCancel: (jobId: string) => void
  onRetry: (jobId: string) => void
  onDelete: (jobId: string) => void
}

export function EditorPage({
  jobs, loading, error,
  uploading, uploadProgress, uploadFileName,
  onUpload, onCancel, onRetry, onDelete,
}: EditorPageProps) {
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
  const { job, loading: jobLoading, refresh: refreshJob } = useJobDetail(selectedJobId)

  // Auto-select the first job when entering from WelcomePage (no selection yet)
  useEffect(() => {
    if (!selectedJobId && jobs.length > 0) {
      setSelectedJobId(jobs[0].id)
    }
  }, [selectedJobId, jobs])

  const handleSelectJob = useCallback((jobId: string) => {
    setSelectedJobId(jobId)
  }, [])

  const handleDownload = useCallback((jobId: string) => {
    window.open(getDownloadUrl(jobId), '_blank')
  }, [])

  const handleRebuildStart = useCallback(() => {
    refreshJob()
  }, [refreshJob])

  // Show editor for any job that has been loaded (all statuses)
  const showEditor = !!job

  return (
    <div className="flex h-screen bg-gray-950 text-white overflow-hidden">
      {/* Left sidebar — Task Panel */}
      <aside className="w-64 flex-shrink-0 border-r border-gray-800 flex flex-col">
        <div className="flex items-center gap-2 px-3 py-3 border-b border-gray-800">
          <Activity className="w-5 h-5 text-green-400" />
          <span className="font-bold text-sm tracking-tight">Football Clip AI</span>
        </div>
        <div className="flex-1 overflow-hidden">
          <TaskPanel
            jobs={jobs}
            selectedJobId={selectedJobId}
            loading={loading}
            uploading={uploading}
            uploadProgress={uploadProgress}
            uploadFileName={uploadFileName}
            error={error}
            onSelectJob={handleSelectJob}
            onUpload={onUpload}
            onCancel={onCancel}
            onRetry={onRetry}
            onDelete={onDelete}
            onDownload={handleDownload}
          />
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 flex flex-col p-3 min-w-0 overflow-hidden">
        {!selectedJobId ? (
          <EmptyState />
        ) : jobLoading && !job ? (
          <LoadingState />
        ) : showEditor ? (
          <EditorWorkspace job={job} onRebuildStart={handleRebuildStart} />
        ) : (
          <EmptyState />
        )}
      </main>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-gray-600 gap-4">
      <div className="w-16 h-16 rounded-2xl bg-gray-800 flex items-center justify-center">
        <Activity className="w-8 h-8 text-gray-600" />
      </div>
      <div className="text-center">
        <h2 className="text-lg font-semibold text-gray-400 mb-1">Football Clip AI Workbench</h2>
        <p className="text-sm">Upload a match video or select a job from the left panel</p>
      </div>
    </div>
  )
}

function LoadingState() {
  return (
    <div className="flex-1 flex items-center justify-center">
      <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
    </div>
  )
}

