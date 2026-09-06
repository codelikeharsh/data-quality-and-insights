import { useCallback, useState } from 'react'
import { ingestFile } from '../api/client'
import HealthScoreBadge from '../components/HealthScoreBadge'
import IssueTable from '../components/IssueTable'

export default function UploadPage() {
  const [isDragging, setIsDragging] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  const runIngest = useCallback(async (file) => {
    if (!file) return
    setIsUploading(true)
    setError(null)
    try {
      const data = await ingestFile(file)
      setResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setIsUploading(false)
    }
  }, [])

  const handleDrop = (event) => {
    event.preventDefault()
    setIsDragging(false)
    const file = event.dataTransfer.files?.[0]
    runIngest(file)
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <h1 className="text-2xl font-semibold text-slate-900">Ingest a dataset</h1>
      <p className="mt-1 text-sm text-slate-600">
        Drop any CSV/Excel file — no fixed schema required. It runs through ingestion, profiling,
        the quality rule engine, and health scoring, and the result appears below immediately.
      </p>

      <label
        onDragOver={(e) => {
          e.preventDefault()
          setIsDragging(true)
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        className={`mt-6 flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-12 text-center transition-colors ${
          isDragging ? 'border-slate-900 bg-slate-100' : 'border-slate-300 bg-white hover:bg-slate-50'
        }`}
      >
        <input
          type="file"
          accept=".csv,.xlsx,.xls"
          className="hidden"
          onChange={(e) => runIngest(e.target.files?.[0])}
        />
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.5}
          className="mb-3 h-10 w-10 text-slate-400"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 16.5V9m0 0-3 3m3-3 3 3M6.75 19.5a4.5 4.5 0 0 1-1.41-8.775 5.25 5.25 0 0 1 10.233-2.33 3 3 0 0 1 3.758 3.848A3.752 3.752 0 0 1 18 19.5H6.75Z" />
        </svg>
        <p className="text-sm font-medium text-slate-700">
          {isUploading ? 'Processing…' : 'Drag & drop a CSV/Excel file, or click to browse'}
        </p>
        <p className="mt-1 text-xs text-slate-400">Any columns — the engine infers the schema from your file</p>
      </label>

      {error && (
        <div className="mt-6 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-8 space-y-6">
          <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-white p-5">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                Run {result.run_id}
              </p>
              <p className="mt-1 text-sm text-slate-600">
                {result.rows_processed} rows processed · {result.rows_flagged} rows flagged
              </p>
            </div>
            <HealthScoreBadge score={result.health_score.score} size="lg" />
          </div>

          {result.health_score.deductions.length > 0 && (
            <div className="rounded-lg border border-slate-200 bg-white p-5">
              <h2 className="text-sm font-semibold text-slate-900">Score breakdown</h2>
              <ul className="mt-3 space-y-1 text-sm text-slate-600">
                {result.health_score.deductions.map((d) => (
                  <li key={d.issue_type} className="flex justify-between">
                    <span>
                      {d.issue_type} × {d.count} @ -{d.penalty_weight} pts each
                    </span>
                    <span className="font-medium text-red-600">-{d.points_deducted} pts</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div>
            <h2 className="mb-2 text-sm font-semibold text-slate-900">
              Flagged issues ({result.issues.length})
            </h2>
            <IssueTable issues={result.issues} />
          </div>
        </div>
      )}
    </div>
  )
}
