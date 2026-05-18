"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { MessageSquare, Send, Loader2 } from "lucide-react";

const SUGGESTIONS = [
  "Find duplicate suppliers",
  "Which datasets have low trust scores?",
  "Show customer hierarchy for Acme Corp",
  "Which systems violate governance policies?",
];

export function CopilotBar() {
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const ask = async (q: string) => {
    if (!q.trim()) return;
    setLoading(true);
    setAnswer(null);
    try {
      const res = await api.post("/api/v1/copilot/query", { query: q });
      setAnswer(res.data.answer);
    } catch {
      setAnswer("Could not reach the copilot service. Check your API configuration.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-gradient-to-br from-brand-900/40 to-surface-900 rounded-xl border border-brand-500/20 p-5">
      <div className="flex items-center gap-2 mb-4">
        <MessageSquare className="w-4 h-4 text-brand-400" />
        <span className="text-sm font-semibold text-brand-300">CognitiveMDM Copilot</span>
        <span className="text-xs bg-brand-500/20 text-brand-400 px-2 py-0.5 rounded-full">AI</span>
      </div>

      <div className="flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask(query)}
          placeholder="Ask anything about your enterprise data..."
          className="flex-1 bg-surface-950/80 border border-slate-700 rounded-lg px-4 py-2.5 text-sm text-white placeholder-slate-500 outline-none focus:border-brand-500 transition-colors"
        />
        <button
          onClick={() => ask(query)}
          disabled={loading}
          className="px-4 py-2.5 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 rounded-lg transition-colors"
        >
          {loading ? (
            <Loader2 className="w-4 h-4 text-white animate-spin" />
          ) : (
            <Send className="w-4 h-4 text-white" />
          )}
        </button>
      </div>

      {/* Suggestions */}
      {!answer && (
        <div className="flex flex-wrap gap-2 mt-3">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => { setQuery(s); ask(s); }}
              className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-1.5 rounded-full border border-slate-700 transition-colors"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Answer */}
      {answer && (
        <div className="mt-4 p-4 bg-surface-950/80 rounded-lg border border-slate-700">
          <p className="text-sm text-slate-200 leading-relaxed whitespace-pre-wrap">{answer}</p>
        </div>
      )}
    </div>
  );
}
