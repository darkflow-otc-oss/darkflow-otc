"use client";

import { useQuery } from "@tanstack/react-query";
import { Gauge } from "lucide-react";

interface DetectionResult {
  pattern_type?: string;
  confidence?: number;
  signal?: string;
  direction?: string;
  detected_at?: string;
  asset?: string;
  trap_type?: string;
}

async function fetchLatestDetection(): Promise<DetectionResult | null> {
  const res = await fetch("/api/patterns/detect");
  if (!res.ok) return null;
  const data = await res.json();
  return data?.data ?? data;
}

function TrapGauge({ confidence }: { confidence: number }) {
  const pct = Math.round(confidence * 100);
  const rotation = (pct / 100) * 180;
  const zoneColors: Record<string, string> = {
    safe: "text-emerald-400",
    warning: "text-amber-400",
    danger: "text-red-400",
  };
  const zone = pct <= 40 ? "safe" : pct <= 70 ? "warning" : "danger";
  const zoneLabel = pct <= 40 ? "LOW RISK" : pct <= 70 ? "CAUTION" : "HIGH RISK";

  return (
    <div className="flex flex-col items-center">
      <div className="relative w-40 h-20 overflow-hidden">
        <div className="absolute bottom-0 left-1/2 -translate-x-1/2 w-36 h-36 rounded-full border-[12px] border-white/5" />
        <div
          className="absolute bottom-0 left-1/2 -translate-x-1/2 w-36 h-36 rounded-full border-[12px] border-transparent border-t-amber-400 transition-transform duration-500"
          style={{
            clipPath: "polygon(0 50%, 100% 50%, 100% 100%, 0% 100%)",
            transform: `rotate(${rotation}deg)`,
            transformOrigin: "center center",
          }}
        />
        <div className="absolute bottom-0 left-1/2 -translate-x-1/2 text-center">
          <span className={`text-2xl font-bold ${zoneColors[zone]}`}>{pct}%</span>
        </div>
      </div>
      <span className={`text-xs font-semibold mt-1 ${zoneColors[zone]}`}>{zoneLabel}</span>
      <div className="flex justify-between w-full text-[10px] text-slate-600 mt-2 px-2">
        <span className="text-emerald-500">0%</span>
        <span>50%</span>
        <span className="text-red-500">100%</span>
      </div>
    </div>
  );
}

export default function ConsensusTrap() {
  const { data, isLoading } = useQuery({
    queryKey: ["latest-detection"],
    queryFn: fetchLatestDetection,
    refetchInterval: 3000,
  });

  const confidence = data?.confidence ?? 0;

  return (
    <div className="bg-[#1a1d2e] border border-white/5 rounded-xl p-5">
      <div className="flex items-center gap-2 mb-4">
        <Gauge className="w-5 h-5 text-orange-400" />
        <h2 className="text-lg font-semibold text-white">Consensus Trap</h2>
      </div>

      {isLoading && (
        <div className="animate-pulse flex flex-col items-center gap-3">
          <div className="h-20 w-40 bg-white/5 rounded-full" />
        </div>
      )}

      {data && (
        <div className="space-y-3">
          <TrapGauge confidence={confidence} />
          <div className="bg-white/5 rounded-lg px-3 py-2">
            <div className="flex justify-between text-sm">
              <span className="text-slate-400">Pattern</span>
              <span className="text-white font-mono">
                {data.pattern_type ?? "none"}
              </span>
            </div>
            {data.trap_type && (
              <div className="flex justify-between text-sm mt-1">
                <span className="text-slate-400">Trap Type</span>
                <span className="text-orange-400 font-mono text-xs">{data.trap_type}</span>
              </div>
            )}
            <div className="flex justify-between text-sm mt-1">
              <span className="text-slate-400">Signal</span>
              <span
                className={`font-mono text-xs ${
                  data.signal === "PUT" ? "text-red-400" : "text-emerald-400"
                }`}
              >
                {data.signal ?? "--"}
              </span>
            </div>
          </div>
        </div>
      )}

      {!isLoading && !data && (
        <p className="text-sm text-slate-500 text-center">Awaiting signal...</p>
      )}
    </div>
  );
}
