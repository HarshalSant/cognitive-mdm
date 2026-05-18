"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Loader2, ZoomIn, ZoomOut, RotateCcw } from "lucide-react";

interface GraphNode {
  id: string;
  label: string;
  props: Record<string, unknown>;
}
interface GraphEdge {
  type: string;
  start: string;
  end: string;
  props: Record<string, unknown>;
}

interface Props {
  nodeId: string;
  depth?: number;
}

export function KnowledgeGraph({ nodeId, depth = 2 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nodeCount, setNodeCount] = useState(0);
  const [edgeCount, setEdgeCount] = useState(0);
  const cyRef = useRef<any>(null);

  useEffect(() => {
    if (!nodeId || !containerRef.current) return;

    setLoading(true);
    setError(null);

    api
      .get(`/api/v1/graph/neighborhood/${nodeId}`, { params: { depth } })
      .then(async (res) => {
        const { nodes, edges } = res.data as { nodes: GraphNode[]; edges: GraphEdge[] };

        // Dynamic import to avoid SSR issues
        const cytoscape = (await import("cytoscape")).default;

        const elements = [
          ...nodes.map((n) => ({
            data: {
              id: n.id,
              label: (n.props as any)?.name || n.label || n.id.slice(0, 8),
              type: n.label,
              ...n.props,
            },
          })),
          ...edges.map((e, i) => ({
            data: {
              id: `e-${i}`,
              source: e.start,
              target: e.end,
              label: e.type,
            },
          })),
        ];

        if (cyRef.current) {
          cyRef.current.destroy();
        }

        cyRef.current = cytoscape({
          container: containerRef.current!,
          elements,
          style: [
            {
              selector: "node",
              style: {
                "background-color": "#6366f1",
                "border-width": 2,
                "border-color": "#818cf8",
                label: "data(label)",
                color: "#e2e8f0",
                "font-size": "11px",
                "text-valign": "bottom",
                "text-margin-y": 6,
                width: 36,
                height: 36,
              },
            },
            {
              selector: `node[id = "${nodeId}"]`,
              style: {
                "background-color": "#f59e0b",
                "border-color": "#fbbf24",
                width: 48,
                height: 48,
              },
            },
            {
              selector: "edge",
              style: {
                width: 1.5,
                "line-color": "#334155",
                "target-arrow-color": "#334155",
                "target-arrow-shape": "triangle",
                "curve-style": "bezier",
                label: "data(label)",
                color: "#64748b",
                "font-size": "9px",
                "text-rotation": "autorotate",
              },
            },
          ],
          layout: { name: "cose", animate: true, padding: 30 },
        });

        setNodeCount(nodes.length);
        setEdgeCount(edges.length);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });

    return () => {
      cyRef.current?.destroy();
    };
  }, [nodeId, depth]);

  return (
    <div className="relative">
      {/* Controls */}
      <div className="absolute top-3 right-3 z-10 flex gap-1">
        <button
          onClick={() => cyRef.current?.zoom(cyRef.current.zoom() * 1.2)}
          className="p-1.5 bg-surface-800 rounded border border-slate-700 hover:bg-slate-700 transition-colors"
        >
          <ZoomIn className="w-3.5 h-3.5 text-slate-300" />
        </button>
        <button
          onClick={() => cyRef.current?.zoom(cyRef.current.zoom() * 0.8)}
          className="p-1.5 bg-surface-800 rounded border border-slate-700 hover:bg-slate-700 transition-colors"
        >
          <ZoomOut className="w-3.5 h-3.5 text-slate-300" />
        </button>
        <button
          onClick={() => cyRef.current?.fit()}
          className="p-1.5 bg-surface-800 rounded border border-slate-700 hover:bg-slate-700 transition-colors"
        >
          <RotateCcw className="w-3.5 h-3.5 text-slate-300" />
        </button>
      </div>

      {/* Stats */}
      {!loading && (
        <div className="absolute bottom-3 left-3 z-10 flex gap-3 text-xs text-slate-400">
          <span>{nodeCount} nodes</span>
          <span>{edgeCount} edges</span>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center z-10">
          <Loader2 className="w-6 h-6 text-brand-400 animate-spin" />
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center z-10 text-sm text-red-400">
          {error}
        </div>
      )}

      <div ref={containerRef} className="cy-container bg-surface-950 rounded-lg" />
    </div>
  );
}
