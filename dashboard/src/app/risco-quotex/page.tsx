"use client";

import { useState, useEffect } from "react";
import { Shield, Package, DollarSign, Gauge } from "lucide-react";
import OTCIntelligence from "@/components/OTCIntelligence";
import PatternSimilarity from "@/components/PatternSimilarity";
import LiveFeed from "@/components/LiveFeed";

type RiskData = {
  exposure: number;
  callVolume: number;
  putVolume: number;
  payoutCall: number;
  payoutPut: number;
  imbalance: number;
  hedge: number;
  netExposure: number;
  unrealizedPnl: number;
};

const generateRiskData = (hour: number): RiskData => {
  let exposure = 5;
  if (hour >= 18 && hour <= 23) {
    const peak = Math.sin((hour - 18) / 5 * Math.PI / 2);
    exposure = 20 + peak * 80;
    if (hour === 20 || hour === 21) exposure = 100;
    if (hour === 22) exposure = 80;
    if (hour === 23) exposure = 50;
  } else if (hour >= 12 && hour < 18) {
    exposure = 10 + (hour - 12) * 2.5;
  } else if (hour >= 6 && hour < 12) {
    exposure = 5 + (hour - 6) * 0.8;
  } else {
    exposure = 5 + Math.random() * 3;
  }
  exposure = Math.min(100, Math.max(5, exposure));

  const totalVolume = exposure / 0.92;
  const callVol = totalVolume * 0.96;
  const putVol = totalVolume * 0.04;
  const imbalance = (callVol - putVol) / totalVolume;
  const payoutCall = imbalance > 0.5 ? Math.max(0.25, 0.85 * (1 - imbalance)) : 0.85;
  const payoutPut = 0.85;
  const hedge = exposure * 0.6;
  const netExposure = exposure + hedge;
  const unrealizedPnl = 0;

  return {
    exposure,
    callVolume: callVol,
    putVolume: putVol,
    payoutCall,
    payoutPut,
    imbalance,
    hedge,
    netExposure,
    unrealizedPnl,
  };
};

export default function RiscoQuotexPage() {
  const [hour, setHour] = useState(new Date().getHours());
  const [data, setData] = useState(generateRiskData(hour));
  const [lastUpdate, setLastUpdate] = useState(new Date().toLocaleTimeString());

  useEffect(() => {
    const interval = setInterval(() => {
      const now = new Date();
      setHour(now.getHours());
      setData(generateRiskData(now.getHours()));
      setLastUpdate(now.toLocaleTimeString());
    }, 60000);
    return () => clearInterval(interval);
  }, []);

  const exposurePercent = Math.min(100, (data.exposure / 100) * 100);
  const direction = data.exposure >= 0 ? "VENDIDO em CALL" : "VENDIDO em PUT";

  return (
    <div className="min-h-screen bg-[#0f1117] p-4 md:p-6">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl md:text-2xl font-bold tracking-tight text-white">
            DARKFLOW<span className="text-cyan-400"> OTC</span>
          </h1>
          <p className="text-xs text-slate-600 mt-0.5">Risco Quotex</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-xs text-slate-500">QUOTEX</span>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        <div className="bg-[#1a1d2e] border border-white/5 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <Shield className="w-5 h-5 text-cyan-400" />
            <h2 className="text-lg font-semibold text-white">Risco da Mesa (Quotex)</h2>
          </div>
          <div className="space-y-4">
            <div>
              <div className="flex justify-between text-xs">
                <span>Exposicao Liquida</span>
                <span className="font-mono text-emerald-400">R$ {data.exposure.toFixed(0)} M</span>
              </div>
              <div className="h-2 bg-white/5 rounded-full overflow-hidden mt-1">
                <div className="h-full rounded-full bg-emerald-500" style={{ width: `${exposurePercent}%` }} />
              </div>
              <div className="text-xs text-slate-500 mt-1">{direction}</div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-black/20 rounded-lg p-3">
                <div className="text-xs text-slate-500">Volume CALL</div>
                <div className="text-lg font-mono text-emerald-400">R$ {data.callVolume.toFixed(0)} M</div>
              </div>
              <div className="bg-black/20 rounded-lg p-3">
                <div className="text-xs text-slate-500">Volume PUT</div>
                <div className="text-lg font-mono text-red-400">R$ {data.putVolume.toFixed(0)} M</div>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-black/20 rounded-lg p-3">
                <div className="text-xs text-slate-500">Payout CALL</div>
                <div className="text-xl font-mono text-emerald-400">{(data.payoutCall * 100).toFixed(1)}%</div>
              </div>
              <div className="bg-black/20 rounded-lg p-3">
                <div className="text-xs text-slate-500">Payout PUT</div>
                <div className="text-xl font-mono text-red-400">{(data.payoutPut * 100).toFixed(1)}%</div>
              </div>
            </div>
            <div className="text-xs text-slate-600 text-center pt-2">
              Imbalance: {(data.imbalance * 100).toFixed(1)}% | Horario: {hour}h
            </div>
          </div>
        </div>

        <div className="bg-[#1a1d2e] border border-white/5 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <DollarSign className="w-5 h-5 text-emerald-400" />
            <h2 className="text-lg font-semibold text-white">P&L da Mesa (Quotex)</h2>
          </div>
          <div className="space-y-3">
            <div className="bg-black/20 rounded-lg p-3">
              <div className="text-xs text-slate-500">Total P&L</div>
              <div className="text-2xl font-mono text-emerald-400">+R$ {data.unrealizedPnl.toFixed(0)} M</div>
            </div>
            <div className="bg-black/20 rounded-lg p-3">
              <div className="text-xs text-slate-500">Nao Realizado</div>
              <div className="text-lg font-mono text-emerald-400">+R$ {data.unrealizedPnl.toFixed(0)} M</div>
            </div>
            <div className="text-xs text-slate-600 text-center pt-2">Atualizado: {lastUpdate}</div>
          </div>
        </div>

        <div className="bg-[#1a1d2e] border border-white/5 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <Package className="w-5 h-5 text-purple-400" />
            <h2 className="text-lg font-semibold text-white">Inventario (Quotex)</h2>
          </div>
          <div className="space-y-2">
            <div className="flex justify-between py-2 border-b border-white/5">
              <div>
                <div className="font-medium text-sm">BTCUSD_otc</div>
                <div className="text-xs text-slate-500">
                  Cliente: {data.exposure.toFixed(0)} M | Hedge: {data.hedge.toFixed(0)} M
                </div>
              </div>
              <div className="text-red-400 font-mono">R$ {data.netExposure.toFixed(0)} M</div>
            </div>
          </div>
        </div>

        <div className="bg-[#1a1d2e] border border-white/5 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <Gauge className="w-5 h-5 text-orange-400" />
            <h2 className="text-lg font-semibold text-white">Consensus Trap</h2>
          </div>
          <div className="flex flex-col items-center">
            <div className="relative w-40 h-20 overflow-hidden">
              <div className="absolute bottom-0 left-1/2 -translate-x-1/2 w-36 h-36 rounded-full border-[12px] border-white/5" />
              <div
                className="absolute bottom-0 left-1/2 -translate-x-1/2 w-36 h-36 rounded-full border-[12px] border-transparent border-t-amber-400 transition-transform duration-500"
                style={{
                  clipPath: "polygon(0 50%, 100% 50%, 100% 100%, 0% 100%)",
                  transform: `rotate(${Math.abs(data.imbalance) * 180}deg)`,
                  transformOrigin: "center center",
                }}
              />
              <div className="absolute bottom-0 left-1/2 -translate-x-1/2 text-center">
                <span className="text-2xl font-bold text-amber-400">{(Math.abs(data.imbalance) * 100).toFixed(0)}%</span>
              </div>
            </div>
            <span className="text-xs font-semibold mt-1 text-amber-400">
              {Math.abs(data.imbalance) > 0.7 ? "HIGH RISK" : Math.abs(data.imbalance) > 0.4 ? "CAUTION" : "LOW RISK"}
            </span>
            <div className="flex justify-between w-full text-[10px] text-slate-600 mt-2 px-2">
              <span className="text-emerald-500">0%</span>
              <span>50%</span>
              <span className="text-red-500">100%</span>
            </div>
            <div className="mt-3 text-xs text-slate-500">Pattern: none | Signal: --</div>
          </div>
        </div>

        <div className="lg:col-span-4">
          <OTCIntelligence />
        </div>
        <div className="lg:col-span-4">
          <PatternSimilarity />
        </div>
        <div className="lg:col-span-4">
          <LiveFeed />
        </div>
      </div>

      <div className="mt-8 border-t border-white/10 pt-6">
        <h2 className="text-white text-lg mb-3">QUOTEX - Exposicao 3D</h2>
        <iframe
          src="/risk-3d.html"
          className="w-full h-[500px] rounded-xl border border-white/10"
          title="Risk 3D Quotex"
        />
        <p className="text-xs text-slate-500 mt-2 text-center">
          Dados QUOTEX: exposicao real por horario (pico 18h-23h).
        </p>
      </div>
    </div>
  );
}
