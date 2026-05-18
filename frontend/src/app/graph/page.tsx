"use client";

import { useState } from "react";
import { KnowledgeGraph } from "@/components/graph/KnowledgeGraph";
import { Search } from "lucide-react";

export default function GraphPage() {
  const [entityId, setEntityId] = useState("");
  const [activeId, setActiveId] = useState("");
  const [depth, setDepth] = useState(2);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Knowledge Graph</h1>
        <p className="text-slate-400 mt-1">
          Explore entity relationships, lineage, and dependencies
        </p>
      </div>

      <div className="bg-surface-900 rounded-xl border border-slate-800 p-5">
        <div className="flex gap-3 mb-5">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              value={entityId}
              onChange={(e) => setEntityId(e.target.value)}
              placeholder="Enter entity ID..."
              className="w-full pl-9 pr-4 py-2.5 bg-surface-950 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 outline-none focus:border-brand-500"
            />
          </div>
          <select
            value={depth}
            onChange={(e) => setDepth(Number(e.target.value))}
            className="px-3 py-2.5 bg-surface-950 border border-slate-700 rounded-lg text-sm text-white outline-none"
          >
            {[1, 2, 3, 4, 5].map((d) => (
              <option key={d} value={d}>Depth {d}</option>
            ))}
          </select>
          <button
            onClick={() => setActiveId(entityId)}
            disabled={!entityId}
            className="px-5 py-2.5 bg-brand-600 hover:bg-brand-500 disabled:opacity-40 rounded-lg text-sm font-medium text-white transition-colors"
          >
            Explore
          </button>
        </div>

        {activeId ? (
          <KnowledgeGraph nodeId={activeId} depth={depth} />
        ) : (
          <div className="cy-container flex items-center justify-center bg-surface-950 rounded-lg">
            <p className="text-slate-500 text-sm">Enter an entity ID above to visualise its graph</p>
          </div>
        )}
      </div>
    </div>
  );
}
