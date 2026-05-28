"use client";

import { useQuery } from "@tanstack/react-query";
import { Shield } from "lucide-react";

interface ExposureData {
  asset: string;
  call_volume: number;
  put_volume: number;
  imbalance: number;
  payout_call: number;
  payout_put: number;
  exposure_usd: number;
}

interface PayoutsData {
  asset: string;
  call: number;
  put: number;
  imbalance: number;
}

async function fetchExposure(asset: string): Promise<ExposureData | null> {
  try {
    const res = await fetch(`/api/risk/exposure/${asset}`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

async function fetchPayouts(asset: string): Promise<PayoutsData | null> {
  try {
    const res = await fetch(`/api/risk/payouts/${asset}`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

function ExposureGauge({ exposure, limit = 100000 }: { exposure: number; limit: number }) {
  const pct = Math.min(100, (Math.abs(exposure) / limit) * 100);
  const color = pct > 80 ? "text-red-400" : pct > 50 ? "text-amber-400" : "text-emerald-400";
  const barColor = pct > 80 ? "bg-red-500" : pct > 50 ? "bg-amber-500" : "bg-emerald-500";
  const direction = exposure >= 0 ? "VENDIDO em CALL" : "VENDIDO em PUT";

  return (
    <div className="space-y-2">
      <div className="flex justify-between text-xs">
        <span>Exposicao Liquida</span>
        <span className={`font-mono ${color}`}>R$ {Math.abs(exposure).toLocaleString()}</span>
      </div>
      <div className="h-2 bg-white/5 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${barColor}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="text-xs text-slate-500">{direction}</div>
    </div>
  );
}

export default function RiskWidget() {
  const asset = "BTCUSD_otc";
  const { data: exposure, isLoading: loadingExpo } = useQuery({
    queryKey: ["risk-exposure", asset],
    queryFn: () => fetchExposure(asset),
    refetchInterval: 10000,
  });
  const { data: payouts, isLoading: loadingPayouts } = useQuery({
    queryKey: ["risk-payouts", asset],
    queryFn: () => fetchPayouts(asset),
    refetchInterval: 10000,
  });

  if (loadingExpo || loadingPayouts) {
    return (
      <div className="bg-[#1a1d2e] border border-white/5 rounded-xl p-5 animate-pulse">
        <div className="h-32 bg-white/5 rounded-lg" />
      </div>
    );
  }

  const expo = exposure || { exposure_usd: 0, call_volume: 0, put_volume: 0, imbalance: 0 };
  const pay = payouts || { call: 0.85, put: 0.85, imbalance: 0 };

  return (
    <div className="bg-[#1a1d2e] border border-white/5 rounded-xl p-5">
      <div className="flex items-center gap-2 mb-4">
        <Shield className="w-5 h-5 text-cyan-400" />
        <h2 className="text-lg font-semibold text-white">Risco da Mesa</h2>
      </div>

      <div className="space-y-4">
        <ExposureGauge exposure={expo.exposure_usd} limit={100000} />

        <div className="grid grid-cols-2 gap-3 pt-2">
          <div className="bg-black/20 rounded-lg p-3">
            <div className="text-xs text-slate-500">Volume CALL</div>
            <div className="text-lg font-mono text-emerald-400">R$ {expo.call_volume.toLocaleString()}</div>
          </div>
          <div className="bg-black/20 rounded-lg p-3">
            <div className="text-xs text-slate-500">Volume PUT</div>
            <div className="text-lg font-mono text-red-400">R$ {expo.put_volume.toLocaleString()}</div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="bg-black/20 rounded-lg p-3">
            <div className="text-xs text-slate-500">Payout CALL</div>
            <div className="text-xl font-mono text-emerald-400">{(pay.call * 100).toFixed(1)}%</div>
          </div>
          <div className="bg-black/20 rounded-lg p-3">
            <div className="text-xs text-slate-500">Payout PUT</div>
            <div className="text-xl font-mono text-red-400">{(pay.put * 100).toFixed(1)}%</div>
          </div>
        </div>

        <div className="text-xs text-slate-600 text-center pt-2">
          Imbalance: {(pay.imbalance * 100).toFixed(1)}%
        </div>
      </div>
    </div>
  );
}
