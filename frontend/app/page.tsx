"use client";

import { useState } from "react";
import { ChatPanel } from "@/components/ChatPanel";
import { BlockDiagram } from "@/components/BlockDiagram";
import { BlockInspector } from "@/components/BlockInspector";
import { useBlockCatalog } from "@/lib/useBlockCatalog";
import {
  chat,
  createRun,
  saveWorkflow,
  uploadFile,
  type CandidateBlock,
  type ChatMessage,
  type Run,
  type UploadResult,
  type WorkflowStep,
} from "@/lib/api";

export default function Home() {
  const catalog = useBlockCatalog();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [attachments, setAttachments] = useState<UploadResult[]>([]);
  const [workflow, setWorkflow] = useState<WorkflowStep[] | null>(null);
  const [summary, setSummary] = useState<string | null>(null);
  const [candidateBlocks, setCandidateBlocks] = useState<Record<string, CandidateBlock>>({});
  const [run, setRun] = useState<Run | null>(null);
  const [selectedStepIdx, setSelectedStepIdx] = useState<number | null>(null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [saving, setSaving] = useState(false);
  const [savedId, setSavedId] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  async function handleAttachFile(file: File) {
    setError(null);
    try {
      const result = await uploadFile(file);
      setAttachments((prev) => [...prev, result]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function handleRemoveAttachment(id: string) {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  }

  async function handleSendMessage(text: string) {
    setBusy(true);
    setError(null);
    const userTurn: ChatMessage = { role: "user", content: text };
    const nextHistory = [...messages, userTurn];
    setMessages(nextHistory);
    try {
      const res = await chat({
        message: text,
        history: messages,
        attachments: attachments.map((a) => ({
          id: a.id,
          filename: a.filename,
          path: a.path,
        })),
      });
      const assistantTurn: ChatMessage = {
        role: "assistant",
        content: res.assistant_message || res.summary || "(no response)",
      };
      setMessages([...nextHistory, assistantTurn]);
      if (res.workflow) {
        setWorkflow(res.workflow);
        setSummary(res.summary);
        setCandidateBlocks(res.candidate_blocks ?? {});
        setRun(null);
        setSavedId(null);
        setSaveError(null);
        setSelectedStepIdx(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleRunWorkflow() {
    if (!workflow) return;
    setBusy(true);
    setError(null);
    try {
      const result = await createRun({
        workflow,
        name: summary ?? undefined,
        candidate_blocks: candidateBlocks,
      });
      setRun(result);
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
    setSavedId(null);
  }

  async function handleSave(name: string, description: string) {
    if (!workflow) return;
    setSaving(true);
    setSaveError(null);
    try {
      const usedCandidates = Object.fromEntries(
        Object.entries(candidateBlocks).filter(([id]) =>
          workflow.some((s) => s.block_id === id)
        )
      );
      const saved = await saveWorkflow({
        name,
        description,
        steps: workflow,
        candidate_blocks: usedCandidates,
      });
      setSavedId(saved.id);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  const selectedStep =
    selectedStepIdx !== null && workflow ? workflow[selectedStepIdx] : null;
  const selectedBlock = selectedStep ? catalog.byId[selectedStep.block_id] : undefined;
  const usedCandidateCount = workflow
    ? workflow.filter((s) => s.block_id in candidateBlocks).length
    : 0;

  return (
    <main className="flex flex-1 min-h-0">
      <section className="w-[440px] shrink-0 border-r border-black/10 dark:border-white/10 flex flex-col">
        <ChatPanel
          messages={messages}
          attachments={attachments}
          busy={busy}
          error={error}
          onSend={handleSendMessage}
          onAttach={handleAttachFile}
          onRemoveAttachment={handleRemoveAttachment}
        />
      </section>
      <section className="flex-1 min-w-0 flex flex-col">
        <BlockDiagram
          workflow={workflow}
          summary={summary}
          run={run}
          busy={busy}
          selectedStepIdx={selectedStepIdx}
          onRun={handleRunWorkflow}
          onSelectStep={setSelectedStepIdx}
          candidateCount={usedCandidateCount}
          showSave={true}
          saving={saving}
          savedId={savedId}
          saveError={saveError}
          onSave={handleSave}
        />
      </section>
      {selectedStep && (
        <section className="w-[380px] shrink-0 border-l border-black/10 dark:border-white/10 flex flex-col">
          <BlockInspector
            step={selectedStep}
            stepIndex={selectedStepIdx!}
            block={selectedBlock}
            editable={true}
            onSave={(params) => {
              handleStepParamsChange(selectedStepIdx!, params);
            }}
            onClose={() => setSelectedStepIdx(null)}
          />
        </section>
      )}
    </main>
  );
}
