"use client";

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

  const pdfUrl = `${BACKEND_URL}/api/runs/${runId}/pdf?disposition=inline`;
  const review = run?.review;

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
            href={`${BACKEND_URL}/api/runs/${runId}/pdf?disposition=attachment`}
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
          <iframe
            title="COSOP PDF preview"
            src={pdfUrl}
            style={{ width: "100%", height: 640, border: 0 }}
          />
        </div>

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
  );
}

