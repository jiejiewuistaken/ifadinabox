export const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export const WS_BACKEND_URL =
  process.env.NEXT_PUBLIC_WS_BACKEND_URL ?? "ws://localhost:8000";

async function apiFetch(path: string, init?: RequestInit) {
  const res = await fetch(`${BACKEND_URL}${path}`, init);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText} ${text}`);
  }
  return res;
}

export async function createProject(): Promise<{ project_id: string }> {
  const res = await apiFetch("/api/projects", { method: "POST" });
  return res.json();
}

export async function setInputs(
  projectId: string,
  body: { country?: string; title?: string; user_notes: string },
): Promise<void> {
  await apiFetch(`/api/projects/${projectId}/inputs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function uploadFiles(projectId: string, files: File[]): Promise<void> {
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  await apiFetch(`/api/projects/${projectId}/upload`, { method: "POST", body: fd });
}

export async function startRun(projectId: string): Promise<{ run_id: string }> {
  const res = await apiFetch(`/api/projects/${projectId}/runs`, { method: "POST" });
  return res.json();
}

export async function getRun(runId: string): Promise<any> {
  const res = await apiFetch(`/api/runs/${runId}`, { method: "GET" });
  return res.json();
}

