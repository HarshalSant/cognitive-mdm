"use client";

import { clsx } from "clsx";
import { AlertTriangle, AlertOctagon, Info } from "lucide-react";

const severityConfig = {
  critical: { color: "text-red-400 bg-red-500/10", icon: AlertOctagon },
  high: { color: "text-orange-400 bg-orange-500/10", icon: AlertTriangle },
  medium: { color: "text-yellow-400 bg-yellow-500/10", icon: AlertTriangle },
  low: { color: "text-slate-400 bg-slate-500/10", icon: Info },
};

interface Violation {
  id: string;
  violation_type: string;
  severity: string;
  description: string;
  policy_name: string;
  detected_at: string;
  status: string;
}

export function RecentViolations({ violations }: { violations: Violation[] }) {
  if (!violations.length) {
    return <p className="text-sm text-slate-500 py-4 text-center">No violations found.</p>;
  }

  return (
    <div className="divide-y divide-slate-800">
      {violations.map((v) => {
        const cfg = severityConfig[v.severity as keyof typeof severityConfig] || severityConfig.low;
        const Icon = cfg.icon;
        return (
          <div key={v.id} className="flex items-start gap-4 py-3">
            <div className={clsx("p-1.5 rounded-lg mt-0.5", cfg.color)}>
              <Icon className="w-3.5 h-3.5" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm text-white font-medium truncate">{v.violation_type}</p>
              <p className="text-xs text-slate-400 mt-0.5 truncate">{v.description}</p>
              <p className="text-xs text-slate-600 mt-1">{v.policy_name}</p>
            </div>
            <div className="flex flex-col items-end gap-1 shrink-0">
              <span className={clsx("text-xs px-2 py-0.5 rounded-full font-medium", cfg.color)}>
                {v.severity}
              </span>
              <span className="text-xs text-slate-600">
                {new Date(v.detected_at).toLocaleDateString()}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
