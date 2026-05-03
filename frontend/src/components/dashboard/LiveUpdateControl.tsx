export function LiveUpdateControl({
  paused,
  onToggle,
}: {
  paused: boolean
  onToggle: () => void
}) {
  return (
    <div className="dashboard-live-control">
      <span className="dashboard-live-dot" aria-hidden="true" />
      <span className="dashboard-live-label">LIVE</span>
      <button
        type="button"
        className="dashboard-live-toggle"
        onClick={onToggle}
        aria-pressed={paused}
      >
        {paused ? 'Resume updates' : 'Pause updates'}
      </button>
    </div>
  )
}
