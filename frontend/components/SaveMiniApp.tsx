"use client";

import { useState } from "react";

type Props = {
  defaultName?: string;
  candidateCount: number;
  saving: boolean;
  savedId: string | null;
  error: string | null;
  onSave: (name: string, description: string) => void | Promise<void>;
};

export function SaveMiniApp({
  defaultName,
  candidateCount,
  saving,
  savedId,
  error,
  onSave,
}: Props) {
  const [name, setName] = useState(defaultName ?? "");
  const [description, setDescription] = useState("");

  return (
    <div className="rounded-md border border-black/10 dark:border-white/15 bg-white dark:bg-zinc-900 p-4 space-y-3">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold">Save this workflow as a mini-app</h3>
        {candidateCount > 0 && (
          <span className="text-[10px] text-amber-700 dark:text-amber-400">
            {candidateCount} candidate block{candidateCount > 1 ? "s" : ""} will be
            promoted to the shared registry
          </span>
        )}
      </div>

      {savedId ? (
        <p className="text-xs text-emerald-700 dark:text-emerald-400">
          Saved.{" "}
          <a
            href={`/apps?id=${savedId}`}
            className="underline font-medium"
          >
            Open mini-app
          </a>
        </p>
      ) : (
        <>
          <input
            type="text"
            placeholder="e.g. Weekly Sales Report"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-md border border-black/10 dark:border-white/15 bg-transparent px-3 py-1.5 text-sm outline-none focus:border-black/40 dark:focus:border-white/40"
            disabled={saving}
          />
          <input
            type="text"
            placeholder="Optional description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full rounded-md border border-black/10 dark:border-white/15 bg-transparent px-3 py-1.5 text-xs outline-none focus:border-black/40 dark:focus:border-white/40"
            disabled={saving}
          />
          {error && (
            <p className="text-xs text-red-600 dark:text-red-400 break-all">{error}</p>
          )}
          <button
            type="button"
            className="rounded-md bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-700 disabled:opacity-50"
            onClick={() => void onSave(name.trim(), description.trim())}
            disabled={!name.trim() || saving}
          >
            {saving ? "Saving…" : "Save mini-app"}
          </button>
        </>
      )}
    </div>
  );
}
