/**
 * EditorPage — the main workbench page.
 * Combines TaskPanel (left sidebar) + EditorWorkspace (main area).
 */
import React, { useState, useCallback } from 'react'
import { Activity, Loader2, AlertCircle } from 'lucide-react'
import { TaskPanel } from '@/components/panels/TaskPanel'
import { EditorWorkspace } from '@/containers/EditorWorkspace'
import { useJobs } from '@/hooks/useJobs'
import { useJobDetail } from '@/hooks/useJobDetail'
import { getDownloadUrl } from '@/services/api'

export function EditorPage() {
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
  const {
    jobs, loading, error,
    uploading, uploadProgress, uploadFileName,
    onUpload, onCancel, onRetry, onDelete,
  } = useJobs()
  const { job, loading: jobLoading, refresh: refreshJob } = useJobDetail(selectedJobId)

  const handleSelectJob = useCallback((jobId: string) => {
    setSelectedJobId(jobId)
  }, [])

  const handleDownload = useCallback((jobId: string) => {
    window.open(getDownloadUrl(jobId), '_blank')
  }, [])

  const handleRebuildStart = useCallback(() => {
    refreshJob()
  }, [refreshJob])

  const showEditor = job && (
    job.status === 'completed' ||
    job.status === 'failed' ||
    job.status === 'processing'
  ) && job.timelines.length > 0

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
        ) : job?.status === 'queued' || job?.status === 'processing' ? (
          <ProcessingState job={job} />
        ) : showEditor ? (
          <EditorWorkspace job={job} onRebuildStart={handleRebuildStart} />
        ) : job?.status === 'failed' ? (
          <FailedState message={job.error_message} />
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

function ProcessingState({ job }: { job: { status: string; progress: number; progress_message: string; name: string } }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-4">
      <Loader2 className="w-10 h-10 text-blue-500 animate-spin" />
      <div className="text-center">
        <h3 className="text-base font-semibold text-gray-300 mb-1">{job.name}</h3>
        <p className="text-sm text-gray-500 mb-3">{job.progress_message}</p>
        <div className="w-64 h-2 bg-gray-800 rounded-full mx-auto overflow-hidden">
          <div
            className="h-full bg-blue-500 rounded-full transition-all duration-500"
            style={{ width: `${Math.round(job.progress * 100)}%` }}
          />
        </div>
        <p className="text-xs text-gray-600 mt-1">{Math.round(job.progress * 100)}%</p>
      </div>
    </div>
  )
}

function FailedState({ message }: { message?: string | null }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-3">
      <AlertCircle className="w-10 h-10 text-red-500" />
      <div className="text-center">
        <h3 className="text-base font-semibold text-red-400 mb-1">Processing Failed</h3>
        {message && <p className="text-sm text-gray-500 max-w-md">{message}</p>}
      </div>
    </div>
  )
}
