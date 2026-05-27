"use client";

import { useWebSocket } from "@/hooks/useWebSocket";
import { Radio, Wifi, WifiOff } from "lucide-react";
import { useEffect, useState } from "react";

interface TickItem {
  ts?: string;
  timestamp?: string;
  asset?: string;
  price?: number;
  close?: number;
  volume?: number;
}

export default function LiveFeed() {
  const { data, status } = useWebSocket();
  const [ticks, setTicks] = useState<TickItem[]>([]);

  useEffect(() => {
    if (!data) return;
    const raw = data as Record<string, unknown>;
    if (raw.type === "signal") return;
    const tick: TickItem = {
      ts: (raw.ts ?? raw.timestamp ?? new Date().toISOString()) as string,
      asset: (raw.asset ?? "BTCUSD_otc") as string,
      price: (raw.price ?? raw.close ?? raw.bid ?? 0) as number,
      volume: (raw.volume ?? 1) as number,
    };
    setTicks((prev) => [tick, ...prev].slice(0, 20));
  }, [data]);

  return (
    <div className="bg-[#1a1d2e] border border-white/5 rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Radio className="w-5 h-5 text-cyan-400" />
          <h2 className="text-lg font-semibold text-white">Live Feed</h2>
        </div>
        <div className="flex items-center gap-2">
          {status === "connected" ? (
            <Wifi className="w-4 h-4 text-emerald-400" />
          ) : (
            <WifiOff className="w-4 h-4 text-red-400" />
          )}
          <span
            className={`text-xs ${
              status === "connected" ? "text-emerald-400" : "text-red-400"
            }`}
          >
            {status === "connected" ? "LIVE" : "OFFLINE"}
          </span>
        </div>
      </div>

      {ticks.length === 0 && (
        <p className="text-sm text-slate-500 text-center py-4">
          Waiting for data...
        </p>
      )}

      {ticks.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-600 text-xs">
                <th className="text-left py-1 font-medium">Time</th>
                <th className="text-left py-1 font-medium">Asset</th>
                <th className="text-right py-1 font-medium">Price</th>
                <th className="text-right py-1 font-medium">Vol</th>
              </tr>
            </thead>
            <tbody>
              {ticks.map((t, i) => (
                <tr
                  key={i}
                  className={`border-t border-white/5 ${i === 0 ? "bg-cyan-400/5" : ""}`}
                >
                  <td className="py-1.5 font-mono text-xs text-slate-500">
                    {formatTime(t.ts)}
                  </td>
                  <td className="py-1.5 font-mono text-xs text-slate-400">
                    {t.asset}
                  </td>
                  <td className="py-1.5 font-mono text-xs text-right text-white">
                    {formatPrice(t.price)}
                  </td>
                  <td className="py-1.5 font-mono text-xs text-right text-slate-500">
                    {t.volume}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function formatTime(ts?: string): string {
  if (!ts) return "--:--:--";
  try {
    return new Date(ts).toLocaleTimeString();
  } catch {
    return ts.slice(11, 19) ?? ts;
  }
}

function formatPrice(price?: number): string {
  if (price == null) return "--";
  return price.toFixed(5);
}
