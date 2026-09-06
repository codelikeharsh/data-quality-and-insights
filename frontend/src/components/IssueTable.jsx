const SEVERITY_STYLES = {
  high: 'bg-red-100 text-red-700',
  medium: 'bg-amber-100 text-amber-700',
  low: 'bg-slate-100 text-slate-700',
}

export default function IssueTable({ issues }) {
  if (!issues || issues.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
        No issues flagged.
      </p>
    )
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50">
          <tr>
            <th className="px-3 py-2 text-left font-medium text-slate-500">Severity</th>
            <th className="px-3 py-2 text-left font-medium text-slate-500">Type</th>
            <th className="px-3 py-2 text-left font-medium text-slate-500">Row</th>
            <th className="px-3 py-2 text-left font-medium text-slate-500">Column</th>
            <th className="px-3 py-2 text-left font-medium text-slate-500">Description</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {issues.map((issue, idx) => (
            <tr key={idx}>
              <td className="px-3 py-2">
                <span
                  className={`rounded px-2 py-0.5 text-xs font-medium ${SEVERITY_STYLES[issue.severity] || SEVERITY_STYLES.low}`}
                >
                  {issue.severity}
                </span>
              </td>
              <td className="px-3 py-2 font-mono text-xs text-slate-600">{issue.issue_type}</td>
              <td className="px-3 py-2 text-slate-600">{issue.row_reference}</td>
              <td className="px-3 py-2 text-slate-600">{issue.column}</td>
              <td className="px-3 py-2 text-slate-700">{issue.description}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
