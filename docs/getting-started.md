# Getting Started

## 1. Backend

```bash
cp .env.example backend/.env      # then edit it: put in your DEEPSEEK_API_KEY

cd backend
uv venv                           # create a virtualenv (uv is already installed)
source .venv/bin/activate
uv pip install -r requirements.txt
uvicorn main:app --reload --port 8010
```

Check it's alive: <http://localhost:8010/api/health>

## 2. Frontend (separate terminal)

```bash
cd frontend
pnpm install --store-dir .pnpm-store
pnpm dev
```

Open <http://localhost:5173> — Vite proxies `/api` to the backend on port 8010.

## 3. Try it

Type: **"Create a Python script that prints the first 20 Fibonacci numbers, then run it."**

You'll see the model run `bash` commands (writing and running a file inside
`sample-project/`), and the file will actually appear there.

## Run the tests

```bash
cd backend
.venv/bin/python -m pytest -q
```

## Config

All via environment variables (or `backend/.env`):

| Var | Default | What it does |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | *(required)* | Your DeepSeek API key |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | API endpoint |
| `DEEPSEEK_MODEL` | `deepseek-chat` | Model name |
| `MAX_STEPS` | `10` | Max model↔tool round-trips per turn |
| `BASH_TIMEOUT` | `30` | Seconds before a bash command is killed |
