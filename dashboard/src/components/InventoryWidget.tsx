"use client";

import { useQuery } from "@tanstack/react-query";
import { Package, TrendingUp, TrendingDown } from "lucide-react";

interface InventoryItem {
  asset: string;
  net_client: number;
  hedge: number;
  net_exposure: number;
  last_updated: string;
}

async function fetchInventory(): Promise<InventoryItem[]> {
  try {
    const res = await fetch("/api/risk/inventory");
    if (!res.ok) return [];
    return await res.json();
  } catch {
    return [];
  }
}

function InventoryRow({ item }: { item: InventoryItem }) {
  const isPositive = item.net_exposure > 0;
  return (
    <div className="flex items-center justify-between py-2 border-b border-white/5 last:border-0">
      <div>
        <div className="font-medium text-sm">{item.asset}</div>
        <div className="text-xs text-slate-500">
          Cliente: {item.net_client.toFixed(0)} | Hedge: {item.hedge.toFixed(0)}
        </div>
      </div>
      <div className={`flex items-center gap-1 ${isPositive ? "text-red-400" : "text-emerald-400"}`}>
        {isPositive ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
        <span className="font-mono">R$ {Math.abs(item.net_exposure).toFixed(0)}</span>
      </div>
    </div>
  );
}

export default function InventoryWidget() {
  const { data, isLoading } = useQuery({
    queryKey: ["inventory"],
    queryFn: fetchInventory,
    refetchInterval: 15000,
  });

  if (isLoading) {
    return (
      <div className="bg-[#1a1d2e] border border-white/5 rounded-xl p-5 animate-pulse">
        <div className="h-32 bg-white/5 rounded-lg" />
      </div>
    );
  }

  const items = data || [];

  return (
    <div className="bg-[#1a1d2e] border border-white/5 rounded-xl p-5">
      <div className="flex items-center gap-2 mb-4">
        <Package className="w-5 h-5 text-purple-400" />
        <h2 className="text-lg font-semibold text-white">Inventario</h2>
      </div>

      {items.length === 0 ? (
        <p className="text-sm text-slate-500 text-center py-4">Nenhuma posicao</p>
      ) : (
        <div className="space-y-1">
          {items.map((item) => (
            <InventoryRow key={item.asset} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}
