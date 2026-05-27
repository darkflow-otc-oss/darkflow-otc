"use client";

import { useQuery } from "@tanstack/react-query";
import { Layers } from "lucide-react";

interface SimilarPattern {
  id: string;
  similarity?: number;
  cosine_score?: number;
  score?: number;
  pattern_type?: string;
  detected_at?: string;
  outcome?: string;
  metadata?: Record<string, unknown>;
}

async function fetchSimilar(asset: string, limit: number): Promise<SimilarPattern[]> {
  const res = await fetch(`/api/patterns/similar?asset=${asset}&limit=${limit}`);
  if (!res.ok) return [];
  const data = await res.json();
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.data)) return data.data;
  if (Array.isArray(data?.matches)) return data.matches;
  return [];
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  const colors: Record<string, string> = {
    WIN: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
    LOSS: "bg-red-500/20 text-red-400 border-red-500/30",
    UNKNOWN: "bg-slate-500/20 text-slate-400 border-slate-500/30",
  };
  const label = outcome ?? "UNKNOWN";
  return (
    <span className={`text-xs px-2 py-0.5 rounded border ${colors[label] ?? colors.UNKNOWN}`}>
      {label}
    </span>
  );
}

function SimilarityBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 80 ? "bg-emerald-500" : pct >= 50 ? "bg-amber-500" : "bg-slate-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-white/5 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono text-slate-400 w-10 text-right">{pct}%</span>
    </div>
  );
}

export default function PatternSimilarity() {
  const { data, isLoading } = useQuery({
    queryKey: ["similar", "BTCUSD_otc"],
    queryFn: () => fetchSimilar("BTCUSD_otc", 5),
    refetchInterval: 10000,
  });

  const items = data ?? [];

  return (
    <div className="bg-[#1a1d2e] border border-white/5 rounded-xl p-5">
      <div className="flex items-center gap-2 mb-4">
        <Layers className="w-5 h-5 text-violet-400" />
        <h2 className="text-lg font-semibold text-white">Pattern Similarity</h2>
      </div>

      {isLoading && (
        <div className="animate-pulse space-y-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-8 bg-white/5 rounded-lg" />
          ))}
        </div>
      )}

      {!isLoading && items.length === 0 && (
        <p className="text-sm text-slate-500">No similar patterns found</p>
      )}

      {items.map((item, i) => {
        const score = item.cosine_score ?? item.similarity ?? item.score ?? 0;
        return (
          <div key={item.id ?? i} className="mb-3 last:mb-0">
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm text-white font-mono truncate max-w-[140px]">
                {item.pattern_type ?? item.id ?? `#${i + 1}`}
              </span>
              <OutcomeBadge outcome={item.outcome ?? "UNKNOWN"} />
            </div>
            <SimilarityBar value={score} />
            {item.detected_at && (
              <span className="text-xs text-slate-600 mt-0.5 block">
                {new Date(item.detected_at).toLocaleString()}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
