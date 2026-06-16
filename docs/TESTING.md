# Testing guide

How to bring up and exercise the app end-to-end.

## Prereqs

- Python 3.11+ (project tested on 3.14.6)
- Node 20+ (project tested on 20.19.5, via nvm)
- An `ANTHROPIC_API_KEY` for the chat orchestrator (everything else works without it)

## Start both servers

**Terminal 1 — backend:**
```bash
cd backend
export ANTHROPIC_API_KEY=sk-ant-...        # optional, only needed for /api/chat
rm -f data.db                              # fresh DB; safe between runs
.venv/bin/uvicorn app.main:app --port 8000 --reload
```

On startup you'll see `[startup] seeded N blocks from disk` confirming the registry loaded.

**Terminal 2 — frontend:**
```bash
cd frontend
npm run dev                                # http://localhost:3000
```

## Demo path A — full browser flow (needs API key)

Open `http://localhost:3000` and run through:

1. **Attach `backend/samples/sales.csv`** with the "Attach file" button (chip appears).
2. **Send**: *"Load the CSV and export it to xlsx with sheet name `Raw`"*. The orchestrator proposes a 2-step chain. Diagram colors the blocks blue (proposed).
3. **Click a block** → right-side inspector opens. Change `sheet_name` from `Raw` to `Sales` → **Save**. Blocks stay blue (run not yet executed); the Run button becomes available.
4. **Click "Run this workflow"**. Blocks turn green (ok). A download link appears.
5. **Download** the xlsx and confirm the sheet name.
6. **Save as mini-app** card appears below the download. Enter a name → **Save mini-app**.
7. **Click "Saved mini-apps"** in the header → see your saved app.
8. **Open it** → on `/apps/<id>`, the diagram loads with the saved steps. Click the `load_csv` block → in the inspector, use "upload a new file to override `path`" with a different CSV → **Run** → new output.

**For the ad-hoc-block story (test `generate_block`):**

After step 2, instead try: *"Load the CSV, add a column `size_bucket` that classifies `quantity` as small/medium/large, then export to xlsx"*. The orchestrator should call `generate_block` (yellow note: "1 candidate block will be promoted"). Run it → Save → check `curl localhost:8000/api/blocks` and confirm `size_bucket` now shows `"status": "promoted"`.

## Demo path B — backend only (no API key needed)

You can exercise everything except the chat orchestrator from the command line. There's already a working script:

```bash
cd backend
.venv/bin/uvicorn app.main:app --port 8000 --log-level warning &   # background
.venv/bin/python /tmp/curl_test_save.py
```

This runs: upload `sales.csv` → run a 3-step chain (`load_csv → size_bucket [candidate] → export_xlsx`) → save as mini-app → verify the candidate was promoted to disk + DB → re-run the saved workflow without the candidate payload. Prints `ALL OK` on success.

> **Note:** `/tmp/curl_test_save.py` lives outside the repo (it was created during the dev session). If it's gone on the new machine, recreate it from this template or use direct `curl` calls against the endpoints in `backend/app/api/`.

## Test suite

```bash
cd backend
.venv/bin/pytest tests/ -v
```

9 tests: 4 runner (incl. candidate-block materialization), 5 orchestrator (incl. search→propose, generate_block, validation rejection-then-retry).

Frontend type check:

```bash
cd frontend && npx tsc --noEmit                  # silent = clean
```

## What to look for in logs

- Backend startup: `[startup] seeded N blocks from disk` (N = 2 in a clean repo).
- Per-run logs in the chat UI: open the "Step logs" `<details>` under the diagram — shows stdout/stderr/duration/returncode for each subprocess.
- Promote-on-save: after `POST /api/workflows` with a candidate, you'll see `app/blocks/<new_slug>/` appear on disk.

## Setup on a fresh machine (if `backend/.venv` or `frontend/node_modules` are missing)

```bash
# backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# frontend
cd ../frontend
npm install
```
