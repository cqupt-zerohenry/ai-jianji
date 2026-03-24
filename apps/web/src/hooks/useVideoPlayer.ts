/**
 * useVideoPlayer — controls an HTML video element ref.
 * Includes Mark In / Mark Out support for manual clipping.
 *
 * Uses a callback ref so event listeners are correctly re-bound
 * whenever the underlying <video> element mounts / remounts.
 */
import { useState, useCallback, useEffect, useRef } from 'react'

export function useVideoPlayer() {
  const [videoEl, setVideoEl] = useState<HTMLVideoElement | null>(null)
  // Keep a stable ref for external code that reads .current (e.g. pendingSourceSeek)
  const videoRef = useRef<HTMLVideoElement | null>(null)

  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [markIn, setMarkIn] = useState<number | null>(null)
  const [markOut, setMarkOut] = useState<number | null>(null)

  // Callback ref — passed to <video ref={callbackRef}>
  // Fires on mount (el = node) and unmount (el = null).
  const callbackRef = useCallback((node: HTMLVideoElement | null) => {
    videoRef.current = node
    setVideoEl(node)
  }, [])

  // Bind / unbind listeners whenever the element changes
  useEffect(() => {
    if (!videoEl) {
      // Element unmounted — reset state
      setCurrentTime(0)
      setDuration(0)
      setPlaying(false)
      return
    }

    const onTimeUpdate = () => setCurrentTime(videoEl.currentTime)
    const onDurationChange = () => setDuration(videoEl.duration || 0)
    const onPlay = () => setPlaying(true)
    const onPause = () => setPlaying(false)
    const onLoadedMetadata = () => {
      setDuration(videoEl.duration || 0)
      setCurrentTime(videoEl.currentTime)
    }

    videoEl.addEventListener('timeupdate', onTimeUpdate)
    videoEl.addEventListener('durationchange', onDurationChange)
    videoEl.addEventListener('loadedmetadata', onLoadedMetadata)
    videoEl.addEventListener('play', onPlay)
    videoEl.addEventListener('pause', onPause)

    // Sync initial state in case video already has data
    if (videoEl.readyState >= 1) {
      setDuration(videoEl.duration || 0)
      setCurrentTime(videoEl.currentTime)
    }

    return () => {
      videoEl.removeEventListener('timeupdate', onTimeUpdate)
      videoEl.removeEventListener('durationchange', onDurationChange)
      videoEl.removeEventListener('loadedmetadata', onLoadedMetadata)
      videoEl.removeEventListener('play', onPlay)
      videoEl.removeEventListener('pause', onPause)
    }
  }, [videoEl])

  const seek = useCallback((time: number) => {
    const el = videoRef.current
    if (el) {
      el.currentTime = time
      setCurrentTime(time)
    }
  }, [])

  const togglePlay = useCallback(() => {
    const el = videoRef.current
    if (!el) return
    if (el.paused) el.play()
    else el.pause()
  }, [])

  const setVolume = useCallback((vol: number) => {
    if (videoRef.current) videoRef.current.volume = vol
  }, [])

  const handleMarkIn = useCallback(() => {
    const t = videoRef.current?.currentTime ?? 0
    setMarkIn(t)
    setMarkOut(prev => (prev !== null && prev <= t) ? null : prev)
  }, [])

  const handleMarkOut = useCallback(() => {
    const t = videoRef.current?.currentTime ?? 0
    setMarkOut(t)
    setMarkIn(prev => (prev !== null && prev >= t) ? null : prev)
  }, [])

  const clearMarks = useCallback(() => {
    setMarkIn(null)
    setMarkOut(null)
  }, [])

  return {
    videoRef: callbackRef, currentTime, duration, playing,
    seek, togglePlay, setVolume,
    markIn, markOut, handleMarkIn, handleMarkOut, clearMarks,
    /** Stable ref for imperative access (e.g. .current.readyState) */
    elementRef: videoRef,
  }
}
