"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { Edge, Node } from "reactflow";

import { getRun } from "../../lib/api";
import { useRunEvents } from "../../lib/useRunEvents";
import { RunEvent } from "../../lib/types";
import { StakeholderGraph } from "../../components/StakeholderGraph";
import { RunLogPanel } from "../../components/RunLogPanel";

function toColor(status: string) {
  if (status === "writing") return "#2563eb";
  if (status === "reviewing") return "#7c3aed";
  if (status === "completed") return "#16a34a";
  if (status === "failed") return "#dc2626";
  return "#64748b";
}

export default function RunPage() {
  const params = useParams<{ runId: string }>();
  const runId = params.runId;

  const { data: run } = useSWR(runId ? ["run", runId] : null, () => getRun(runId), {
    refreshInterval: 1000,
  });

  const [logs, setLogs] = useState<string[]>([]);
  const [nodesState, setNodesState] = useState<Record<string, { label: string; status: string }>>({
    cd: { label: "Country Director", status: "idle" },
    cdt_econ: { label: "CDT Economist", status: "idle" },
    cdt_tech: { label: "CDT Technical", status: "idle" },
    gov_mof: { label: "Ministry of Finance", status: "idle" },
    gov_moa: { label: "Ministry of Agriculture", status: "idle" },
    osc: { label: "OSC Review", status: "idle" },
    qag: { label: "QAG Desk Review", status: "idle" },
    vp: { label: "VP Endorsement", status: "idle" },
    president: { label: "President Approval", status: "idle" },
    eb: { label: "EB Consultation", status: "idle" },
  });

  const [edgesState, setEdgesState] = useState<{ source: string; target: string; label?: string }[]>([
    { source: "gov_mof", target: "cd", label: "priorities" },
    { source: "gov_moa", target: "cd", label: "priorities" },
    { source: "cdt_econ", target: "cd", label: "technical review" },
    { source: "cdt_tech", target: "cd", label: "technical review" },
    { source: "cd", target: "osc", label: "OSC review" },
    { source: "osc", target: "qag", label: "QAG desk review" },
    { source: "qag", target: "vp", label: "endorsement" },
    { source: "vp", target: "president", label: "approval" },
    { source: "president", target: "eb", label: "consultation" },
  ]);

  useRunEvents(runId, (ev: RunEvent) => {
    if (ev.type === "log") {
      setLogs((prev) => [...prev, `${ev.ts}  ${ev.payload?.message ?? ""}`]);
    }
    if (ev.type === "graph_update") {
      // initial graph: nodes/edges
      if (ev.payload?.nodes?.length) {
        const next: Record<string, { label: string; status: string }> = {};
        for (const n of ev.payload.nodes) {
          next[n.id] = { label: n.label ?? n.id, status: n.status ?? "idle" };
        }
        setNodesState(next);
      }
      if (ev.payload?.edges?.length) {
        setEdgesState(ev.payload.edges);
      }
      // incremental status update: { node_status: {id: status} }
      if (ev.payload?.node_status) {
        setNodesState((prev) => {
          const copy = { ...prev };
          for (const [id, st] of Object.entries(ev.payload.node_status)) {
            copy[id] = { label: copy[id]?.label ?? id, status: String(st) };
          }
          return copy;
        });
      }
    }
    if (ev.type === "run_status") {
      const s = ev.payload?.status;
      if (s) {
        setLogs((prev) => [...prev, `${ev.ts}  STATUS: ${s}`]);
      }
    }
  });

  const nodes: Node[] = useMemo(() => {
    const ids = Object.keys(nodesState);
    return ids.map((id, idx) => {
      const n = nodesState[id];
      return {
        id,
        position: { x: 80 + idx * 220, y: 120 },
        data: { label: `${n.label}\n(${n.status})` },
        style: {
          border: `2px solid ${toColor(n.status)}`,
          borderRadius: 10,
          padding: 10,
          width: 200,
          whiteSpace: "pre-line",
        },
      };
    });
  }, [nodesState]);

  const edges: Edge[] = useMemo(() => {
    return edgesState.map((e, idx) => ({
      id: `e-${idx}`,
      source: e.source,
      target: e.target,
      label: e.label,
      animated: true,
    }));
  }, [edgesState]);

  const status = run?.status ?? "loading";
  const completed = status === "completed";

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 800 }}>Simulation</h1>
          <div style={{ fontFamily: "monospace", opacity: 0.8 }}>run_id: {runId}</div>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <div style={{ fontWeight: 700 }}>Status: {status}</div>
          <Link
            href={`/runs/${runId}/preview`}
            style={{
              padding: "8px 12px",
              border: "1px solid rgba(0,0,0,0.2)",
              borderRadius: 8,
              opacity: completed ? 1 : 0.5,
              pointerEvents: completed ? "auto" : "none",
            }}
          >
            Go to Preview
          </Link>
        </div>
      </div>

      <div style={{ marginTop: 16, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <StakeholderGraph nodes={nodes} edges={edges} />
        <RunLogPanel logs={logs} />
      </div>

      <div style={{ marginTop: 12, opacity: 0.8, fontSize: 13 }}>
        Tip: This run may evaluate multiple candidates with multi-agent review. When completed, open Preview to view the PDF carousel and checklist.
      </div>
    </div>
  );
}

