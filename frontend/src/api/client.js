// Thin fetch wrapper around the FastAPI backend (see api/main.py).
// No axios/react-query — the brief asks for plain React + fetch.

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, options)
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

export function ingestFile(file) {
  const formData = new FormData()
  formData.append('file', file)
  return request('/ingest', { method: 'POST', body: formData })
}

export function getRuns() {
  return request('/runs')
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
