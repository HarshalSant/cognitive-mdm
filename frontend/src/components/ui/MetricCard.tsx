import { clsx } from "clsx";
import { ReactNode } from "react";

const colorMap = {
  blue: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  green: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  yellow: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  red: "bg-red-500/10 text-red-400 border-red-500/20",
  purple: "bg-purple-500/10 text-purple-400 border-purple-500/20",
};

interface MetricCardProps {
  title: string;
  value: string | number;
  icon: ReactNode;
  trend?: string;
  color?: keyof typeof colorMap;
}

export function MetricCard({ title, value, icon, trend, color = "blue" }: MetricCardProps) {
  const trendPositive = trend?.startsWith("+");

  return (
    <div className="bg-surface-900 rounded-xl border border-slate-800 p-5 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-slate-400 uppercase tracking-wide">{title}</span>
        <div className={clsx("p-2 rounded-lg border", colorMap[color])}>{icon}</div>
      </div>
      <div className="flex items-end justify-between">
        <span className="text-2xl font-bold text-white">{value}</span>
        {trend && (
          <span
            className={clsx(
              "text-xs font-medium",
              trendPositive ? "text-emerald-400" : "text-red-400"
            )}
          >
            {trend} vs last month
          </span>
        )}
      </div>
    </div>
  );
}
