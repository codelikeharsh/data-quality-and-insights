import { useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { getRunIssues, getRunPreview, getRunProfile, getRuns } from '../api/client'
import IssueTable from '../components/IssueTable'
import ColumnProfileGrid from '../components/ColumnProfileGrid'
import DataPreviewTable from '../components/DataPreviewTable'

export default function DashboardPage() {
  const [runs, setRuns] = useState([])
  const [latestIssues, setLatestIssues] = useState([])
  const [profile, setProfile] = useState(null)
  const [preview, setPreview] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    async function load() {
      try {
        const runsData = await getRuns()
        // /runs comes back newest-first; the trend chart reads left-to-right chronologically.
        setRuns([...runsData].reverse())

        if (runsData.length > 0) {
          const latestRunId = runsData[0].run_id
          const [issues, runProfile, runPreview] = await Promise.all([
            getRunIssues(latestRunId),
            getRunProfile(latestRunId),
            getRunPreview(latestRunId, 10),
          ])
          setLatestIssues(issues)
          setProfile(runProfile)
          setPreview(runPreview)
        }
      } catch (err) {
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const scoreTrend = useMemo(
    () =>
      runs.map((r) => ({
        run: r.run_id,
        timestamp: new Date(r.timestamp).toLocaleString(),
        score: r.health_score,
      })),
    [runs],
  )

  if (loading) {
    return <p className="p-8 text-sm text-slate-500">Loading dashboard…</p>
  }

  if (error) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-8">
        <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      </div>
    )
  }

  if (runs.length === 0) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-8">
        <p className="rounded-md border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">
          No ingestion runs yet — upload a file on the Upload page to populate the dashboard.
        </p>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-6xl space-y-8 px-4 py-8">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Trend dashboard</h1>
        <p className="mt-1 text-sm text-slate-600">
          Health score across every ingestion run, plus a column-by-column profile and raw data
          preview for the most recent one — works the same regardless of what columns your file has.
        </p>
      </div>

      <section className="rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="text-sm font-semibold text-slate-900">Data health score over time</h2>
        <div className="mt-4 h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={scoreTrend}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="run" tick={{ fontSize: 12 }} stroke="#64748b" />
              <YAxis domain={[0, 100]} tick={{ fontSize: 12 }} stroke="#64748b" />
              <Tooltip />
              <Line
                type="monotone"
                dataKey="score"
                stroke="#0f172a"
                strokeWidth={2}
                dot={{ r: 4 }}
                name="Health score"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>

      {profile && (
        <section>
          <h2 className="mb-2 text-sm font-semibold text-slate-900">
            Column profile (latest run — {profile.row_count} rows)
          </h2>
          <ColumnProfileGrid columns={profile.columns} />
        </section>
      )}

      {preview.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-semibold text-slate-900">
            Data preview (first {preview.length} rows)
          </h2>
          <DataPreviewTable rows={preview} />
        </section>
      )}

      <section>
        <h2 className="mb-2 text-sm font-semibold text-slate-900">
          Currently flagged issues (latest run)
        </h2>
        <IssueTable issues={latestIssues} />
      </section>
    </div>
  )
}
