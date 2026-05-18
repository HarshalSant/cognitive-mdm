"use client";

import { Bell, Search, User } from "lucide-react";

export function TopBar() {
  return (
    <header className="h-16 border-b border-slate-800 bg-surface-900 flex items-center justify-between px-6 shrink-0">
      <div className="flex items-center gap-3 flex-1 max-w-md">
        <Search className="w-4 h-4 text-slate-500" />
        <input
          type="text"
          placeholder="Search entities, relationships, policies..."
          className="bg-transparent text-sm text-slate-300 placeholder-slate-500 flex-1 outline-none"
        />
      </div>
      <div className="flex items-center gap-3">
        <button className="relative p-2 rounded-lg hover:bg-slate-800 transition-colors">
          <Bell className="w-4 h-4 text-slate-400" />
          <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-red-500" />
        </button>
        <div className="flex items-center gap-2 pl-3 border-l border-slate-800">
          <div className="w-8 h-8 rounded-full bg-brand-600 flex items-center justify-center">
            <User className="w-4 h-4 text-white" />
          </div>
          <span className="text-sm text-slate-300 font-medium">Admin</span>
        </div>
      </div>
    </header>
  );
}
