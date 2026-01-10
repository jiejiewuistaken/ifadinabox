"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { createProject, setInputs, startRun, uploadFiles } from "./lib/api";

export default function Home() {
  const router = useRouter();
  const [projectId, setProjectId] = useState<string | null>(null);

  const [country, setCountry] = useState("");
  const [title, setTitle] = useState("");
  const [userNotes, setUserNotes] = useState("");
  const [files, setFiles] = useState<File[]>([]);

  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const canStart = useMemo(() => {
    return !!projectId && files.length > 0;
  }, [projectId, files.length]);

  async function onCreateProject() {
    setError(null);
    setBusy("Creating project...");
    try {
      const { project_id } = await createProject();
      setProjectId(project_id);
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setBusy(null);
    }
  }

  async function onIngestAndRun() {
    if (!projectId) return;
    setError(null);
    setBusy("Saving inputs, uploading files, starting run...");
    try {
      await setInputs(projectId, { country, title, user_notes: userNotes });
      await uploadFiles(projectId, files);
      const { run_id } = await startRun(projectId);
      router.push(`/runs/${run_id}`);
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div style={{ padding: 24, maxWidth: 980, margin: "0 auto" }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 8 }}>
        IFAD in a box — MVP
      </h1>
      <p style={{ opacity: 0.8, marginBottom: 16 }}>
        Step 1: Upload files + add notes → Step 2: Run simulation → Step 3: Preview PDF + checklist.
      </p>

      <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 16 }}>
        <button
          onClick={onCreateProject}
          disabled={!!busy}
          style={{ padding: "10px 14px", fontWeight: 600 }}
        >
          Create Project
        </button>
        <div style={{ fontFamily: "monospace", opacity: 0.85 }}>
          project_id: {projectId ?? "(not created yet)"}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <label style={{ display: "grid", gap: 6 }}>
          <div style={{ fontWeight: 600 }}>Country</div>
          <input
            value={country}
            onChange={(e) => setCountry(e.target.value)}
            placeholder="e.g., Kenya"
            style={{ padding: 10 }}
          />
        </label>
        <label style={{ display: "grid", gap: 6 }}>
          <div style={{ fontWeight: 600 }}>COSOP title</div>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g., COSOP 2026–2031"
            style={{ padding: 10 }}
          />
        </label>
      </div>

      <label style={{ display: "grid", gap: 6, marginTop: 12 }}>
        <div style={{ fontWeight: 600 }}>User notes (free text)</div>
        <textarea
          value={userNotes}
          onChange={(e) => setUserNotes(e.target.value)}
          placeholder="Paste country context, priorities, constraints, etc."
          rows={8}
          style={{ padding: 10, resize: "vertical" }}
        />
      </label>

      <label style={{ display: "grid", gap: 6, marginTop: 12 }}>
        <div style={{ fontWeight: 600 }}>Upload documents (PDF / TXT / MD)</div>
        <input
          type="file"
          multiple
          onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
        />
        <div style={{ opacity: 0.8 }}>
          {files.length === 0 ? "No files selected." : `${files.length} file(s) selected.`}
        </div>
      </label>

      <div style={{ marginTop: 16, display: "flex", gap: 12, alignItems: "center" }}>
        <button
          onClick={onIngestAndRun}
          disabled={!!busy || !canStart}
          style={{ padding: "10px 14px", fontWeight: 700 }}
        >
          Start Simulation
        </button>
        {busy ? <div style={{ opacity: 0.8 }}>{busy}</div> : null}
      </div>

      {error ? (
        <pre
          style={{
            marginTop: 16,
            padding: 12,
            background: "rgba(255,0,0,0.06)",
            border: "1px solid rgba(255,0,0,0.25)",
            whiteSpace: "pre-wrap",
          }}
        >
          {error}
        </pre>
      ) : null}
    </div>
  );
}
