// Color-codes a 0-100 health score so the severity reads at a glance —
// consistent thresholds used everywhere the score appears in the app.
function scoreColor(score) {
  if (score >= 85) return { text: 'text-emerald-700', bg: 'bg-emerald-100', ring: 'ring-emerald-600/20' }
  if (score >= 60) return { text: 'text-amber-700', bg: 'bg-amber-100', ring: 'ring-amber-600/20' }
  return { text: 'text-red-700', bg: 'bg-red-100', ring: 'ring-red-600/20' }
}

export default function HealthScoreBadge({ score, size = 'md' }) {
  const colors = scoreColor(score)
  const sizeClasses = size === 'lg' ? 'text-3xl px-4 py-2' : 'text-sm px-2.5 py-1'

  return (
    <span
      className={`inline-flex items-center rounded-full font-semibold ring-1 ring-inset ${colors.text} ${colors.bg} ${colors.ring} ${sizeClasses}`}
    >
      {score}
      <span className="ml-1 font-normal opacity-70">/100</span>
    </span>
  )
}
