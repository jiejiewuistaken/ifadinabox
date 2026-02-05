"use client";

import { CheckboxStatus, ReviewComment } from "../lib/types";

function pillColor(status: string) {
  if (status === "true") return "rgba(22,163,74,0.15)";
  if (status === "partial") return "rgba(234,179,8,0.18)";
  return "rgba(220,38,38,0.15)";
}

export function Checklist({
  checkboxes,
  comments,
}: {
  checkboxes: CheckboxStatus[];
  comments: ReviewComment[];
}) {
  return (
    <div style={{ border: "1px solid rgba(0,0,0,0.15)", borderRadius: 8, padding: 12 }}>
      <div style={{ fontWeight: 800, marginBottom: 10 }}>QAG review checklist</div>

      <div style={{ display: "grid", gap: 10 }}>
        {checkboxes.map((c) => (
          <div key={c.id} style={{ display: "grid", gap: 6 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <div
                style={{
                  width: 14,
                  height: 14,
                  borderRadius: 4,
                  background: pillColor(c.status),
                  border: "1px solid rgba(0,0,0,0.2)",
                }}
                title={c.status}
              />
              <div style={{ fontWeight: 700 }}>{c.label}</div>
              <div style={{ marginLeft: "auto", fontFamily: "monospace", opacity: 0.7 }}>
                {c.status}
              </div>
            </div>
            <div style={{ fontSize: 13, opacity: 0.85 }}>{c.rationale}</div>
          </div>
        ))}
      </div>

      <div style={{ marginTop: 14, fontWeight: 800 }}>Review comments</div>
      {comments.length === 0 ? (
        <div style={{ opacity: 0.7, marginTop: 6 }}>No comments.</div>
      ) : (
        <div style={{ marginTop: 8, display: "grid", gap: 10 }}>
          {comments.map((c, idx) => (
            <div
              key={idx}
              style={{
                padding: 10,
                background: "rgba(0,0,0,0.02)",
                border: "1px solid rgba(0,0,0,0.12)",
                borderRadius: 8,
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <div style={{ fontWeight: 800 }}>
                  {c.severity.toUpperCase()} — {c.section}
                </div>
              </div>
              <div style={{ marginTop: 6, fontSize: 13 }}>{c.comment}</div>
              {c.suggestion ? (
                <div style={{ marginTop: 6, fontSize: 13, opacity: 0.85 }}>
                  Suggestion: {c.suggestion}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

