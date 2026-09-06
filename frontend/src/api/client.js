// Thin fetch wrapper around the FastAPI backend (see api/main.py).
// No axios/react-query — the brief asks for plain React + fetch.

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
// Only needed if the backend was started with API_KEY set (see api/auth.py)
// — unset by default so local dev needs no extra setup.
const API_KEY = import.meta.env.VITE_API_KEY || ''

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) }
  if (API_KEY) headers['X-API-Key'] = API_KEY

  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = body.detail || detail
    } catch {
      // response body wasn't JSON — fall back to statusText
    }
    throw new Error(detail)
  }
  return response.json()
}

export function ingestFile(file, datasetName) {
  const formData = new FormData()
  formData.append('file', file)
  if (datasetName) formData.append('dataset_name', datasetName)
  return request('/ingest', { method: 'POST', body: formData })
}

export function getDatasets() {
  return request('/datasets')
}

export function getRuns(datasetName) {
  const qs = datasetName ? `?dataset_name=${encodeURIComponent(datasetName)}` : ''
  return request(`/runs${qs}`)
}

export function getRunIssues(runId) {
  return request(`/runs/${runId}/issues`)
}

export function getRunProfile(runId) {
  return request(`/runs/${runId}/profile`)
}

export function getRunPreview(runId, limit = 25) {
  return request(`/runs/${runId}/preview?limit=${limit}`)
}

export function getIssueBreakdown(datasetName) {
  const qs = datasetName ? `?dataset_name=${encodeURIComponent(datasetName)}` : ''
  return request(`/reports/issue-breakdown${qs}`)
}

export function exportRunUrl(runId) {
  // A plain link, not a fetch — the browser handles the file download
  // (Content-Disposition) itself.
  return `${API_BASE_URL}/runs/${runId}/export`
}
