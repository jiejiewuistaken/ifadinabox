"use client";

import { useEffect, useRef } from "react";

import { RunEvent } from "./types";
import { WS_BACKEND_URL } from "./api";

export function useRunEvents(
  runId: string,
  onEvent: (ev: RunEvent) => void,
) {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    if (!runId) return;
    const ws = new WebSocket(`${WS_BACKEND_URL}/ws/runs/${runId}`);

    ws.onmessage = (msg) => {
      try {
        const ev = JSON.parse(msg.data) as RunEvent;
        onEventRef.current(ev);
      } catch {
        // ignore
      }
    };

    return () => ws.close();
  }, [runId]);
}

