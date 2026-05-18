"use client";

import { PieChart, Pie, Cell, Legend, Tooltip, ResponsiveContainer } from "recharts";

const data = [
  { name: "Gold (≥0.85)", value: 4234, color: "#f59e0b" },
  { name: "Silver (0.70–0.85)", value: 8102, color: "#94a3b8" },
  { name: "Bronze (0.50–0.70)", value: 3455, color: "#a16207" },
  { name: "Unverified (<0.50)", value: 1209, color: "#ef4444" },
];

export function TrustDistributionChart() {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <PieChart>
        <Pie
          data={data}
          cx="50%"
          cy="50%"
          innerRadius={55}
          outerRadius={90}
          paddingAngle={3}
          dataKey="value"
        >
          {data.map((entry) => (
            <Cell key={entry.name} fill={entry.color} />
          ))}
        </Pie>
        <Tooltip
          contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8 }}
          labelStyle={{ color: "#e2e8f0" }}
          itemStyle={{ color: "#94a3b8" }}
        />
        <Legend
          iconType="circle"
          iconSize={8}
          formatter={(value) => <span className="text-xs text-slate-400">{value}</span>}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}
