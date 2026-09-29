"""ResearchAgent — AI Research workspace over user-pasted sources only."""
import os
import uuid
from typing import Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

MODEL_ID = "openai/gpt-oss-120b"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MAX_SOURCES = 6
MAX_SOURCE_CHARS = 8000

app = FastAPI(title="ResearchAgent")

# In-memory sessions: {session_id: {"sources": [{"title":..., "text":...}]}}
SESSIONS: Dict[str, Dict] = {}

VALID_JOBS = {"plan", "summarize", "claims", "compare", "report", "findings", "followups", "ask"}


def resolve_key(header_key: Optional[str]) -> Optional[str]:
    if header_key and header_key.strip():
        return header_key.strip()
    for name in ("GROQ_API_KEY", "GROQ_TEST_KEY"):
        v = os.environ.get(name, "").strip()
        if v:
            return v
    # .env fallback (read without printing key)
    env_path = os.path.join(BASE_DIR, ".env")
    try:
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("GROQ_API_KEY="):
                        v = line.split("=", 1)[1].strip().strip("'\"")
                        if v:
                            return v
    except Exception:
        pass
    return None


def get_session(session_id: Optional[str]) -> tuple[str, Dict]:
    sid = (session_id or "").strip() or str(uuid.uuid4())
    if sid not in SESSIONS:
        SESSIONS[sid] = {"sources": []}
    return sid, SESSIONS[sid]


def groq_client(api_key: str):
    from openai import OpenAI
    return OpenAI(api_key=api_key, base_url=GROQ_BASE_URL, timeout=60.0)


def map_groq_error(e: Exception) -> tuple[int, str]:
    msg = str(e)
    low = msg.lower()
    status = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
    try:
        status = int(status) if status else None
    except Exception:
        status = None
    if status == 401 or "invalid_api_key" in low or "unauthorized" in low or "invalid api key" in low:
        return 401, "Invalid API key (401). Open Settings and paste a valid Groq key."
    if status == 429 or "rate limit" in low or "429" in low:
        return 429, "Rate limited by Groq (429). Wait a moment and retry."
    if status == 404 or "model" in low and "not found" in low or "decommissioned" in low:
        return 404, f"Model not available (404): {MODEL_ID}."
    if "connect" in low or "connection" in low or "timeout" in low or "dns" in low or "network" in low:
        return 503, "Cannot reach Groq API (connection error). Check internet and retry."
    if status == 500 or status == 502 or status == 503 or "overloaded" in low or "server" in low:
        return 503, "Groq service temporarily unavailable (5xx). Retry shortly."
    return 502, f"Groq request failed: {msg[:300]}"


def call_llm(api_key: str, system: str, user: str, max_tokens: int = 1500) -> str:
    client = groq_client(api_key)
    try:
        resp = client.chat.completions.create(
            model=MODEL_ID,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.4,
            max_tokens=max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        code, friendly = map_groq_error(e)
        raise HTTPException(status_code=code, detail=friendly)


# ---------- Models ----------
class PlanIn(BaseModel):
    question: str = Field(default="")
    key: Optional[str] = None


class SourceIn(BaseModel):
    title: str = Field(default="")
    text: str = Field(default="")


class AnalyzeIn(BaseModel):
    job: str = Field(default="")
    question: Optional[str] = ""
    source_index: Optional[int] = None
    query: Optional[str] = ""
    history: Optional[List[Dict]] = None
    key: Optional[str] = None


class VerifyIn(BaseModel):
    key: str = Field(default="")


# ---------- Routes ----------
@app.get("/api/status")
def api_status(x_groq_key: Optional[str] = Header(default=None, alias="X-Groq-Key")):
    key = resolve_key(x_groq_key)
    src = "header" if (x_groq_key and x_groq_key.strip()) else ("env" if key else "none")
    return {"has_key": bool(key), "model": MODEL_ID, "key_source": src}


@app.post("/api/settings/verify")
def api_verify(body: VerifyIn):
    key = (body.key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="API key is required.")
    try:
        client = groq_client(key)
        client.models.list()
        return {"ok": True, "model": MODEL_ID}
    except Exception as e:
        code, friendly = map_groq_error(e)
        raise HTTPException(status_code=code, detail=friendly)


@app.post("/api/plan")
def api_plan(body: PlanIn, x_groq_key: Optional[str] = Header(default=None, alias="X-Groq-Key")):
    q = (body.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Research question is required.")
    if len(q) > 2000:
        raise HTTPException(status_code=400, detail="Question is too long (max 2000 chars).")
    api_key = resolve_key(body.key or x_groq_key)
    if not api_key:
        raise HTTPException(status_code=503, detail="No Groq API key configured. Open Settings and paste your key, or set GROQ_API_KEY in .env.")
    system = (
        "You are a research planner. Given ONLY the user's research question, produce a short structured research plan. "
        "Output markdown with headings: Objectives, Key sub-questions (numbered, max 6), Suggested source types, Search terms, Evaluation criteria, Limitations. "
        "Do NOT browse the web. Do NOT invent citations or URLs. Keep under 350 words."
    )
    out = call_llm(api_key, system, f"Research question:\n{q}", max_tokens=1000)
    return {"plan": out}


@app.get("/api/sources")
def list_sources(x_session_id: Optional[str] = Header(default=None, alias="X-Session-Id")):
    sid, sess = get_session(x_session_id)
    return JSONResponse(content={"session_id": sid, "sources": [{"title": s["title"], "chars": len(s["text"]), "preview": s["text"][:300]} for s in sess["sources"]], "count": len(sess["sources"]), "max": MAX_SOURCES})


@app.post("/api/sources")
async def add_source(request: Request, x_session_id: Optional[str] = Header(default=None, alias="X-Session-Id")):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")
    title = (data.get("title") or "").strip()
    text = (data.get("text") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Source title is required.")
    if len(title) > 200:
        raise HTTPException(status_code=400, detail="Title too long (max 200 chars).")
    if not text:
        raise HTTPException(status_code=400, detail="Source text is required (paste content).")
    if len(text) > MAX_SOURCE_CHARS:
        raise HTTPException(status_code=400, detail=f"Source too large: {len(text)} chars (max {MAX_SOURCE_CHARS}).")
    sid, sess = get_session(x_session_id)
    if len(sess["sources"]) >= MAX_SOURCES:
        raise HTTPException(status_code=400, detail=f"Too many sources (max {MAX_SOURCES}). Remove one first.")
    sess["sources"].append({"title": title, "text": text})
    return {"session_id": sid, "count": len(sess["sources"]), "index": len(sess["sources"]) - 1}


@app.delete("/api/sources")
def clear_sources(x_session_id: Optional[str] = Header(default=None, alias="X-Session-Id")):
    sid, sess = get_session(x_session_id)
    sess["sources"] = []
    return {"session_id": sid, "count": 0}


@app.delete("/api/sources/{index}")
def delete_source(index: int, x_session_id: Optional[str] = Header(default=None, alias="X-Session-Id")):
    sid, sess = get_session(x_session_id)
    if index < 0 or index >= len(sess["sources"]):
        raise HTTPException(status_code=404, detail="Source index out of range.")
    sess["sources"].pop(index)
    return {"session_id": sid, "count": len(sess["sources"])}


@app.post("/api/analyze")
def api_analyze(body: AnalyzeIn, x_groq_key: Optional[str] = Header(default=None, alias="X-Groq-Key"), x_session_id: Optional[str] = Header(default=None, alias="X-Session-Id")):
    job = (body.job or "").strip().lower()
    if job not in VALID_JOBS:
        raise HTTPException(status_code=400, detail=f"Unknown job '{body.job}'. Valid: {sorted(VALID_JOBS)}.")
    sid, sess = get_session(x_session_id)
    sources: List[Dict] = sess["sources"]
    api_key = resolve_key(body.key or x_groq_key)
    if not api_key:
        raise HTTPException(status_code=503, detail="No Groq API key configured. Open Settings and paste your key, or set GROQ_API_KEY in .env.")

    def src_block(s, i):
        return f"--- SOURCE {i+1}: {s['title']} ---\n{s['text']}"

    honesty = (
        "CRITICAL HONESTY RULES: You ONLY know the user-pasted sources below. Never browse the web. "
        "Never invent citations, URLs, authors, dates, or statistics not present in the sources. "
        "Every factual claim in your answer MUST be tagged with its source title in brackets, e.g. [Source: <title>]. "
        "If the sources disagree or lack info, say so explicitly. "
        "Visually separate: quote/paraphrase source content under 'From sources' and your own reasoning under 'AI analysis'."
    )

    if job == "plan":
        q = (body.question or "").strip()
        if not q:
            raise HTTPException(status_code=400, detail="Question is required for job 'plan'.")
        out = call_llm(api_key, "You are a research planner. " + honesty, f"Research question:\n{q}\n\nProduce a structured plan (Objectives, Sub-questions, Method, Limitations). No invented citations.", max_tokens=1000)
        return {"job": job, "session_id": sid, "result": out}

    if job in ("summarize", "claims"):
        if body.source_index is None:
            raise HTTPException(status_code=400, detail=f"'source_index' is required for job '{job}'.")
        idx = body.source_index
        if idx < 0 or idx >= len(sources):
            raise HTTPException(status_code=404, detail="Source index out of range.")
        s = sources[idx]
        if job == "summarize":
            sys = "You summarize a single user-pasted source. " + honesty
            usr = f"Summarize this source in <=200 words with bullet key points. Tag claims with [Source: {s['title']}].\n\nTitle: {s['title']}\nText:\n{s['text']}"
            out = call_llm(api_key, sys, usr, max_tokens=800)
            return {"job": job, "session_id": sid, "source": s["title"], "result": out}
        else:
            sys = "You extract key claims from a single user-pasted source. " + honesty
            usr = f"Extract up to 8 distinct key claims from the source below. Number them. Each claim MUST end with [Source: {s['title']}]. No claims beyond the text.\n\nTitle: {s['title']}\nText:\n{s['text']}"
            out = call_llm(api_key, sys, usr, max_tokens=900)
            return {"job": job, "session_id": sid, "source": s["title"], "result": out}

    if job == "compare":
        if len(sources) < 2:
            raise HTTPException(status_code=400, detail="Compare needs at least 2 sources. Add more sources first.")
        joined = "\n\n".join(src_block(s, i) for i, s in enumerate(sources))
        sys = "You compare user-pasted sources. " + honesty
        usr = ("Compare the sources below. Output markdown with sections: ## Agreements (claims 2+ sources agree on, each tagged with ALL agreeing source titles), "
               "## Disagreements / Contradictions (tag each side with its source title), ## Unique points (tag source). Never invent claims.\n\n" + joined)
        out = call_llm(api_key, sys, usr, max_tokens=1500)
        return {"job": job, "session_id": sid, "result": out}

    if job == "report":
        q = (body.question or "").strip()
        if not q:
            raise HTTPException(status_code=400, detail="Question is required for job 'report'.")
        if not sources:
            raise HTTPException(status_code=400, detail="Report needs at least 1 source. Paste sources first.")
        joined = "\n\n".join(src_block(s, i) for i, s in enumerate(sources))
        sys = "You write a structured research report grounded ONLY in user-pasted sources. " + honesty
        usr = (f"Research question: {q}\n\nSources:\n{joined}\n\nWrite a markdown report with: # Title, ## Executive summary, ## Evidence from sources "
               "(every paragraph tagged with [Source: title]), ## AI analysis (your synthesis, clearly labeled as analysis, not source fact), "
               "## Agreements & disagreements, ## Limitations (what sources don't cover), ## Conclusion. No invented citations.")
        out = call_llm(api_key, sys, usr, max_tokens=2200)
        return {"job": job, "session_id": sid, "result": out}

    if job == "findings":
        if not sources:
            raise HTTPException(status_code=400, detail="Findings need at least 1 source.")
        joined = "\n\n".join(src_block(s, i) for i, s in enumerate(sources))
        sys = "You list key findings from user-pasted sources. " + honesty
        usr = "List the top 7 key findings across these sources as bullets. Each bullet MUST end with [Source: title(s)].\n\n" + joined
        out = call_llm(api_key, sys, usr, max_tokens=1000)
        return {"job": job, "session_id": sid, "result": out}

    if job == "followups":
        q = (body.question or "").strip()
        if not q:
            raise HTTPException(status_code=400, detail="Question is required for job 'followups'.")
        ctx = "\n\n".join(src_block(s, i) for i, s in enumerate(sources)) if sources else "(no sources pasted yet)"
        sys = "You suggest follow-up research questions. " + honesty
        usr = f"Original question: {q}\nSources:\n{ctx}\n\nSuggest 6 follow-up questions that address gaps in these sources. Number them."
        out = call_llm(api_key, sys, usr, max_tokens=800)
        return {"job": job, "session_id": sid, "result": out}

    # ask
    query = (body.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required for job 'ask'.")
    hist = body.history or []
    clean_hist = []
    for m in hist[-8:]:
        try:
            r = str(m.get("role", "user"))
            c = str(m.get("content", ""))[:2000]
            if r in ("user", "assistant") and c.strip():
                clean_hist.append({"role": r, "content": c})
        except Exception:
            continue
    ctx = "\n\n".join(src_block(s, i) for i, s in enumerate(sources)) if sources else "(no sources pasted yet — answer only from conversation, and say coverage is limited)"
    sys = "You are a research assistant answering ONLY from user-pasted sources plus conversation. " + honesty
    from openai import OpenAI as _OA
    client = _OA(api_key=api_key, base_url=GROQ_BASE_URL, timeout=60.0)
    try:
        resp = client.chat.completions.create(
            model=MODEL_ID,
            messages=[{"role": "system", "content": sys + f"\n\nSOURCES:\n{ctx}"}] + clean_hist + [{"role": "user", "content": query}],
            temperature=0.4,
            max_tokens=1000,
        )
        out = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        code, friendly = map_groq_error(e)
        raise HTTPException(status_code=code, detail=friendly)
    return {"job": job, "session_id": sid, "result": out}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
