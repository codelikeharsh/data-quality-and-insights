// Renders whatever rows /runs/{id}/preview returns as a plain table — the
// column set is read from the first row, so this works for any dataset
// shape without knowing its columns ahead of time.
export default function DataPreviewTable({ rows }) {
  if (!rows || rows.length === 0) return null
  const columns = Object.keys(rows[0])

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50">
          <tr>
            {columns.map((col) => (
              <th key={col} className="whitespace-nowrap px-3 py-2 text-left font-mono text-xs font-medium text-slate-500">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {rows.map((row, idx) => (
            <tr key={idx}>
              {columns.map((col) => (
                <td key={col} className="whitespace-nowrap px-3 py-2 text-slate-700">
                  {row[col] === null || row[col] === undefined ? (
                    <span className="text-slate-300">—</span>
                  ) : (
                    String(row[col])
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
