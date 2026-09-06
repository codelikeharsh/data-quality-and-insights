// Renders profiling.profiler's per-column output (see profiling/profiler.py)
// as a grid of cards — numeric columns show min/max/mean/std, text columns
// show unique-value count. Works for any set of columns, since it just
// iterates whatever the profile actually contains.
function NullBadge({ nullPct }) {
  if (nullPct === 0) return null
  const tone = nullPct > 20 ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'
  return (
    <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${tone}`}>
      {nullPct}% null
    </span>
  )
}

export default function ColumnProfileGrid({ columns }) {
  const entries = Object.entries(columns || {})
  if (entries.length === 0) return null

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {entries.map(([name, col]) => {
        const isNumeric = col.min !== null && col.min !== undefined
        return (
          <div key={name} className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex items-center justify-between gap-2">
              <span className="truncate font-mono text-xs font-semibold text-slate-900">{name}</span>
              <NullBadge nullPct={col.null_pct} />
            </div>
            <p className="mt-1 text-[11px] uppercase tracking-wide text-slate-400">{col.dtype}</p>

            {isNumeric ? (
              <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-slate-600">
                <dt className="text-slate-400">min</dt>
                <dd className="text-right font-mono">{col.min?.toLocaleString()}</dd>
                <dt className="text-slate-400">max</dt>
                <dd className="text-right font-mono">{col.max?.toLocaleString()}</dd>
                <dt className="text-slate-400">mean</dt>
                <dd className="text-right font-mono">{col.mean?.toLocaleString()}</dd>
                <dt className="text-slate-400">std</dt>
                <dd className="text-right font-mono">{col.std?.toLocaleString()}</dd>
              </dl>
            ) : (
              <p className="mt-3 text-xs text-slate-600">
                {col.unique_count} unique value{col.unique_count === 1 ? '' : 's'}
              </p>
            )}
          </div>
        )
      })}
    </div>
  )
}
