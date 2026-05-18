"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { clsx } from "clsx";
import {
  LayoutDashboard,
  Database,
  Network,
  Shield,
  Bot,
  MessageSquare,
  Upload,
  Settings,
  Brain,
} from "lucide-react";

const nav = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/entities", label: "Entities", icon: Database },
  { href: "/graph", label: "Knowledge Graph", icon: Network },
  { href: "/governance", label: "Governance", icon: Shield },
  { href: "/agents", label: "AI Agents", icon: Bot },
  { href: "/copilot", label: "Copilot", icon: MessageSquare },
  { href: "/ingestion", label: "Ingestion", icon: Upload },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-60 shrink-0 bg-surface-900 border-r border-slate-800 flex flex-col">
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-5 h-16 border-b border-slate-800">
        <Brain className="w-7 h-7 text-brand-500" />
        <span className="font-bold text-white text-lg tracking-tight">CognitiveMDM</span>
      </div>

      {/* Nav */}
      <nav className="flex-1 py-4 px-2 space-y-0.5 overflow-y-auto">
        {nav.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={clsx(
              "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
              pathname.startsWith(href)
                ? "bg-brand-600/20 text-brand-400"
                : "text-slate-400 hover:text-white hover:bg-slate-800"
            )}
          >
            <Icon className="w-4 h-4 shrink-0" />
            {label}
          </Link>
        ))}
      </nav>

      {/* Bottom */}
      <div className="px-2 py-3 border-t border-slate-800">
        <Link
          href="/settings"
          className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
        >
          <Settings className="w-4 h-4" />
          Settings
        </Link>
      </div>
    </aside>
  );
}
