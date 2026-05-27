"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, TrendingUp, TrendingDown, Minus } from "lucide-react";

interface Probability {
  asset: string;
  pattern_type: string;
  total_occurrences: number;
  wins: number;
  losses: number;
  probability: number;
  weighted_probability: number;
  classification: string;
  recommendation: string;
}

async function fetchProbability(asset: string): Promise<Probability | null> {
  const res = await fetch(`/api/patterns/probability?asset=${asset}`);
  if (!res.ok) return null;
  const data = await res.json();
  return data.data ?? data;
}

function ClassificationBadge({ label }: { label: string }) {
  const colors: Record<string, string> = {
    HIGH: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
    MEDIUM: "bg-amber-500/20 text-amber-400 border-amber-500/30",
    LOW: "bg-red-500/20 text-red-400 border-red-500/30",
    UNKNOWN: "bg-slate-500/20 text-slate-400 border-slate-500/30",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded border ${colors[label] ?? colors.UNKNOWN}`}>
      {label}
    </span>
  );
}

function RecommendationBadge({ rec }: { rec: string }) {
  const config: Record<string, { icon: React.ReactNode; color: string }> = {
    ENTER: { icon: <TrendingUp className="w-4 h-4" />, color: "text-emerald-400" },
    WATCH: { icon: <Minus className="w-4 h-4" />, color: "text-amber-400" },
    SKIP: { icon: <TrendingDown className="w-4 h-4" />, color: "text-red-400" },
  };
  const c = config[rec] ?? config.SKIP;
  return (
    <span className={`flex items-center gap-1 text-sm font-semibold ${c.color}`}>
      {c.icon} {rec}
    </span>
  );
}

function Skeleton() {
  return (
    <div className="animate-pulse space-y-3">
      {[...Array(3)].map((_, i) => (
        <div key={i} className="h-10 bg-white/5 rounded-lg" />
      ))}
    </div>
  );
}

export default function OTCIntelligence() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["probability", "BTCUSD_otc"],
    queryFn: () => fetchProbability("BTCUSD_otc"),
    refetchInterval: 5000,
  });

  return (
    <div className="bg-[#1a1d2e] border border-white/5 rounded-xl p-5">
      <div className="flex items-center gap-2 mb-4">
        <AlertTriangle className="w-5 h-5 text-cyan-400" />
        <h2 className="text-lg font-semibold text-white">OTC Intelligence</h2>
      </div>

      {isLoading && <Skeleton />}

      {error && (
        <div className="text-red-400 text-sm">Failed to fetch intelligence data</div>
      )}

      {data && (
        <div className="grid grid-cols-2 gap-3">
          <Stat label="Asset" value={data.asset ?? "BTCUSD_otc"} />
          <Stat label="Pattern" value={data.pattern_type ?? "--"} />
          <Stat label="Win Rate" value={`${((data.probability ?? 0) * 100).toFixed(1)}%`} />
          <Stat label="Weighted WR" value={`${((data.weighted_probability ?? 0) * 100).toFixed(1)}%`} />
          <div className="col-span-2 flex items-center justify-between bg-white/5 rounded-lg px-3 py-2">
            <span className="text-sm text-slate-400">Classification</span>
            <ClassificationBadge label={data.classification ?? "UNKNOWN"} />
          </div>
          <div className="col-span-2 flex items-center justify-between bg-white/5 rounded-lg px-3 py-2">
            <span className="text-sm text-slate-400">Recommendation</span>
            <RecommendationBadge rec={data.recommendation ?? "SKIP"} />
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white/5 rounded-lg px-3 py-2">
      <span className="text-xs text-slate-500 block">{label}</span>
      <span className="text-sm font-mono text-white">{value}</span>
    </div>
  );
}
