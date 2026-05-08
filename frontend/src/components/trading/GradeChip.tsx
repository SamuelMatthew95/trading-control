import { StatusChip } from '@/components/terminal'
import { toneForGrade } from '@/lib/state'

interface GradeChipProps {
  grade: string | null | undefined
  className?: string
}

/** Letter-grade chip (A/B/C/D/F) — tone from the grade letter. */
export function GradeChip({ grade, className }: GradeChipProps) {
  if (!grade) return null
  const label = String(grade).toUpperCase()
  return <StatusChip label={label} tone={toneForGrade(grade)} dot={false} className={className} />
}
