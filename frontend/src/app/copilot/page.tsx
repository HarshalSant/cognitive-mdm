"use client";

import { useState, useRef, useEffect } from "react";
import { api } from "@/lib/api";
import { Send, Loader2, Bot, User } from "lucide-react";

interface Message {
  role: "user" | "assistant";
  content: string;
}

const SUGGESTIONS = [
  "Find duplicate suppliers",
  "Which datasets have low trust scores?",
  "Show customer hierarchy for Acme Corp",
  "Which entities have PII governance violations?",
  "What products are related to oncology?",
  "Which systems violate data governance policies?",
];

export default function CopilotPage() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "Hello! I'm the CognitiveMDM Copilot. I can help you explore your enterprise data, find duplicates, check governance status, and much more. What would you like to know?",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async (q: string) => {
    const query = q.trim();
    if (!query || loading) return;

    setMessages((m) => [...m, { role: "user", content: query }]);
    setInput("");
    setLoading(true);

    try {
      const res = await api.post("/api/v1/copilot/query", { query });
      setMessages((m) => [...m, { role: "assistant", content: res.data.answer }]);
    } catch {
      setMessages((m) => [
        ...m,
        { role: "assistant", content: "Sorry, I couldn't reach the copilot service. Check your configuration." },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full max-h-[calc(100vh-8rem)]">
      <div className="mb-4">
        <h1 className="text-2xl font-bold text-white">CognitiveMDM Copilot</h1>
        <p className="text-slate-400 mt-1">Natural language interface to your enterprise data</p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-4 pr-1">
        {messages.map((msg, i) => (
          <div key={i} className={`flex gap-3 ${msg.role === "user" ? "flex-row-reverse" : ""}`}>
            <div
              className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${
                msg.role === "assistant" ? "bg-brand-600" : "bg-slate-700"
              }`}
            >
              {msg.role === "assistant" ? (
                <Bot className="w-4 h-4 text-white" />
              ) : (
                <User className="w-4 h-4 text-white" />
              )}
            </div>
            <div
              className={`max-w-2xl rounded-xl px-4 py-3 text-sm leading-relaxed ${
                msg.role === "assistant"
                  ? "bg-surface-900 border border-slate-800 text-slate-200"
                  : "bg-brand-600/20 border border-brand-500/30 text-white"
              }`}
            >
              <p className="whitespace-pre-wrap">{msg.content}</p>
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex gap-3">
            <div className="w-8 h-8 rounded-full bg-brand-600 flex items-center justify-center">
              <Bot className="w-4 h-4 text-white" />
            </div>
            <div className="bg-surface-900 border border-slate-800 rounded-xl px-4 py-3">
              <Loader2 className="w-4 h-4 text-brand-400 animate-spin" />
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Suggestions */}
      <div className="flex flex-wrap gap-2 my-3">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => send(s)}
            disabled={loading}
            className="text-xs bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-slate-300 px-3 py-1.5 rounded-full border border-slate-700 transition-colors"
          >
            {s}
          </button>
        ))}
      </div>

      {/* Input */}
      <div className="flex gap-2 border-t border-slate-800 pt-3">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send(input)}
          placeholder="Ask anything about your enterprise data..."
          className="flex-1 bg-surface-900 border border-slate-700 rounded-lg px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-brand-500 transition-colors"
        />
        <button
          onClick={() => send(input)}
          disabled={loading || !input.trim()}
          className="px-4 py-3 bg-brand-600 hover:bg-brand-500 disabled:opacity-40 rounded-lg transition-colors"
        >
          <Send className="w-4 h-4 text-white" />
        </button>
      </div>
    </div>
  );
}
