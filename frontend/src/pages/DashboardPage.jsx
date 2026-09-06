import { useEffect, useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  exportRunUrl,
  getDatasets,
  getIssueBreakdown,
  getRunIssues,
  getRunPreview,
  getRunProfile,
  getRuns,
} from '../api/client'
import IssueTable from '../components/IssueTable'
import ColumnProfileGrid from '../components/ColumnProfileGrid'
import DataPreviewTable from '../components/DataPreviewTable'
import HealthScoreBadge from '../components/HealthScoreBadge'

const SEVERITY_COLORS = { high: '#dc2626', medium: '#d97706', low: '#94a3b8' }

export default function DashboardPage() {
  const [datasets, setDatasets] = useState([])
  const [selectedDataset, setSelectedDataset] = useState(null)
  const [runs, setRuns] = useState([])
  const [latestIssues, setLatestIssues] = useState([])
  const [profile, setProfile] = useState(null)
  const [preview, setPreview] = useState([])
  const [breakdown, setBreakdown] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Load the dataset list once, then default to the most recently active one.
  useEffect(() => {
    getDatasets()
      .then((data) => {
        setDatasets(data)
        if (data.length > 0) setSelectedDataset(data[0].dataset_name)
        else setLoading(false)
      })
      .catch((err) => {
        setError(err.message)
        setLoading(false)
      })
  }, [])

  // Everything else is scoped to whichever dataset is selected — mixing two
  // different datasets' runs onto one trend line would be meaningless.
  useEffect(() => {
    if (!selectedDataset) return
    setLoading(true)
    async function load() {
      try {
        const [runsData, breakdownData] = await Promise.all([
          getRuns(selectedDataset),
          getIssueBreakdown(selectedDataset),
        ])
        setRuns([...runsData].reverse())
        setBreakdown(breakdownData)

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
  }, [selectedDataset])

  const scoreTrend = useMemo(
    () => runs.map((r) => ({ run: r.run_id, score: r.health_score })),
    [runs],
  )

  const breakdownChartData = useMemo(() => {
    const byType = {}
    for (const row of breakdown) {
      byType[row.issue_type] = byType[row.issue_type] || { issue_type: row.issue_type }
      byType[row.issue_type][row.severity] = row.issue_count
    }
    return Object.values(byType)
  }, [breakdown])

  if (error) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-8">
        <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      </div>
    )
  }

  if (!loading && datasets.length === 0) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-8">
        <p className="rounded-md border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">
          No ingestion runs yet — upload a file on the Upload page to populate the dashboard.
        </p>
      </div>
    )
  }

  const latestRun = runs[runs.length - 1]

  return (
    <div className="mx-auto max-w-6xl space-y-8 px-4 py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Trend dashboard</h1>
          <p className="mt-1 text-sm text-slate-600">
            Scoped to one dataset at a time — every chart below is that dataset's own history.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="text-xs font-medium text-slate-500">Dataset</label>
          <select
            value={selectedDataset || ''}
            onChange={(e) => setSelectedDataset(e.target.value)}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900"
          >
            {datasets.map((d) => (
              <option key={d.dataset_name} value={d.dataset_name}>
                {d.dataset_name} ({d.run_count} run{d.run_count === 1 ? '' : 's'})
              </option>
            ))}
          </select>
        </div>
      </div>

      {loading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : (
        <>
          {latestRun && (
            <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-white p-5">
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  Latest run — {latestRun.run_id}
                </p>
                <p className="mt-1 text-sm text-slate-600">
                  {latestRun.rows_processed} rows processed · {latestRun.rows_flagged} rows flagged
                </p>
              </div>
              <div className="flex items-center gap-4">
                <a
                  href={exportRunUrl(latestRun.run_id)}
                  className="text-sm font-medium text-slate-600 underline hover:text-slate-900"
                >
                  Export CSV report
                </a>
                <HealthScoreBadge score={latestRun.health_score} size="lg" />
              </div>
            </div>
          )}

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

          {breakdownChartData.length > 0 && (
            <section className="rounded-lg border border-slate-200 bg-white p-5">
              <h2 className="text-sm font-semibold text-slate-900">
                Issue breakdown by type (across every run of this dataset)
              </h2>
              <div className="mt-4 h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={breakdownChartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="issue_type" tick={{ fontSize: 12 }} stroke="#64748b" />
                    <YAxis tick={{ fontSize: 12 }} stroke="#64748b" allowDecimals={false} />
                    <Tooltip />
                    {Object.keys(SEVERITY_COLORS).map((sev) => (
                      <Bar key={sev} dataKey={sev} stackId="a" fill={SEVERITY_COLORS[sev]} name={sev} />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </section>
          )}

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
        </>
      )}
    </div>
  )
}
