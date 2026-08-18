# Running Phoenix after cloning from GitHub

This guide explains how to run the sanitized Project Phoenix AI repository after cloning or downloading it from GitHub. The public repository must never contain a real `.env`, OAuth client JSON, access token, database, generated videos, or provider secrets.

## Recommended single-command startup

If Git Bash or WSL is available, run the complete stack from the project root:

```bash
cd project-phoenix-ai
./run.sh
```

The launcher creates or reuses the Python virtual environment, installs Python dependencies, installs/builds the frontend, creates runtime directories, checks the media toolchain, and starts the API, scheduler, and built dashboard on one port. Open `http://localhost:8000` after startup. In this recommended mode, separate backend and frontend terminals are not required.

## Backend commands — Windows PowerShell

Use Terminal 1 from the project root:

```powershell
cd project-phoenix-ai
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:PYTHONUTF8=1
python backend\cli.py serve
```

If PowerShell blocks virtual-environment activation, run this once for the current Windows user and then activate again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## Backend commands — Windows CMD

Use Command Prompt Terminal 1:

```bat
cd project-phoenix-ai
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
set PYTHONUTF8=1
python backend\cli.py serve
```

## Frontend commands — development mode

Use Terminal 2. Keep the backend running in Terminal 1:

```powershell
cd project-phoenix-ai\frontend
npm install
npm run dev
```

The same commands work in Windows CMD:

```bat
cd project-phoenix-ai\frontend
npm install
npm run dev
```

The frontend development server normally uses `http://localhost:5173`, while the backend API remains on `http://localhost:8000`. Python virtual-environment activation is not required in the frontend terminal because `npm` is a Node.js command.

## Exact two-terminal command blocks

The following are the requested commands in their direct form.

### Terminal 1 — backend

```text
cd project-phoenix-ai
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
set PYTHONUTF8=1
python backend/cli.py serve
```

### Terminal 2 — frontend

```text
cd project-phoenix-ai
.venv\Scripts\activate
cd frontend
npm install
npm run dev
```

The frontend does not technically need `.venv\Scripts\activate`; it is retained above exactly as requested. For a cleaner setup, activate the environment only in Terminal 1 and run the frontend commands from `project-phoenix-ai\frontend` in Terminal 2.

## Environment file placement

The real environment file belongs beside `run.sh`:

```text
project-phoenix-ai\.env
```

Do not put provider keys in `frontend\.env` or upload them to GitHub. The main provider variables are:

```dotenv
OPENROUTER_API_KEY=your_real_value
GEMINI_API_KEY=your_real_value
GROK_API_KEY=your_real_value
PEXELS_API_KEY=your_real_value
PIXABAY_API_KEY=your_real_value
JAMENDO_CLIENT_ID=your_real_value
```

To safely merge a local environment file without allowing blank values to erase existing credentials:

```powershell
python backend\cli.py import-env C:\path\to\your\.env
```

The import command accepts only non-empty values, creates a timestamped backup, and refuses an empty or redacted source file. Provider credentials appear in the dashboard only as masked configured status.

## GitHub safety checklist

Before committing, verify that `.env`, `secrets/client_secret.json`, `data/phoenix.db`, `data/tokens`, generated media, logs, and virtual environments are not staged. The repository `.gitignore` excludes these sensitive and generated files. The public repository contains only the sanitized source, documentation, tests, and safe dashboard screenshots.
