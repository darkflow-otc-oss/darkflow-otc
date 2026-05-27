"use client";

import { useState, useEffect, useRef, useCallback } from "react";

interface WebSocketState {
  data: unknown;
  status: "connecting" | "connected" | "disconnected";
  lastUpdate: number | null;
}

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws";
const MAX_BACKOFF = 30_000;

export function useWebSocket(): WebSocketState {
  const [status, setStatus] = useState<WebSocketState["status"]>("connecting");
  const [data, setData] = useState<unknown>(null);
  const [lastUpdate, setLastUpdate] = useState<number | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const retriesRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;
    setStatus("connecting");

    ws.onopen = () => {
      setStatus("connected");
      retriesRef.current = 0;
    };

    ws.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data);
        setData(parsed);
        setLastUpdate(Date.now());
      } catch {
        // ignore malformed messages
      }
    };

    ws.onclose = () => {
      setStatus("disconnected");
      wsRef.current = null;
      const delay = Math.min(1000 * 2 ** retriesRef.current, MAX_BACKOFF);
      retriesRef.current += 1;
      timerRef.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [connect]);

  return { data, status, lastUpdate };
}
