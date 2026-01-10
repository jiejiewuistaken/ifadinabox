"use client";

export function RunLogPanel({ logs }: { logs: string[] }) {
  return (
    <div
      style={{
        border: "1px solid rgba(0,0,0,0.15)",
        borderRadius: 8,
        padding: 12,
        height: 320,
        overflow: "auto",
        background: "rgba(0,0,0,0.02)",
      }}
    >
      <div style={{ fontWeight: 700, marginBottom: 8 }}>Run log</div>
      {logs.length === 0 ? (
        <div style={{ opacity: 0.7 }}>Waiting for events…</div>
      ) : (
        <div style={{ display: "grid", gap: 6, fontFamily: "monospace", fontSize: 12 }}>
          {logs.map((l, i) => (
            <div key={i}>{l}</div>
          ))}
        </div>
      )}
    </div>
  );
}

