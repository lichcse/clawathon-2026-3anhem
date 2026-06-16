"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { BlockDiagram } from "@/components/BlockDiagram";
import { BlockInspector } from "@/components/BlockInspector";
import { useBlockCatalog } from "@/lib/useBlockCatalog";
import {
  createRun,
  getWorkflow,
  listWorkflows,
  uploadFile,
  type Run,
  type SavedWorkflow,
  type SavedWorkflowSummary,
  type UploadResult,
  type WorkflowStep,
} from "@/lib/api";

function AppDetailView({ id }: { id: string }) {
  const catalog = useBlockCatalog();
  const [savedWorkflow, setSavedWorkflow] = useState<SavedWorkflow | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [workflow, setWorkflow] = useState<WorkflowStep[] | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [selectedStepIdx, setSelectedStepIdx] = useState<number | null>(null);
  const [attachments, setAttachments] = useState<UploadResult[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getWorkflow(id)
      .then((w) => {
        if (!cancelled) {
          setSavedWorkflow(w);
          setWorkflow(w.steps);
          setLoading(false);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setLoadError(e instanceof Error ? e.message : String(e));
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [id]);

  async function handleAttachAndSetPath(file: File) {
    if (selectedStepIdx === null || !workflow) return;
    setBusy(true);
    setError(null);
    try {
      const result = await uploadFile(file);
      setAttachments((prev) => [...prev, result]);
      const step = workflow[selectedStepIdx];
      const newParams = { ...step.params, path: result.path };
      const next = workflow.map((s, i) =>
        i === selectedStepIdx ? { ...s, params: newParams } : s
      );
      setWorkflow(next);
      setRun(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function handleStepParamsChange(stepIdx: number, newParams: Record<string, unknown>) {
    if (!workflow) return;
    const next = workflow.map((s, i) => (i === stepIdx ? { ...s, params: newParams } : s));
    setWorkflow(next);
    setRun(null);
  }

  async function handleRun() {
    if (!workflow) return;
    setBusy(true);
    setError(null);
    try {
      const result = await createRun({ workflow, name: savedWorkflow?.name, workflow_id: id });
      setRun(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <main className="p-8 text-sm text-zinc-500">Loading…</main>;
  if (loadError || !savedWorkflow) {
    return (
      <main className="p-8 text-sm text-red-600 dark:text-red-400">
        {loadError ?? "Workflow not found."}
      </main>
    );
  }

  const selectedStep = selectedStepIdx !== null && workflow ? workflow[selectedStepIdx] : null;
  const selectedBlock = selectedStep ? catalog.byId[selectedStep.block_id] : undefined;

  return (
    <main className="flex flex-1 min-h-0">
      <section className="flex-1 min-w-0 flex flex-col">
        <div className="px-4 py-3 border-b border-black/10 dark:border-white/10">
          <div className="flex items-center gap-3 mb-1">
            <Link href="/apps" className="text-xs text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200">
              ← Back
            </Link>
            <h1 className="text-sm font-semibold">{savedWorkflow.name}</h1>
          </div>
          {savedWorkflow.description && (
            <p className="text-xs text-zinc-500">{savedWorkflow.description}</p>
          )}
          {attachments.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {attachments.map((a) => (
                <span key={a.id} className="inline-flex items-center rounded-full bg-zinc-100 dark:bg-zinc-800 px-2 py-0.5 text-[11px]">
                  uploaded: {a.filename}
                </span>
              ))}
            </div>
          )}
          {error && <p className="mt-2 text-xs text-red-600 dark:text-red-400 break-all">{error}</p>}
        </div>
        <BlockDiagram
          workflow={workflow}
          summary={savedWorkflow.description || null}
          run={run}
          busy={busy}
          selectedStepIdx={selectedStepIdx}
          onRun={handleRun}
          onSelectStep={setSelectedStepIdx}
        />
      </section>
      {selectedStep && (
        <section className="w-[380px] shrink-0 border-l border-black/10 dark:border-white/10 flex flex-col">
          <BlockInspector
            step={selectedStep}
            stepIndex={selectedStepIdx!}
            block={selectedBlock}
            editable={true}
            onSave={(params) => handleStepParamsChange(selectedStepIdx!, params)}
            onClose={() => setSelectedStepIdx(null)}
          />
          {"path" in selectedStep.params && (
            <div className="border-t border-black/10 dark:border-white/10 p-3 space-y-2">
              <p className="text-xs text-zinc-500">
                Quick action: upload a new file to override <span className="font-mono">path</span>
              </p>
              <input
                type="file"
                className="text-xs"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void handleAttachAndSetPath(f);
                  e.currentTarget.value = "";
                }}
                disabled={busy}
              />
            </div>
          )}
        </section>
      )}
    </main>
  );
}

function AppsListView() {
  const [items, setItems] = useState<SavedWorkflowSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listWorkflows()
      .then((data) => { if (!cancelled) { setItems(data); setLoading(false); } })
      .catch((e) => { if (!cancelled) { setError(e instanceof Error ? e.message : String(e)); setLoading(false); } });
    return () => { cancelled = true; };
  }, []);

  return (
    <main className="flex-1 overflow-y-auto p-8">
      <div className="max-w-3xl mx-auto space-y-6">
        <div>
          <h1 className="text-xl font-semibold">Saved mini-apps</h1>
          <p className="text-sm text-zinc-500 mt-1">Workflows you've saved. Open one to re-run with new inputs.</p>
        </div>
        {loading && <p className="text-sm text-zinc-500">Loading…</p>}
        {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
        {!loading && !error && items.length === 0 && (
          <p className="text-sm text-zinc-500 italic">
            No saved mini-apps yet.{" "}
            <Link href="/" className="underline">Go compose one</Link>.
          </p>
        )}
        <ul className="space-y-2">
          {items.map((a) => (
            <li key={a.id} className="rounded-md border border-black/10 dark:border-white/15 p-3 hover:border-black/40 dark:hover:border-white/40 transition-colors">
              <Link href={`/apps?id=${a.id}`} className="block">
                <div className="font-medium text-sm">{a.name}</div>
                {a.description && <div className="text-xs text-zinc-600 dark:text-zinc-400 mt-0.5">{a.description}</div>}
                <div className="text-[11px] text-zinc-500 mt-1">
                  {a.step_count} step{a.step_count !== 1 ? "s" : ""} · {a.created_at ? new Date(a.created_at).toLocaleString() : "—"} · <span className="font-mono">{a.id.slice(0, 8)}</span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </main>
  );
}

function AppsPageInner() {
  const params = useSearchParams();
  const id = params.get("id");
  return id ? <AppDetailView id={id} /> : <AppsListView />;
}

export default function AppsPage() {
  return (
    <Suspense fallback={<main className="p-8 text-sm text-zinc-500">Loading…</main>}>
      <AppsPageInner />
    </Suspense>
  );
}
