import { useEffect, useRef, useState } from "react";
import { wsUrl } from "@/lib/api";

export interface WsMessage {
  type: string;
  [k: string]: unknown;
}

/**
 * Realtime link to the backend (PLAN.md §5.5). Auto-reconnects with backoff and
 * surfaces a `connected` flag for the LIVE indicator. `onMessage` fires for
 * every server push (e.g. `job_updated`).
 */
export function useWebSocket(onMessage?: (msg: WsMessage) => void) {
  const [connected, setConnected] = useState(false);
  const cbRef = useRef(onMessage);
  cbRef.current = onMessage;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout>;
    let closed = false;

    const connect = () => {
      ws = new WebSocket(wsUrl());
      ws.onopen = () => {
        retry = 0;
        setConnected(true);
      };
      ws.onclose = () => {
        setConnected(false);
        if (closed) return;
        retry = Math.min(retry + 1, 6);
        timer = setTimeout(connect, 500 * 2 ** retry); // capped exponential backoff
      };
      ws.onerror = () => ws?.close();
      ws.onmessage = (ev) => {
        try {
          cbRef.current?.(JSON.parse(ev.data) as WsMessage);
        } catch {
          /* ignore non-JSON frames */
        }
      };
    };

    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, []);

  return { connected };
}
