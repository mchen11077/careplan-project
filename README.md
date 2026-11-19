# Careplan

A portfolio prototype for drafting pharmacist care plans. Django stores orders and a durable job queue in SQLite. React and TypeScript provide one intake form, order status, draft preview, retry, download, and CSV export.

## Run locally

Requires Python 3.12 or newer, Node.js 22.12 or newer, and pnpm.

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe manage.py migrate
cd frontend
pnpm install
pnpm build
cd ..
.venv/Scripts/python.exe manage.py runserver 127.0.0.1:8000
```

In a second terminal in the project directory:

```powershell
.venv/Scripts/python.exe manage.py worker
```

Open http://127.0.0.1:8000. Click **Fill sample**, submit the order, then select it to preview and download the generated draft. Demo mode works without API credentials and generates a deterministic template from synthetic inputs. SQLite keeps jobs across restarts.

For frontend development, run `pnpm dev` in `frontend`. Vite proxies API requests to Django.

## Generation with Claude

Set these environment variables in the worker terminal before starting the worker:

```powershell
$env:CAREPLAN_MODE = 'claude'
$env:ANTHROPIC_API_KEY = '<your key>'
$env:ANTHROPIC_MODEL = '<an available Claude model ID>'
.venv/Scripts/python.exe manage.py worker
```

Set CAREPLAN_MODE in the web terminal too so the interface shows the corresponding mode. Credentials stay on the backend. Keep keys out of version control. The application has no login or clinical deployment controls. Use fictional data in this local prototype. A generated draft requires pharmacist review.

## Validation and recovery

MRNs contain six digits, NPIs contain ten digits, and diagnosis codes receive format validation. A database constraint blocks same-patient, same-medication orders on the same day. Existing patient identity differences and refills require confirmation. Provider NPIs are unique and a conflicting provider name is blocked.

The worker claims jobs with an atomic conditional update and a three-minute lease. Failed attempts are delayed 10 and 20 seconds. After three attempts the order becomes failed and can be explicitly retried. An interrupted worker's lease expires so another worker can reclaim it. The local queue uses SQLite and is intended for a single-machine demonstration.

CSV export includes the most recent and historical orders. Spreadsheet formula prefixes are escaped. Plans download as text.

## Checks

```powershell
.venv/Scripts/python.exe manage.py test
.venv/Scripts/python.exe manage.py check
cd frontend
pnpm build
```

The tests cover successful generation and download, validation, duplicate handling, provider conflicts, warning confirmation, failed generation and retry, and CSRF enforcement.

## Project scope

The original design draft is retained in design_doc.md. This implementation focuses on one web intake path and text/CSV export. Patient records are entered as text. AWS deployment, PDF parsing, authentication, and external patient/provider registries remain future integration work. The draft's client background is historical design context and does not establish a deployment or affiliation.
