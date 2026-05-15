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
    jobs, hasJobs, loading, error,
    uploading, uploadProgress, uploadFileName,
    clipOrderMode, setClipOrderMode,
    searchQuery, setSearchQuery,
    statusFilter, setStatusFilter,
    onUpload, onCancel, onRetry, onDelete,
  } = useJobs()

  // Show loading spinner during initial fetch
  if (loading && !hasJobs && jobs.length === 0) {
    return (
      <div className="flex h-screen bg-gray-950 items-center justify-center">
        <div className="w-6 h-6 border-2 border-gray-700 border-t-green-500 rounded-full animate-spin" />
      </div>
    )
  }

  // No history → welcome / import page (stays here during upload until jobs appear)
  if (!hasJobs) {
    return (
      <WelcomePage
        uploading={uploading}
        uploadProgress={uploadProgress}
        uploadFileName={uploadFileName}
        clipOrderMode={clipOrderMode}
        onClipOrderModeChange={setClipOrderMode}
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
      clipOrderMode={clipOrderMode}
      onClipOrderModeChange={setClipOrderMode}
      searchQuery={searchQuery}
      onSearchQueryChange={setSearchQuery}
      statusFilter={statusFilter}
      onStatusFilterChange={setStatusFilter}
      onUpload={onUpload}
      onCancel={onCancel}
      onRetry={onRetry}
      onDelete={onDelete}
    />
  )
}
