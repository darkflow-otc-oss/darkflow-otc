import OTCIntelligence from "@/components/OTCIntelligence";
import PatternSimilarity from "@/components/PatternSimilarity";
import ConsensusTrap from "@/components/ConsensusTrap";
import LiveFeed from "@/components/LiveFeed";
import SignalAlert from "@/components/SignalAlert";

export default function Home() {
  return (
    <div className="min-h-screen bg-[#0f1117] p-4 md:p-6">
      {/* Header */}
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl md:text-2xl font-bold tracking-tight text-white">
            DARKFLOW<span className="text-cyan-400"> OTC</span>
          </h1>
          <p className="text-xs text-slate-600 mt-0.5">AI Engine Dashboard</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-xs text-slate-500">SYSTEM ONLINE</span>
        </div>
      </header>

      {/* Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Signal Alert — top full width */}
        <div className="lg:col-span-3">
          <SignalAlert />
        </div>

        {/* OTC Intelligence — full width */}
        <div className="lg:col-span-3">
          <OTCIntelligence />
        </div>

        {/* Pattern Similarity + Consensus Trap — middle row */}
        <div className="lg:col-span-2">
          <PatternSimilarity />
        </div>
        <div className="lg:col-span-1">
          <ConsensusTrap />
        </div>

        {/* Live Feed — bottom full width */}
        <div className="lg:col-span-3">
          <LiveFeed />
        </div>
      </div>
    </div>
  );
}
