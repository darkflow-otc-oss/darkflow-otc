"use client";

import { useQuery } from "@tanstack/react-query";
import { DollarSign } from "lucide-react";

interface PnLData {
  asset: string;
  unrealized_pnl: number;
  total_pnl: number;
  timestamp: string;
}

async function fetchPnL(asset: string): Promise<PnLData | null> {
  try {
    const res = await fetch(`/api/risk/pnl/${asset}`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export default function PnLWidget() {
  const asset = "BTCUSD_otc";
  const { data, isLoading } = useQuery({
    queryKey: ["pnl", asset],
    queryFn: () => fetchPnL(asset),
    refetchInterval: 30000,
  });

  if (isLoading) {
    return (
      <div className="bg-[#1a1d2e] border border-white/5 rounded-xl p-5 animate-pulse">
        <div className="h-24 bg-white/5 rounded-lg" />
      </div>
    );
  }

  const pnl = data || { unrealized_pnl: 0, total_pnl: 0 };
  const isProfit = pnl.total_pnl >= 0;

  return (
    <div className="bg-[#1a1d2e] border border-white/5 rounded-xl p-5">
      <div className="flex items-center gap-2 mb-4">
        <DollarSign className="w-5 h-5 text-emerald-400" />
        <h2 className="text-lg font-semibold text-white">P&L da Mesa</h2>
      </div>

      <div className="space-y-3">
        <div className="bg-black/20 rounded-lg p-3">
          <div className="text-xs text-slate-500">Total P&L</div>
          <div className={`text-2xl font-mono ${isProfit ? "text-emerald-400" : "text-red-400"}`}>
            {isProfit ? "+" : ""}R$ {pnl.total_pnl.toLocaleString()}
          </div>
        </div>

        <div className="bg-black/20 rounded-lg p-3">
          <div className="text-xs text-slate-500">Nao Realizado</div>
          <div className={`text-lg font-mono ${pnl.unrealized_pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {pnl.unrealized_pnl >= 0 ? "+" : ""}R$ {pnl.unrealized_pnl.toLocaleString()}
          </div>
        </div>

        {data?.timestamp && (
          <div className="text-xs text-slate-600 text-center pt-2">
            Atualizado: {new Date(data.timestamp).toLocaleTimeString()}
          </div>
        )}
      </div>
    </div>
  );
}
