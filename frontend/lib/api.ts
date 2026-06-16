export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export type WorkflowStep = {
  block_id: string;
  params: Record<string, unknown>;
  input_bindings: Record<string, string>;
};

export type StepLog = {
  step: number;
  block: string;
  returncode: number;
  duration_ms: number;
  stdout: string;
  stderr: string;
};

export type RunArtifacts = {
  run_dir?: string;
  steps?: Record<string, string>[];
  final?: { step: number; output_name: string; path: string; filename: string };
  error?: string;
};

export type Run = {
  id: string;
  workflow_id: string | null;
  status: "pending" | "running" | "succeeded" | "failed";
  inputs: { workflow: WorkflowStep[]; name: string | null };
  artifacts: RunArtifacts;
  logs: StepLog[];
  started_at: string | null;
  finished_at: string | null;
};

export type UploadResult = {
  id: string;
  filename: string;
  path: string;
  size: number;
  content_type: string | null;
};

export type BlockSpec = {
  id: string;
  name: string;
  description: string;
  version: string;
  status: string;
  inputs: Record<string, unknown>;
  params: Record<string, unknown>;
  outputs: Record<string, unknown>;
};

export type ChatMessage = { role: "user" | "assistant"; content: string };

export type CandidateBlock = {
  code: string;
  name?: string;
  description?: string;
  version?: string;
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  params_schema?: Record<string, unknown>;
};

export type ChatResponse = {
  assistant_message: string;
  workflow: WorkflowStep[] | null;
  summary: string | null;
  candidate_blocks: Record<string, CandidateBlock>;
  tool_trace: Array<{ tool: string; input: unknown; output?: unknown; error?: string }>;
  usage: {
    input_tokens: number;
    output_tokens: number;
    cache_creation_input_tokens: number;
    cache_read_input_tokens: number;
  };
  stop_reason: string;
  validation_errors: string[];
};

export type SavedWorkflowSummary = {
  id: string;
  name: string;
  description: string;
  step_count: number;
  created_at: string | null;
};

export type SavedWorkflow = {
  id: string;
  name: string;
  description: string;
  steps: WorkflowStep[];
  created_at: string | null;
};

export async function healthz(): Promise<{ ok: boolean }> {
  const res = await fetch(`${API_BASE}/healthz`);
  if (!res.ok) throw new Error(`healthz: ${res.status}`);
  return res.json();
}

export async function listBlocks(): Promise<BlockSpec[]> {
  const res = await fetch(`${API_BASE}/api/blocks`);
  if (!res.ok) throw new Error(`listBlocks: ${res.status}`);
  return res.json();
}

export async function uploadFile(file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/uploads`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(`upload failed: ${res.status} ${await res.text()}`);
  return res.json();
}

export async function createRun(args: {
  workflow: WorkflowStep[];
  name?: string;
  candidate_blocks?: Record<string, CandidateBlock>;
  workflow_id?: string;
}): Promise<Run> {
  const res = await fetch(`${API_BASE}/api/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      workflow: args.workflow,
      name: args.name ?? null,
      candidate_blocks: args.candidate_blocks ?? {},
      workflow_id: args.workflow_id ?? null,
    }),
  });
  if (!res.ok) throw new Error(`createRun: ${res.status} ${await res.text()}`);
  return res.json();
}

export async function saveWorkflow(args: {
  name: string;
  description?: string;
  steps: WorkflowStep[];
  candidate_blocks?: Record<string, CandidateBlock>;
}): Promise<{ id: string; promoted_blocks: string[]; name: string }> {
  const res = await fetch(`${API_BASE}/api/workflows`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: args.name,
      description: args.description ?? "",
      steps: args.steps,
      candidate_blocks: args.candidate_blocks ?? {},
    }),
  });
  if (!res.ok) throw new Error(`saveWorkflow: ${res.status} ${await res.text()}`);
  return res.json();
}

export async function listWorkflows(): Promise<SavedWorkflowSummary[]> {
  const res = await fetch(`${API_BASE}/api/workflows`);
  if (!res.ok) throw new Error(`listWorkflows: ${res.status}`);
  return res.json();
}

export async function getWorkflow(id: string): Promise<SavedWorkflow> {
  const res = await fetch(`${API_BASE}/api/workflows/${id}`);
  if (!res.ok) throw new Error(`getWorkflow: ${res.status} ${await res.text()}`);
  return res.json();
}

export async function chat(args: {
  message: string;
  history: ChatMessage[];
  attachments: { id?: string; filename: string; path: string }[];
}): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(args),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`chat: ${res.status} ${detail}`);
  }
  return res.json();
}

export function artifactUrl(runId: string): string {
  return `${API_BASE}/api/runs/${runId}/artifact`;
}
