"use client";

import { useRef, useState } from "react";
import type { ChatMessage, UploadResult } from "@/lib/api";

type Props = {
  messages: ChatMessage[];
  attachments: UploadResult[];
  busy: boolean;
  error: string | null;
  onSend: (text: string) => void | Promise<void>;
  onAttach: (file: File) => void | Promise<void>;
  onRemoveAttachment: (id: string) => void;
};

export function ChatPanel({
  messages,
  attachments,
  busy,
  error,
  onSend,
  onAttach,
  onRemoveAttachment,
}: Props) {
  const [draft, setDraft] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    await onSend(text);
  }

  return (
    <div className="flex flex-col h-full">
      <header className="px-4 py-3 border-b border-black/10 dark:border-white/10">
        <h1 className="text-sm font-semibold">Block Chat</h1>
        <p className="text-xs text-zinc-500">
          Describe a data workflow. The AI composes it from reusable blocks.
        </p>
      </header>

      <div className="flex-1 overflow-y-auto p-4 space-y-3 text-sm">
        {messages.length === 0 ? (
          <p className="text-zinc-500 italic">
            No messages yet. Attach a CSV and ask for a transform.
          </p>
        ) : (
          messages.map((m, i) => (
            <div
              key={i}
              className={
                m.role === "user"
                  ? "rounded-md bg-zinc-100 dark:bg-zinc-900 px-3 py-2"
                  : "rounded-md bg-blue-50 dark:bg-blue-950/30 px-3 py-2 border border-blue-200/60 dark:border-blue-900/40"
              }
            >
              <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1">
                {m.role}
              </div>
              <div className="whitespace-pre-wrap">{m.content}</div>
            </div>
          ))
        )}
        {busy && (
          <div className="rounded-md px-3 py-2 text-zinc-500 italic">
            …thinking
          </div>
        )}
      </div>

      <form
        className="border-t border-black/10 dark:border-white/10 p-3 space-y-2"
        onSubmit={handleSubmit}
      >
        {attachments.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {attachments.map((a) => (
              <span
                key={a.id}
                className="inline-flex items-center gap-1 rounded-full bg-zinc-100 dark:bg-zinc-800 px-2 py-0.5 text-xs"
              >
                {a.filename}
                <button
                  type="button"
                  className="text-zinc-500 hover:text-red-600"
                  onClick={() => onRemoveAttachment(a.id)}
                  aria-label={`remove ${a.filename}`}
                  disabled={busy}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}

        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              void handleSubmit(e as unknown as React.FormEvent);
            }
          }}
          placeholder="e.g. Load the CSV, then export to xlsx with sheet name Summary"
          rows={3}
          className="w-full resize-none rounded-md border border-black/10 dark:border-white/15 bg-transparent px-3 py-2 text-sm outline-none focus:border-black/40 dark:focus:border-white/40"
          disabled={busy}
        />

        <div className="flex items-center gap-2">
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.xlsx,text/csv"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void onAttach(file);
              if (fileRef.current) fileRef.current.value = "";
            }}
          />
          <button
            type="button"
            className="text-xs rounded-md border border-black/10 dark:border-white/15 px-2 py-1.5 hover:bg-black/5 dark:hover:bg-white/5 disabled:opacity-50"
            onClick={() => fileRef.current?.click()}
            disabled={busy}
          >
            Attach file
          </button>
          <button
            type="submit"
            className="ml-auto rounded-md bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-700 disabled:opacity-50"
            disabled={!draft.trim() || busy}
          >
            Send {messages.length === 0 ? "" : "(⌘↵)"}
          </button>
        </div>

        {error && (
          <p className="text-xs text-red-600 dark:text-red-400 break-all">
            {error}
          </p>
        )}
      </form>
    </div>
  );
}
