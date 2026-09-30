# ResearchAgent — AI Research Workspace (Project 5)

Premium dark research-workspace UI (teal/steel) with a **Question → Sources → Analysis → Report** flow.
**Honesty-first:** no web search, no invented citations. All analysis runs over **user-pasted sources only**,
and the UI visually separates source text from AI analysis. Every claim is tagged `[Source: title]`.

- **Model:** `openai/gpt-oss-120b` via Groq OpenAI-compatible endpoint (`https://api.groq.com/openai/v1`)
- **Stack:** Python + FastAPI + vanilla HTML/CSS/JS, port **8004**

## Features
- Research question input + research-plan generator (`POST /api/plan`)
- Up to 6 pasted sources (title + text, ≤8000 chars each, in-memory per session)
- Jobs via `POST /api/analyze {job}`: `plan` / `summarize` / `claims` / `compare` / `report` / `findings` / `followups` / `ask` (free ask with history)
- Cross-source compare (agreements / disagreements, each claim tagged with source title)
- Full structured report + key findings + follow-up questions
- Report view with **Copy** + **Download (.md)**; Clear/reset session
- Settings modal (paste key, live `models.list` verify via `POST /api/key` into server process memory only — never browser storage, `DELETE /api/key` to remove) + `.env` fallback + `GET /api/status` pill (`key_source`: settings|env|none)
- Validation + friendly errors; Groq 401/429/404/503/connection mapped

## Run
```powershell
pip install -r requirements.txt
uvicorn app:app --port 8004
# open http://localhost:8004
```

## Test
```powershell
pip install -r requirements-test.txt
pytest -q
```

## Limitations
- Sources are in-memory per session (server restart clears them).
- No live web search by design; quality depends on pasted source quality.
- Groq rate limits / key required for all AI jobs.
