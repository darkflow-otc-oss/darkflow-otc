"use client";

import { useWebSocket } from "@/hooks/useWebSocket";
import { ArrowUpCircle, ArrowDownCircle, Zap, TrendingUp, TrendingDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";

interface SignalItem {
  action: string;
  pattern: string;
  confidence: number;
  timestamp: string;
  asset: string;
}

export default function SignalAlert() {
  const { data } = useWebSocket();
  const [lastSignal, setLastSignal] = useState<SignalItem | null>(null);
  const [history, setHistory] = useState<SignalItem[]>([]);
  const audioCtxRef = useRef<AudioContext | null>(null);

  useEffect(() => {
    if (!data) return;
    const raw = data as Record<string, unknown>;
    if (raw.type !== "signal") return;

    const signal: SignalItem = {
      action: (raw.action as string) ?? "COMPRA",
      pattern: (raw.pattern as string) ?? "unknown",
      confidence: (raw.confidence as number) ?? 0,
      timestamp: (raw.timestamp as string) ?? new Date().toISOString(),
      asset: (raw.asset as string) ?? "BTCUSD_otc",
    };

    setLastSignal(signal);
    setHistory((prev) => [signal, ...prev].slice(0, 5));
    playBeep(signal.action);
  }, [data]);

  function playBeep(action: string) {
    try {
      if (!audioCtxRef.current) {
        audioCtxRef.current = new (window.AudioContext ||
          (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
      }
      const ctx = audioCtxRef.current;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = "square";
      osc.frequency.value = action === "COMPRA" ? 880 : 440;
      gain.gain.value = 0.08;
      osc.start();
      osc.stop(ctx.currentTime + 0.15);
    } catch {
      // audio not available
    }
  }

  const isBuy = lastSignal?.action === "COMPRA";

  return (
    <div className="bg-[#1a1d2e] border border-white/5 rounded-xl p-5">
      <div className="flex items-center gap-2 mb-4">
        <Zap className="w-5 h-5 text-amber-400" />
        <h2 className="text-lg font-semibold text-white">Signal Alerts</h2>
        {lastSignal && (
          <span className="text-xs text-slate-500 ml-auto">
            {new Date(lastSignal.timestamp).toLocaleTimeString()}
          </span>
        )}
      </div>

      {/* Last Signal */}
      {lastSignal ? (
        <div
          className={`rounded-lg p-4 mb-4 ${
            isBuy
              ? "bg-emerald-500/10 border border-emerald-500/30"
              : "bg-red-500/10 border border-red-500/30"
          }`}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              {isBuy ? (
                <ArrowUpCircle className="w-8 h-8 text-emerald-400" />
              ) : (
                <ArrowDownCircle className="w-8 h-8 text-red-400" />
              )}
              <div>
                <span
                  className={`text-xl font-bold ${
                    isBuy ? "text-emerald-400" : "text-red-400"
                  }`}
                >
                  {lastSignal.action}
                </span>
                <p className="text-sm text-slate-400">{lastSignal.pattern}</p>
              </div>
            </div>
            <div className="text-right">
              <span className="text-2xl font-bold text-white">
                {(lastSignal.confidence * 100).toFixed(0)}%
              </span>
              <p className="text-xs text-slate-500">confidence</p>
            </div>
          </div>
        </div>
      ) : (
        <div className="rounded-lg p-4 mb-4 bg-white/5 text-center">
          <p className="text-sm text-slate-500">Waiting for signals...</p>
        </div>
      )}

      {/* History */}
      {history.length > 0 && (
        <div>
          <h3 className="text-xs text-slate-500 mb-2 uppercase tracking-wider">
            Last 5 Signals
          </h3>
          <div className="space-y-2">
            {history.map((s, i) => (
              <div
                key={i}
                className="flex items-center justify-between bg-white/5 rounded-lg px-3 py-2"
              >
                <div className="flex items-center gap-2">
                  {s.action === "COMPRA" ? (
                    <TrendingUp className="w-4 h-4 text-emerald-400" />
                  ) : (
                    <TrendingDown className="w-4 h-4 text-red-400" />
                  )}
                  <span className="text-sm text-white">{s.pattern}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span
                    className={`text-xs font-semibold ${
                      s.action === "COMPRA" ? "text-emerald-400" : "text-red-400"
                    }`}
                  >
                    {s.action}
                  </span>
                  <span className="text-xs text-slate-500">
                    {(s.confidence * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
