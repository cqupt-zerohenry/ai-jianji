/**
 * App — root component that switches between WelcomePage and EditorPage.
 *
 * - No jobs + initial load done → WelcomePage (full-screen import)
 * - Jobs exist (or user just uploaded) → EditorPage (sidebar + editor)
 */
import React from 'react'
import { WelcomePage } from '@/pages/WelcomePage'
import { EditorPage } from '@/pages/EditorPage'
import { useJobs } from '@/hooks/useJobs'

export default function App() {
  const {
    jobs, loading, error,
    uploading, uploadProgress, uploadFileName,
    onUpload, onCancel, onRetry, onDelete, refresh,
  } = useJobs()

  // Show loading spinner during initial fetch
  if (loading && jobs.length === 0) {
    return (
      <div className="flex h-screen bg-gray-950 items-center justify-center">
        <div className="w-6 h-6 border-2 border-gray-700 border-t-green-500 rounded-full animate-spin" />
      </div>
    )
  }

  // No history → welcome / import page (stays here during upload until jobs appear)
  if (jobs.length === 0) {
    return (
      <WelcomePage
        uploading={uploading}
        uploadProgress={uploadProgress}
        uploadFileName={uploadFileName}
        error={error}
        onUpload={onUpload}
      />
    )
  }

  // Has jobs → full editor with sidebar
  return (
    <EditorPage
      jobs={jobs}
      loading={loading}
      error={error}
      uploading={uploading}
      uploadProgress={uploadProgress}
      uploadFileName={uploadFileName}
      onUpload={onUpload}
      onCancel={onCancel}
      onRetry={onRetry}
      onDelete={onDelete}
    />
  )
}
