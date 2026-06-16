"use client";

import {
  artifactUrl,
  type Run,
  type StepLog,
  type WorkflowStep,
} from "@/lib/api";
import { SaveMiniApp } from "./SaveMiniApp";

type Props = {
  workflow: WorkflowStep[] | null;
  summary: string | null;
  run: Run | null;
  busy: boolean;
  selectedStepIdx: number | null;
  onRun: () => void | Promise<void>;
  onSelectStep: (idx: number | null) => void;
  candidateCount?: number;
  showSave?: boolean;
  saving?: boolean;
  savedId?: string | null;
  saveError?: string | null;
  onSave?: (name: string, description: string) => void | Promise<void>;
};

type StepState = "ok" | "failed" | "pending" | "proposed";

function stepStatus(
  idx: number,
  log: StepLog | undefined,
  hasRun: boolean,
  runStatus: Run["status"] | null
): StepState {
  if (!hasRun) return "proposed";
  if (!log) return runStatus === "running" ? "pending" : "proposed";
  return log.returncode === 0 ? "ok" : "failed";
}

const STATUS_STYLES: Record<StepState, string> = {
  ok: "border-emerald-400/60 bg-emerald-50 dark:bg-emerald-950/30",
  failed: "border-red-400/60 bg-red-50 dark:bg-red-950/30",
  pending: "border-zinc-300 bg-zinc-50 dark:border-white/10 dark:bg-zinc-900",
  proposed: "border-blue-300 bg-blue-50 dark:border-blue-900/60 dark:bg-blue-950/20",
};

function paramSummary(params: Record<string, unknown>): string {
  return Object.entries(params)
    .map(([k, v]) => {
      if (typeof v === "string") {
        const tail = v.split("/").pop() || v;
        return `${k}=${tail}`;
      }
      return `${k}=${JSON.stringify(v)}`;
    })
    .join(", ");
}

function StepCard({
  step,
  idx,
  status,
  log,
  selected,
  onClick,
}: {
  step: WorkflowStep;
  idx: number;
  status: StepState;
  log?: StepLog;
  selected: boolean;
  onClick: () => void;
}) {
  const klass = STATUS_STYLES[status];
  const ps = paramSummary(step.params);
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-lg border-2 px-4 py-3 text-left shadow-sm transition-all min-w-[200px] ${klass} ${
        selected
          ? "ring-2 ring-zinc-900 dark:ring-white border-zinc-900 dark:border-white"
          : "hover:border-black/40 dark:hover:border-white/40"
      }`}
    >
      <div className="text-xs uppercase tracking-wide text-zinc-500">
        Step {idx + 1} · {status}
      </div>
      <div className="font-medium text-sm">{step.block_id}</div>
      {log && (
        <div className="text-xs text-zinc-500 mt-1">
          {log.duration_ms}ms · rc={log.returncode}
        </div>
      )}
      {ps && (
        <div className="text-[11px] text-zinc-500 mt-1 truncate max-w-[280px]">{ps}</div>
      )}
    </button>
  );
}

export function BlockDiagram({
  workflow,
  summary,
  run,
  busy,
  selectedStepIdx,
  onRun,
  onSelectStep,
  candidateCount = 0,
  showSave = false,
  saving = false,
  savedId = null,
  saveError = null,
  onSave,
}: Props) {
  const hasRun = run !== null;

  return (
    <div className="flex flex-col h-full">
      <header className="px-4 py-3 border-b border-black/10 dark:border-white/10 flex items-baseline justify-between">
        <div>
          <h2 className="text-sm font-semibold">Workflow</h2>
          <p className="text-xs text-zinc-500">
            {hasRun
              ? `Run ${run!.id.slice(0, 8)} · status: ${run!.status}`
              : workflow
              ? "Click a block to edit its parameters. Run when ready."
              : "Chat with the orchestrator to compose a workflow."}
          </p>
        </div>
        {workflow && (
          <button
            type="button"
            className="rounded-md bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-700 disabled:opacity-50"
            onClick={() => void onRun()}
            disabled={busy}
          >
            {busy ? "Running…" : hasRun ? "Re-run" : "Run this workflow"}
          </button>
        )}
      </header>

      <div className="flex-1 overflow-auto p-8">
        {!workflow ? (
          <p className="text-sm text-zinc-500 italic">
            No workflow yet. Send a message to the orchestrator.
          </p>
        ) : (
          <div className="space-y-6">
            {summary && (
              <p className="text-sm text-zinc-700 dark:text-zinc-300">{summary}</p>
            )}

            <div className="flex items-center gap-4 flex-wrap">
              {workflow.map((step, idx) => (
                <div key={idx} className="flex items-center gap-4">
                  <StepCard
                    step={step}
                    idx={idx}
                    status={stepStatus(idx, run?.logs[idx], hasRun, run?.status ?? null)}
                    log={hasRun ? run!.logs[idx] : undefined}
                    selected={selectedStepIdx === idx}
                    onClick={() =>
                      onSelectStep(selectedStepIdx === idx ? null : idx)
                    }
                  />
                  {idx < workflow.length - 1 && (
                    <span className="text-zinc-400 select-none">→</span>
                  )}
                </div>
              ))}
            </div>

            {hasRun && run!.status === "succeeded" && run!.artifacts.final && (
              <div className="rounded-md border border-emerald-400/60 bg-emerald-50 dark:bg-emerald-950/30 px-4 py-3 text-sm flex items-center justify-between">
                <div>
                  <div className="font-medium">Output ready</div>
                  <div className="text-xs text-zinc-600 dark:text-zinc-400">
                    {run!.artifacts.final.filename}
                  </div>
                </div>
                <a
                  href={artifactUrl(run!.id)}
                  className="rounded-md bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-700"
                  download={run!.artifacts.final.filename}
                >
                  Download
                </a>
              </div>
            )}

            {showSave && hasRun && run!.status === "succeeded" && onSave && (
              <SaveMiniApp
                defaultName={summary ?? ""}
                candidateCount={candidateCount}
                saving={saving}
                savedId={savedId}
                error={saveError}
                onSave={onSave}
              />
            )}

            {hasRun && run!.status === "failed" && (
              <div className="rounded-md border border-red-400/60 bg-red-50 dark:bg-red-950/30 px-4 py-3 text-sm">
                <div className="font-medium text-red-900 dark:text-red-200">Run failed</div>
                <div className="text-xs text-zinc-700 dark:text-zinc-300 mt-1 whitespace-pre-wrap break-all">
                  {run!.artifacts.error ?? "see logs"}
                </div>
              </div>
            )}

            {hasRun && run!.logs.length > 0 && (
              <details className="text-xs">
                <summary className="cursor-pointer text-zinc-500">Step logs</summary>
                <pre className="mt-2 p-3 bg-zinc-100 dark:bg-zinc-900 rounded-md overflow-auto">
                  {run!.logs
                    .map(
                      (l) =>
                        `[step ${l.step}] ${l.block} (rc=${l.returncode}, ${l.duration_ms}ms)\n${l.stdout}${l.stderr ? "\n--stderr--\n" + l.stderr : ""}`
                    )
                    .join("\n\n")}
                </pre>
              </details>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
