/**
 * StatusBadge — colored badge for job status.
 */
import React from 'react'
import { Badge } from '@/components/ui/badge'
import { STATUS_LABELS, STATUS_COLORS } from '@/utils/constants'
import type { JobStatus } from '@/types'

interface StatusBadgeProps {
  status: JobStatus
}

export function StatusBadge({ status }: StatusBadgeProps) {
  return (
    <Badge
      style={{ backgroundColor: STATUS_COLORS[status], color: '#fff', borderColor: 'transparent' }}
    >
      {STATUS_LABELS[status] ?? status}
    </Badge>
  )
}
