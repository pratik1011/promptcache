import type { Notice as NoticeType } from '../../types'

export default function Notice({ notice }: { notice: NoticeType }) {
  if (!notice) return null
  const icons = { success: '✓', error: '⚠', info: 'ℹ' } as const
  return (
    <div className={`notice ${notice.type}`} role="status">
      <span className="notice-icon">{icons[notice.type]}</span>
      <span>{notice.message}</span>
    </div>
  )
}