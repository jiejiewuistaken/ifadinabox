"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import useSWR from "swr";

import { BACKEND_URL, getRun } from "../../../lib/api";
import { Checklist } from "../../../components/Checklist";

export default function PreviewPage() {
  const params = useParams<{ runId: string }>();
  const runId = params.runId;

  const { data: run, error } = useSWR(runId ? ["run", runId] : null, () => getRun(runId), {
    refreshInterval: 1000,
  });

  const candidateEntries = useMemo(() => {
    const candidatePdfs = (run?.artifacts?.candidate_pdfs as Record<string, string> | undefined) ?? {};
    const candidates = Array.isArray(run?.candidates) ? run.candidates : [];
    const selectedIds = Array.isArray(run?.selected_candidates)
      ? run.selected_candidates
      : Object.keys(candidatePdfs);
    const ids = selectedIds.length > 0 ? selectedIds : Object.keys(candidatePdfs);
    if (ids.length === 0) return [];
    return ids.map((id) => {
      const cand = candidates.find((c: any) => c?.candidate_id === id);
      return {
        id,
        score: typeof cand?.score === "number" ? cand.score : null,
        review: cand?.review ?? null,
        forecast: cand?.forecast ?? null,
      };
    });
  }, [run?.artifacts?.candidate_pdfs, run?.candidates]);

  const [idx, setIdx] = useState(0);
  useEffect(() => {
    setIdx(0);
  }, [candidateEntries.length, runId]);

  const activeCandidate = candidateEntries[idx] ?? null;
  const candidateId = activeCandidate?.id ?? null;
  const pdfUrl = candidateId
    ? `${BACKEND_URL}/api/runs/${runId}/pdf?candidate_id=${candidateId}&disposition=inline`
    : `${BACKEND_URL}/api/runs/${runId}/pdf?disposition=inline`;
  const downloadUrl = candidateId
    ? `${BACKEND_URL}/api/runs/${runId}/pdf?candidate_id=${candidateId}&disposition=attachment`
    : `${BACKEND_URL}/api/runs/${runId}/pdf?disposition=attachment`;
  const review = activeCandidate?.review ?? run?.review;
  const forecast = activeCandidate?.forecast ?? run?.forecast;

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 800 }}>COSOP Preview</h1>
          <div style={{ fontFamily: "monospace", opacity: 0.8 }}>run_id: {runId}</div>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <Link
            href={`/runs/${runId}`}
            style={{ padding: "8px 12px", border: "1px solid rgba(0,0,0,0.2)", borderRadius: 8 }}
          >
            Back to Simulation
          </Link>
          <a
            href={downloadUrl}
            style={{ padding: "8px 12px", border: "1px solid rgba(0,0,0,0.2)", borderRadius: 8 }}
            download="cosop.pdf"
          >
            Download PDF
          </a>
        </div>
      </div>

      {error ? (
        <pre style={{ marginTop: 12, whiteSpace: "pre-wrap", color: "crimson" }}>
          {String(error)}
        </pre>
      ) : null}

      <div style={{ marginTop: 16, display: "grid", gridTemplateColumns: "2fr 1fr", gap: 12 }}>
        <div
          style={{
            border: "1px solid rgba(0,0,0,0.15)",
            borderRadius: 8,
            overflow: "hidden",
            minHeight: 640,
          }}
        >
          {candidateEntries.length > 1 ? (
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "8px 12px",
                borderBottom: "1px solid rgba(0,0,0,0.08)",
                background: "rgba(0,0,0,0.02)",
              }}
            >
              <button
                onClick={() => setIdx((prev) => Math.max(0, prev - 1))}
                disabled={idx === 0}
                style={{ padding: "6px 10px" }}
              >
                Prev
              </button>
              <div style={{ fontSize: 13 }}>
                Candidate {idx + 1} of {candidateEntries.length}
                {activeCandidate?.score != null ? ` (score: ${activeCandidate.score.toFixed(2)})` : ""}
              </div>
              <button
                onClick={() => setIdx((prev) => Math.min(candidateEntries.length - 1, prev + 1))}
                disabled={idx >= candidateEntries.length - 1}
                style={{ padding: "6px 10px" }}
              >
                Next
              </button>
            </div>
          ) : null}
          <iframe
            title="COSOP PDF preview"
            src={pdfUrl}
            style={{ width: "100%", height: 640, border: 0 }}
          />
        </div>

        <div style={{ display: "grid", gap: 12 }}>
          {forecast ? (
            <div
              style={{
                border: "1px solid rgba(0,0,0,0.15)",
                borderRadius: 8,
                padding: 12,
              }}
            >
              <div style={{ fontWeight: 800 }}>Completion forecast</div>
              <div style={{ marginTop: 6, fontSize: 13 }}>
                Phase: <strong>{forecast.phase}</strong>
              </div>
              <div style={{ marginTop: 4, fontSize: 13 }}>
                Confidence: {(forecast.confidence ?? 0).toFixed(2)}
              </div>
              {forecast.rationale ? (
                <div style={{ marginTop: 6, opacity: 0.8, fontSize: 12 }}>
                  {forecast.rationale}
                </div>
              ) : null}
            </div>
          ) : null}

          {review ? (
            <Checklist checkboxes={review.checkboxes ?? []} comments={review.comments ?? []} />
          ) : (
            <div
              style={{
                border: "1px solid rgba(0,0,0,0.15)",
                borderRadius: 8,
                padding: 12,
                height: "fit-content",
              }}
            >
              <div style={{ fontWeight: 800 }}>ODE review</div>
              <div style={{ marginTop: 6, opacity: 0.8 }}>
                Review not ready yet. Current status: {run?.status ?? "loading"}.
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

