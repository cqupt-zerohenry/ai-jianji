/**
 * WelcomePage — landing page shown when there are no jobs.
 * Full-screen import experience with drag-and-drop, similar to professional NLEs.
 */
import React, { useRef, useState, useCallback } from 'react'
import {
  Upload, Film, Zap, Scissors, Clock,
  Loader2, AlertCircle,
} from 'lucide-react'

interface WelcomePageProps {
  uploading: boolean
  uploadProgress: number
  uploadFileName: string | null
  error: string | null
  onUpload: (files: File[], name?: string) => Promise<void>
}

const ACCEPT_EXTENSIONS = ['mp4', 'mov', 'avi', 'mkv', 'webm']

export function WelcomePage({
  uploading,
  uploadProgress,
  uploadFileName,
  error,
  onUpload,
}: WelcomePageProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)

    const files = Array.from(e.dataTransfer.files).filter(f => {
      const ext = f.name.split('.').pop()?.toLowerCase() || ''
      return ACCEPT_EXTENSIONS.includes(ext)
    })
    if (files.length > 0) {
      void onUpload(files)
    }
  }, [onUpload])

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files ? Array.from(e.target.files) : []
    if (files.length > 0) {
      void onUpload(files)
      e.target.value = ''
    }
  }

  return (
    <div className="flex h-screen bg-gray-950 text-white overflow-hidden">
      <div className="flex-1 flex flex-col items-center justify-center px-6">
        {/* Brand */}
        <div className="flex items-center gap-3 mb-10">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-green-500 to-emerald-600 flex items-center justify-center shadow-lg shadow-green-500/20">
            <Scissors className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Football Clip AI</h1>
            <p className="text-sm text-gray-500">AI-Powered Match Highlight Generator</p>
          </div>
        </div>

        {/* Upload area */}
        {uploading ? (
          <UploadingState
            fileName={uploadFileName}
            progress={uploadProgress}
          />
        ) : (
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`
              group relative w-full max-w-lg cursor-pointer
              rounded-2xl border-2 border-dashed transition-all duration-300
              ${dragOver
                ? 'border-green-400 bg-green-500/10 scale-[1.02]'
                : 'border-gray-700 hover:border-gray-500 hover:bg-gray-900/50'
              }
            `}
          >
            <div className="flex flex-col items-center justify-center py-16 px-8">
              <div className={`
                w-16 h-16 rounded-2xl flex items-center justify-center mb-5 transition-all duration-300
                ${dragOver
                  ? 'bg-green-500/20 text-green-400 scale-110'
                  : 'bg-gray-800 text-gray-500 group-hover:text-gray-300 group-hover:bg-gray-700'
                }
              `}>
                <Upload className="w-8 h-8" />
              </div>

              <h2 className="text-lg font-semibold text-gray-200 mb-2">
                Import Match Video
              </h2>
              <p className="text-sm text-gray-500 text-center mb-4">
                Drag and drop video files here, or click to browse
              </p>
              <p className="text-xs text-gray-600">
                Supports {ACCEPT_EXTENSIONS.map(e => `.${e}`).join(', ')}
              </p>

              <button
                className="mt-6 px-5 py-2 bg-green-600 hover:bg-green-500 text-white text-sm font-medium rounded-lg transition-colors"
                onClick={(e) => {
                  e.stopPropagation()
                  fileInputRef.current?.click()
                }}
              >
                Select Files
              </button>
            </div>
          </div>
        )}

        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="video/*"
          className="hidden"
          onChange={handleFileChange}
        />

        {/* Error */}
        {error && (
          <div className="mt-4 flex items-center gap-2 px-4 py-2 bg-red-950/30 border border-red-900/40 rounded-lg max-w-lg w-full">
            <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0" />
            <span className="text-sm text-red-300">{error}</span>
          </div>
        )}

        {/* Feature highlights */}
        <div className="mt-14 grid grid-cols-3 gap-8 max-w-lg w-full">
          <FeatureItem
            icon={<Zap className="w-4 h-4" />}
            title="AI Detection"
            desc="Auto-detect goals, shots, fouls"
          />
          <FeatureItem
            icon={<Film className="w-4 h-4" />}
            title="Smart Clips"
            desc="Priority-based highlight reel"
          />
          <FeatureItem
            icon={<Clock className="w-4 h-4" />}
            title="Timeline Edit"
            desc="Fine-tune clips with ease"
          />
        </div>
      </div>
    </div>
  )
}

function UploadingState({
  fileName,
  progress,
}: {
  fileName: string | null
  progress: number
}) {
  const pct = Math.round(progress * 100)
  return (
    <div className="w-full max-w-lg rounded-2xl border border-gray-800 bg-gray-900/60 p-10 flex flex-col items-center">
      <Loader2 className="w-10 h-10 text-green-500 animate-spin mb-5" />
      <h3 className="text-base font-semibold text-gray-200 mb-1">Uploading</h3>
      <p className="text-sm text-gray-500 mb-5 truncate max-w-full">
        {fileName || 'video'}
      </p>
      <div className="w-full h-2 bg-gray-800 rounded-full overflow-hidden mb-2">
        <div
          className="h-full bg-green-500 rounded-full transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-gray-500">{pct}%</span>
    </div>
  )
}

function FeatureItem({
  icon,
  title,
  desc,
}: {
  icon: React.ReactNode
  title: string
  desc: string
}) {
  return (
    <div className="flex flex-col items-center text-center gap-2">
      <div className="w-8 h-8 rounded-lg bg-gray-800 flex items-center justify-center text-gray-400">
        {icon}
      </div>
      <span className="text-xs font-medium text-gray-300">{title}</span>
      <span className="text-[10px] text-gray-600 leading-tight">{desc}</span>
    </div>
  )
}
