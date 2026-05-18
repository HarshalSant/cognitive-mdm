"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { MetricCard } from "@/components/ui/MetricCard";
import { TrustDistributionChart } from "@/components/governance/TrustDistributionChart";
import { RecentViolations } from "@/components/governance/RecentViolations";
import { EntityTypeBreakdown } from "@/components/entity/EntityTypeBreakdown";
import { CopilotBar } from "@/components/CopilotBar";
import { Activity, Database, GitMerge, Shield, AlertTriangle, TrendingUp } from "lucide-react";

export default function DashboardPage() {
  const { data: entities } = useQuery({
    queryKey: ["entities-summary"],
    queryFn: () => api.get("/api/v1/entities/?limit=1").then((r) => r.data),
  });

  const { data: violations } = useQuery({
    queryKey: ["violations"],
    queryFn: () => api.get("/api/v1/governance/violations?limit=5").then((r) => r.data),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Command Center</h1>
        <p className="text-slate-400 mt-1">AI-native master data intelligence platform overview</p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          title="Total Entities"
          value={entities?.total ?? "—"}
          icon={<Database className="w-5 h-5" />}
          trend="+12%"
          color="blue"
        />
        <MetricCard
          title="Duplicates Detected"
          value="1,247"
          icon={<GitMerge className="w-5 h-5" />}
          trend="-8%"
          color="yellow"
        />
        <MetricCard
          title="Governance Violations"
          value={violations?.violations?.length ?? "—"}
          icon={<Shield className="w-5 h-5" />}
          trend="-3%"
          color="red"
        />
        <MetricCard
          title="Avg Trust Score"
          value="0.82"
          icon={<TrendingUp className="w-5 h-5" />}
          trend="+0.04"
          color="green"
        />
      </div>

      {/* Copilot */}
      <CopilotBar />

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-surface-900 rounded-xl border border-slate-800 p-5">
          <h2 className="text-sm font-semibold text-slate-300 mb-4">Trust Score Distribution</h2>
          <TrustDistributionChart />
        </div>
        <div className="bg-surface-900 rounded-xl border border-slate-800 p-5">
          <h2 className="text-sm font-semibold text-slate-300 mb-4">Entity Type Breakdown</h2>
          <EntityTypeBreakdown />
        </div>
      </div>

      {/* Recent Violations */}
      <div className="bg-surface-900 rounded-xl border border-slate-800 p-5">
        <h2 className="text-sm font-semibold text-slate-300 mb-4">Recent Governance Violations</h2>
        <RecentViolations violations={violations?.violations ?? []} />
      </div>
    </div>
  );
}
