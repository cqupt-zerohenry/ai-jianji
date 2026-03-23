// Core domain types for the Football Clip System frontend

export type JobStatus = 'queued' | 'processing' | 'completed' | 'failed' | 'canceled'

export type EventType =
  | 'SOURCE'
  | 'GOAL'
  | 'SHOT_ON_TARGET'
  | 'SHOT_BLOCKED'
  | 'SAVE'
  | 'CORNER_KICK'
  | 'FREE_KICK'
  | 'OFFSIDE'
  | 'FOUL'
  | 'SUBSTITUTION'
  | 'YELLOW_CARD'
  | 'RED_CARD'
  | 'PENALTY'
  | 'VAR'
  | 'HIGHLIGHT'

export type TransitionType = 'cut' | 'fade' | 'wipe' | 'slide' | 'circle'

export interface DetectedEvent {
  id: string
  job_id: string
  event_type: EventType
  timestamp_seconds: number
  confidence: number
  description?: string
  extra_data?: Record<string, unknown>
}

export interface Clip {
  id: string
  timeline_id: string
  title: string
  event_type?: EventType
  event_id?: string
  start_time: number
  end_time: number
  order_index: number
  transition_type: TransitionType
  transition_duration: number
  is_ai_generated: boolean
  notes?: string
}

export interface Timeline {
  id: string
  job_id: string
  name: string
  order_index: number
  is_active: boolean
  clips: Clip[]
}

export interface JobListItem {
  id: string
  name: string
  status: JobStatus
  progress: number
  progress_message: string
  source_filename?: string
  video_duration?: number
  detection_chain?: string
  created_at: string
  updated_at: string
  completed_at?: string
  error_message?: string
}

export interface JobDetail extends JobListItem {
  source_path?: string
  output_path?: string
  ai_plan?: AIPlan
  events: DetectedEvent[]
  timelines: Timeline[]
}

export interface AIPlan {
  chain_used: string
  total_events: number
  clips: AIPlanClip[]
  ai_summary: string
}

export interface AIPlanClip {
  order_index: number
  title: string
  event_type: string
  start_time: number
  end_time: number
  confidence: number
  description?: string
  transition_type: TransitionType
  transition_duration: number
}

export interface ClipPatch {
  id?: string
  title: string
  event_type?: EventType
  event_id?: string
  start_time: number
  end_time: number
  transition_type: TransitionType
  transition_duration: number
  is_ai_generated?: boolean
  notes?: string
}

export interface TimelinePatch {
  timeline_id: string
  name?: string
  clips: ClipPatch[]
}

export interface RebuildRequest {
  timelines: TimelinePatch[]
}

export interface HealthCheck {
  status: string
  api: boolean
  redis: boolean
  sqlite: boolean
  timestamp: string
}
