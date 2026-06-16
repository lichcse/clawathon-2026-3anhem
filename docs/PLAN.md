# Block-Composing Chat App — Hackathon Demo Plan

## Context

People run the same data-prep workflow on a recurring cadence (weekly KPI, monthly compliance export, etc.). Today they re-prompt an LLM each time, even though only the **inputs** change (URL, file, template). The end-to-end shape — fetch → transform → format — is identical.

We're building a chat app where the AI does not just answer; it **composes a workflow from atomic, reusable blocks** (Apple Shortcuts style), shows the chain to the user, runs it, and lets the user save the composition as a **mini-app** that can be re-run later with different inputs. Editable per-block via prompt or inspector UI. Globally shared block registry so the library grows with every user.

**This plan delivers a 1-week hackathon demo of one headline workflow:** CSV/Excel → styled Excel report, with a swap-block story to demonstrate reusability.

## Decisions already made

| Decision | Choice |
|---|---|
| Scope | Hackathon demo (~1 week) |
| Block authoring | Try shared library first → if no fit, LLM drafts ad-hoc block → promote to library on user "save mini-app" |
| Block runtime | Local Python subprocess (demo only, curated trust) |
| Stack | FastAPI backend + Next.js (App Router) frontend |
| Editing UX | Static block diagram + click-to-edit parameters (no drag-and-drop) |
| Orchestrator LLM | Anthropic Claude (Sonnet 4.6) via official SDK with tool use + prompt caching |
| Headline scenario | Upload CSV/Excel + `template.xlsx` → group/aggregate → fill template → download `.xlsx` |
| Persistence | SQLite (single-host) |
| Auth / multi-tenant | Out of scope — single-host demo; "shared registry" = global on this instance |

## Architecture

```
 ┌────────────────────────────────────────────────────────────────┐
 │  Next.js frontend                                              │
 │  ┌────────────┐  ┌───────────────────┐  ┌──────────────────┐   │
 │  │ ChatPanel  │  │  BlockDiagram     │  │ BlockInspector   │   │
 │  │ (SSE)      │  │  (SVG, clickable) │  │ (params editor)  │   │
 │  └────┬───────┘  └─────────┬─────────┘  └────────┬─────────┘   │
 └───────┼────────────────────┼─────────────────────┼─────────────┘
         │ POST /api/chat     │ GET /api/workflows  │ PATCH params
         ▼                    ▼                     ▼
 ┌────────────────────────────────────────────────────────────────┐
 │  FastAPI backend                                               │
 │                                                                │
 │  /api/chat ──▶ Orchestrator (Claude + tools)                   │
 │                  • search_blocks(query)                        │
 │                  • propose_workflow(steps[])                   │
 │                  • generate_block(name, code, schema)          │
 │                                                                │
 │  /api/workflows  CRUD saved mini-apps                          │
 │  /api/blocks     registry + search                             │
 │  /api/runs       execute a workflow → status / logs / artifact │
 │                                                                │
 │              ┌──────────────────────────────┐                  │
 │              │   Runner (subprocess)        │                  │
 │              │   workspace = /tmp/runs/{id} │                  │
 │              │   step → parquet/xlsx → next │                  │
 │              └──────────────────────────────┘                  │
 └────────────────────────────────────────────────────────────────┘
         │
         ▼
 ┌────────────────────────────────────────────────────────────────┐
 │  SQLite                  +    Block registry on disk           │
 │  blocks  (metadata)            backend/app/blocks/<id>/        │
 │  workflows (composition)         block.yaml                    │
 │  runs (history)                  main.py                       │
 │  candidates (pre-promotion)                                    │
 └────────────────────────────────────────────────────────────────┘
```

## Data model (SQLite via SQLModel)

```
blocks
  id (pk, slug) · name · description · version · author
  input_schema (JSON)  · output_schema (JSON)
  code_path (str)      · status: 'curated' | 'promoted' | 'candidate'
  created_at

workflows  (mini-apps)
  id (pk, uuid) · name · description · created_at
  steps (JSON list of { block_id, params, input_bindings })
  source_chat_id (nullable)

runs
  id (pk, uuid) · workflow_id (fk) · status · started_at · finished_at
  inputs (JSON: file refs, params overrides)
  artifacts (JSON: per-step output paths)
  logs (text)

candidate_blocks
  id (pk) · session_id · proposed_for_workflow_id (nullable)
  same fields as `blocks`, but isolated to one run until promoted
```

## Block contract

A block is a directory: `backend/app/blocks/<slug>/`

```
block.yaml          # name, description, version, input_schema, output_schema
main.py             # __main__: reads params.json + inputs.json, writes outputs
```

`main.py` invocation:
```
python main.py --workdir /tmp/runs/<run_id>/step<N> \
               --params params.json \
               --inputs inputs.json \
               --outputs outputs.json
```

Inter-block artifacts:
- DataFrames → parquet on disk (`step1.parquet`) — passed by path
- Files (xlsx, pdf) → raw on disk
- Schema declares logical types (`dataframe`, `xlsx_file`, `string`) and the runner enforces compatibility on chain assembly.

## Block library v1 (ship for the demo)

| Slug | Inputs | Outputs | Purpose |
|---|---|---|---|
| `load_csv` | `{path}` | `{data: dataframe}` | Read CSV file |
| `load_xlsx` | `{path, sheet}` | `{data: dataframe}` | Read Excel sheet |
| `load_url_csv` | `{url}` | `{data: dataframe}` | Fetch CSV from URL (swap-source demo) |
| `filter_rows` | `{data, expr}` | `{data}` | pandas `df.query(expr)` |
| `group_aggregate` | `{data, group_by[], agg{}}` | `{data}` | groupby + agg |
| `apply_xlsx_template` | `{data, template_path, sheet, cell_anchor}` | `{file: xlsx}` | Write df into a templated xlsx via openpyxl |
| `export_xlsx` | `{data, filename}` | `{file: xlsx}` | Plain export, no template |

7 blocks is enough to compose 3–4 distinct demo flows and showcase block swapping.

## Orchestrator flow

1. `POST /api/chat` receives `{message, attachments[], desired_format}`.
2. Claude (Sonnet 4.6) is called with the chat history and three tools:
   - `search_blocks(query)` — semantic + lexical search over `blocks` table; returns top N with schemas.
   - `propose_workflow(steps)` — final structured output: ordered list of `{block_id, params, input_bindings}`.
   - `generate_block(name, description, code, input_schema, output_schema)` — if no curated block fits a step; result is saved as a `candidate_block` and referenced by the step.
3. Orchestrator validates the proposed chain: schemas line up between steps; required params are present.
4. Streams the proposal to the chat panel; the BlockDiagram renders it.
5. User confirms → `POST /api/runs` executes; logs stream back via SSE.
6. User clicks "Save as mini-app" → `POST /api/workflows`; any `candidate_blocks` referenced become `promoted` rows in `blocks` and are now visible to all users.

Prompt caching: cache the system prompt + block catalog summary (~50 lines) between turns; this keeps the cache hot during the chat and is dirt cheap.

## Repo layout

```
backend/
  app/
    main.py                  FastAPI entry
    api/chat.py              SSE chat endpoint
    api/workflows.py         CRUD
    api/blocks.py            registry + /search
    api/runs.py              execute + status + artifact download
    orchestrator/claude.py   Anthropic SDK wrapper + tool definitions
    orchestrator/loop.py     tool-use loop
    runner/executor.py       subprocess runner + workspace mgmt
    blocks/<slug>/           on-disk block dirs
    db/models.py             SQLModel tables
    db/session.py
  pyproject.toml             uv-managed
  tests/

frontend/
  app/
    page.tsx                 chat + diagram split view
    apps/[id]/page.tsx       saved mini-app, re-run with new inputs
  components/
    ChatPanel.tsx
    BlockDiagram.tsx         SVG, clickable nodes
    BlockInspector.tsx       per-block param editor
    AttachmentDrop.tsx
  lib/api.ts                 fetch helpers
  package.json
```

## Implementation order (1-week timebox)

| Day | Goal | Concretely |
|---|---|---|
| 1 | Scaffolds + block runtime | FastAPI hello, Next.js shell, SQLite migrations; write `load_csv` + `export_xlsx` blocks; manual subprocess invocation works |
| 2 | Runner + e2e via API | `/api/runs` accepts a hardcoded workflow JSON, executes the two blocks, returns an xlsx — no LLM yet |
| 3 | Orchestrator | Claude tool-use loop; `search_blocks` + `propose_workflow`; `/api/chat` returns a workflow; ChatPanel renders messages |
| 4 | Diagram + inspector | SVG renderer for the step chain; click a node → open BlockInspector → patch params → re-render |
| 5 | Save + re-run + ad-hoc blocks | Save mini-app; `/apps/[id]` re-run page; `generate_block` tool; promote-on-save |
| 6 | Remaining blocks + polish | `filter_rows`, `group_aggregate`, `apply_xlsx_template`, `load_url_csv`; demo dataset; rehearse |
| 7 | Buffer | Bug fixes, demo recording |

## Verification (end-to-end)

Run:
```
cd backend && uv sync && uv run uvicorn app.main:app --reload --port 8000
cd frontend && npm install && npm run dev
```

Open `http://localhost:3000` and run the demo script:
1. Upload `samples/sales.csv` + `samples/template.xlsx`.
2. Chat: *"Group by region, sum sales and orders, fill the Summary sheet of the template."*
3. Confirm the proposed chain renders: `load_csv → group_aggregate → apply_xlsx_template`.
4. Click the `group_aggregate` block, change `group_by` to `["region", "product"]`, re-run.
5. Download `out.xlsx`, verify the Summary sheet is populated.
6. Click **Save as mini-app** → name it "Weekly Sales Report".
7. Open `/apps/<id>`, upload a different CSV with the same schema, hit **Run** → same chain, new output.
8. Swap story: open the saved app, chat *"Pull the CSV from `https://example.com/sales-latest.csv` instead"* — verify the orchestrator swaps `load_csv` for `load_url_csv` while keeping downstream blocks intact.
9. Ad-hoc story: ask for a transform no curated block handles (e.g., *"add a column that classifies orders as Small/Medium/Large by quantity"*). Verify `generate_block` is called, the candidate runs, and **Save** promotes it into the shared registry (visible at `/api/blocks`).

## Explicitly out of scope (for the week)

- Authentication, user accounts, multi-tenancy
- Real sandboxing of Python blocks (Docker / Pyodide / E2B)
- Block versioning / rollback / dependency graph beyond v1
- Drag-and-drop canvas
- Non-CSV/XLSX data sources (Metabase, OpenSearch, Prometheus) — schemas are reserved but blocks not built
- PDF/image input parsing
- Scheduled re-runs (cron) — re-run is manual on click
- Vector embedding store for block search — start with lexical + LLM-side reasoning over the catalog summary
