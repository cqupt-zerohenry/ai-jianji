/**
 * TaskPanel — lists all jobs with status, progress, and actions.
 */
import React, { useRef } from 'react'
import {
  Upload, RefreshCw, XCircle, Trash2, Download,
  Loader2, FolderOpen
} from 'lucide-react'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { formatRelativeTime, formatDuration } from '@/utils/time'
import type { JobListItem } from '@/types'

interface TaskPanelProps {
  jobs: JobListItem[]
  selectedJobId: string | null
  loading: boolean
  uploading?: boolean
  uploadProgress?: number
  uploadFileName?: string | null
  error?: string | null
  onSelectJob: (jobId: string) => void
  onUpload: (files: File[], name?: string) => Promise<void>
  onCancel: (jobId: string) => void
  onRetry: (jobId: string) => void
  onDelete: (jobId: string) => void
  onDownload: (jobId: string) => void
}

export function TaskPanel({
  uploading = false,
  uploadProgress = 0,
  uploadFileName = null,
  error = null,
  jobs, selectedJobId, loading,
  onSelectJob, onUpload, onCancel, onRetry, onDelete, onDownload,
}: TaskPanelProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files ? Array.from(e.target.files) : []
    if (files.length > 0) {
      void onUpload(files)
      e.target.value = ''
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 bg-gray-800 border-b border-gray-700">
        <span className="text-xs font-semibold text-gray-300 uppercase tracking-wider">Tasks</span>
        <button
          onClick={() => fileInputRef.current?.click()}
          className="flex items-center gap-1 text-xs bg-blue-600 hover:bg-blue-500 text-white px-2 py-1 rounded transition-colors"
        >
          <Upload className="w-3 h-3" />
          Upload
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="video/*"
          className="hidden"
          onChange={handleFileChange}
        />
      </div>

      {/* Upload progress */}
      {uploading && (
        <div className="px-3 py-2 border-b border-gray-800 bg-gray-900/60 space-y-1">
          <div className="flex items-center justify-between text-[10px] text-gray-400">
            <span className="truncate pr-2">Uploading {uploadFileName || 'video'}...</span>
            <span>{Math.round(uploadProgress * 100)}%</span>
          </div>
          <div className="w-full h-1.5 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-cyan-500 rounded-full transition-all duration-200"
              style={{ width: `${Math.round(uploadProgress * 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Request error */}
      {error && (
        <div className="px-3 py-1.5 border-b border-red-900/40 bg-red-950/20 text-[10px] text-red-300">
          {error}
        </div>
      )}

      {/* Job list */}
      <div className="flex-1 overflow-y-auto">
        {loading && jobs.length === 0 ? (
          <div className="flex items-center justify-center h-20">
            <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />
          </div>
        ) : jobs.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-gray-600 text-sm gap-2">
            <Upload className="w-6 h-6 opacity-50" />
            <span>Upload a video to get started</span>
          </div>
        ) : (
          jobs.map(job => (
            <JobRow
              key={job.id}
              job={job}
              isSelected={job.id === selectedJobId}
              onSelect={() => onSelectJob(job.id)}
              onCancel={() => onCancel(job.id)}
              onRetry={() => onRetry(job.id)}
              onDelete={() => onDelete(job.id)}
              onDownload={() => onDownload(job.id)}
            />
          ))
        )}
      </div>
    </div>
  )
}

interface JobRowProps {
  job: JobListItem
  isSelected: boolean
  onSelect: () => void
  onCancel: () => void
  onRetry: () => void
  onDelete: () => void
  onDownload: () => void
}

function JobRow({ job, isSelected, onSelect, onCancel, onRetry, onDelete, onDownload }: JobRowProps) {
  const isActive = job.status === 'queued' || job.status === 'processing'

  return (
    <div
      className={`
        p-2.5 border-b border-gray-800 cursor-pointer transition-colors
        ${isSelected ? 'bg-blue-900/30 border-l-2 border-l-blue-500' : 'hover:bg-gray-800/50 border-l-2 border-l-transparent'}
      `}
      onClick={onSelect}
    >
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <div className="flex-1 min-w-0">
          <div className="text-xs font-medium text-gray-200 truncate">{job.name}</div>
          <div className="text-[10px] text-gray-500 mt-0.5">
            {formatRelativeTime(job.created_at)}
            {job.video_duration && ` · ${formatDuration(job.video_duration)}`}
          </div>
        </div>
        <StatusBadge status={job.status} />
      </div>

      {/* Progress bar */}
      {isActive && (
        <div className="space-y-1 mb-1.5">
          <div className="w-full h-1 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 rounded-full transition-all duration-500"
              style={{ width: `${Math.round(job.progress * 100)}%` }}
            />
          </div>
          <div className="text-[10px] text-gray-400 truncate">{job.progress_message}</div>
        </div>
      )}

      {/* Error */}
      {job.status === 'failed' && job.error_message && (
        <div className="text-[10px] text-red-400 truncate mb-1.5">{job.error_message}</div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-1.5 mt-1" onClick={e => e.stopPropagation()}>
        {job.status === 'completed' && (
          <>
            <ActionButton icon={<FolderOpen className="w-3 h-3" />} label="Open" onClick={onSelect} variant="primary" />
            <ActionButton icon={<Download className="w-3 h-3" />} label="Download" onClick={onDownload} />
          </>
        )}
        {isActive && (
          <ActionButton icon={<XCircle className="w-3 h-3" />} label="Cancel" onClick={onCancel} variant="danger" />
        )}
        {(job.status === 'failed' || job.status === 'canceled') && (
          <ActionButton icon={<RefreshCw className="w-3 h-3" />} label="Retry" onClick={onRetry} />
        )}
        <ActionButton icon={<Trash2 className="w-3 h-3" />} label="Delete" onClick={onDelete} variant="danger" />
      </div>
    </div>
  )
}

function ActionButton({
  icon, label, onClick, variant = 'default'
}: {
  icon: React.ReactNode
  label: string
  onClick: () => void
  variant?: 'default' | 'primary' | 'danger'
}) {
  const colors = {
    default: 'text-gray-500 hover:text-gray-300',
    primary: 'text-blue-500 hover:text-blue-300',
    danger: 'text-gray-500 hover:text-red-400',
  }
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-0.5 text-[10px] transition-colors ${colors[variant]}`}
      title={label}
    >
      {icon}
      <span>{label}</span>
    </button>
  )
}
