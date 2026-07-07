"""
main.py - FastAPI webhook server for AI PR Code Reviewer
Receives GitHub webhook events and auto-reviews PRs using Groq (free)
Keep-alive: pings itself every 14 minutes so Render free tier never sleeps.
"""
import os
import json
import hmac
import hashlib
import asyncio
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
import httpx

app = FastAPI(
    title="AI Code Review Bot",
    description="Auto-reviews GitHub PRs using Groq LLM - 100% free",
    version="1.0.0"
)

GROQ_API_KEY    = os.environ.get("GROQ_API_KEY", "")
GITHUB_TOKEN    = os.environ.get("GITHUB_TOKEN", "")
WEBHOOK_SECRET  = os.environ.get("WEBHOOK_SECRET", "")
GROQ_MODEL      = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
MAX_FILES       = int(os.environ.get("MAX_FILES", "10"))
MAX_PATCH_CHARS = int(os.environ.get("MAX_PATCH_CHARS", "3000"))
RENDER_URL      = os.environ.get("RENDER_URL", "")


# ---------------------------------------------------------------------------
# Keep-alive: ping self every 14 min so Render free tier never sleeps
# ---------------------------------------------------------------------------
async def _keep_alive():
    await asyncio.sleep(60)
    while True:
        if RENDER_URL:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.get(f"{RENDER_URL}/ping")
                    print("Keep-alive ping sent ✓")
            except Exception as e:
                print(f"Keep-alive ping failed: {e}")
        await asyncio.sleep(14 * 60)


@app.on_event("startup")
async def startup():
    asyncio.create_task(_keep_alive())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def verify_signature(payload: bytes, signature: str) -> bool:
    if not WEBHOOK_SECRET:
        return True
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def groq_chat(messages: list, temperature: float = 0.3) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": GROQ_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": 2048,
            }
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def get_pr_files(repo: str, pr_number: int) -> list:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files",
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            }
        )
        resp.raise_for_status()
        return resp.json()[:MAX_FILES]


async def get_pr_info(repo: str, pr_number: int) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"https://api.github.com/repos/{repo}/pulls/{pr_number}",
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            }
        )
        resp.raise_for_status()
        return resp.json()


async def post_pr_comment(repo: str, pr_number: int, body: str):
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments",
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            },
            json={"body": body}
        )
        resp.raise_for_status()
        return resp.json()


async def review_file(filename: str, patch: str) -> list:
    if not patch:
        return []
    patch = patch[:MAX_PATCH_CHARS]
    format_hint = '[{"issue": "description", "severity": "high|medium|low"}]'
    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert code reviewer. Review the git diff and find bugs, "
                "security issues, performance problems, or bad practices. "
                "Be concise. Format as JSON array: " + format_hint + ". "
                "Return [] if code looks good."
            )
        },
        {
            "role": "user",
            "content": "Review diff for " + filename + ":\n```diff\n" + patch + "\n```"
        }
    ]
    try:
        resp = await groq_chat(messages, temperature=0.2)
        start = resp.find("[")
        end   = resp.rfind("]") + 1
        if start == -1 or end == 0:
            return []
        return json.loads(resp[start:end])
    except Exception:
        return []


async def generate_summary(pr_info: dict, files: list) -> str:
    changed = "\n".join([
        "- " + f["filename"] + " (+" + str(f.get("additions", 0)) + " -" + str(f.get("deletions", 0)) + ")"
        for f in files
    ])
    diffs = "\n\n".join([
        "File: " + f["filename"] + "\n```diff\n" + f.get("patch", "")[:1500] + "\n```"
        for f in files[:4]
    ])
    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert code reviewer. Give a concise PR review with: "
                "1) What this PR does, 2) Key issues found, 3) Overall verdict. "
                "Use markdown. Be direct and helpful."
            )
        },
        {
            "role": "user",
            "content": (
                "PR: " + pr_info.get("title", "") + "\n"
                "Description: " + (pr_info.get("body", "") or "")[:300] + "\n\n"
                "Files changed:\n" + changed + "\n\nDiffs:\n" + diffs
            )
        }
    ]
    try:
        return await groq_chat(messages, temperature=0.3)
    except Exception as e:
        return "Could not generate summary: " + str(e)


async def process_pr(repo: str, pr_number: int, pr_title: str):
    print("Reviewing PR #" + str(pr_number) + " in " + repo + ": " + pr_title)
    try:
        pr_info = await get_pr_info(repo, pr_number)
        files   = await get_pr_files(repo, pr_number)
        print("  Found " + str(len(files)) + " files")

        all_issues   = []
        file_reviews = []
        for f in files:
            fname  = f.get("filename", "")
            issues = await review_file(fname, f.get("patch", ""))
            if issues:
                all_issues.extend(issues)
                lines = ["**`" + fname + "`**"]
                for issue in issues:
                    sev   = issue.get("severity", "medium")
                    emoji = {"high": "🔴", "medium": "🟡", "low": "🔵"}.get(sev, "🟡")
                    lines.append("  " + emoji + " " + issue.get("issue", str(issue)))
                file_reviews.append("\n".join(lines))

        summary = await generate_summary(pr_info, files)

        if file_reviews:
            issues_section = "\n\n### Inline Issues Found\n\n" + "\n\n".join(file_reviews)
        else:
            issues_section = "\n\n### Inline Issues\n\n✅ No major issues found."

        comment = (
            "## 🤖 AI Code Review\n\n"
            "*Powered by **Groq** (" + GROQ_MODEL + ") — Free AI PR Reviewer*\n\n"
            "---\n\n"
            + summary
            + issues_section + "\n\n"
            "---\n"
            "*Reviewed **" + str(len(files)) + "** file(s) · Found **" + str(len(all_issues)) + "** issue(s)*"
        )

        await post_pr_comment(repo, pr_number, comment)
        print("  Review posted for PR #" + str(pr_number))

    except Exception as e:
        print("  Error reviewing PR #" + str(pr_number) + ": " + str(e))
        try:
            await post_pr_comment(
                repo, pr_number,
                "## 🤖 AI Code Review\n\n❌ Review failed: " + str(e)
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/ping")
def ping():
    """Keep-alive endpoint — called every 14 min to prevent Render sleep."""
    return {"status": "alive"}


@app.get("/health")
def health():
    return {"status": "ok", "model": GROQ_MODEL}


@app.get("/", response_class=HTMLResponse)
def dashboard():
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>AI Code Review Bot</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#0d1117;color:#e6edf3;min-height:100vh}
.container{max-width:800px;margin:0 auto;padding:60px 20px}
.badge{display:inline-block;background:#238636;color:#fff;padding:4px 12px;border-radius:20px;font-size:13px;margin-bottom:20px}
h1{font-size:2.5rem;font-weight:700;margin-bottom:12px}
.subtitle{color:#8b949e;font-size:1.1rem;margin-bottom:40px}
.card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:28px;margin-bottom:24px}
.card h2{font-size:1.1rem;margin-bottom:16px;color:#58a6ff}
.step{display:flex;gap:16px;margin-bottom:16px;align-items:flex-start}
.num{background:#1f6feb;color:#fff;width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;flex-shrink:0}
.txt{color:#8b949e;font-size:14px;line-height:1.6}
.txt code{background:#21262d;padding:2px 8px;border-radius:4px;font-family:monospace;color:#e6edf3;font-size:13px}
.status{display:flex;align-items:center;gap:8px}
.dot{width:10px;height:10px;border-radius:50%;background:#238636;box-shadow:0 0 8px #238636;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{box-shadow:0 0 8px #238636}50%{box-shadow:0 0 16px #238636}}
</style>
</head>
<body>
<div class="container">
  <div class="badge">🟢 Live</div>
  <h1>🤖 AI Code Review Bot</h1>
  <p class="subtitle">Auto-reviews GitHub PRs using Groq AI — 100% free, works on any repo</p>
  <div class="card">
    <h2>⚡ Status</h2>
    <div class="status"><div class="dot"></div><span>Webhook server running — never sleeps</span></div>
  </div>
  <div class="card">
    <h2>🔗 Add to any GitHub repo (30 seconds)</h2>
    <div class="step"><div class="num">1</div><div class="txt">Go to your repo → Settings → Webhooks → Add webhook</div></div>
    <div class="step"><div class="num">2</div><div class="txt">Payload URL: <code>YOUR_RENDER_URL/webhook</code></div></div>
    <div class="step"><div class="num">3</div><div class="txt">Content type: <code>application/json</code></div></div>
    <div class="step"><div class="num">4</div><div class="txt">Events: select <code>Pull requests</code> only</div></div>
    <div class="step"><div class="num">5</div><div class="txt">Save — open any PR and the bot reviews it automatically!</div></div>
  </div>
</div>
</body>
</html>"""
    return html


@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    payload_bytes = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")
    if WEBHOOK_SECRET and not verify_signature(payload_bytes, sig):
        raise HTTPException(status_code=401, detail="Invalid signature")

    event = request.headers.get("X-GitHub-Event", "")
    if event != "pull_request":
        return {"status": "ignored", "event": event}

    payload   = json.loads(payload_bytes)
    action    = payload.get("action", "")
    if action not in ("opened", "synchronize", "reopened"):
        return {"status": "ignored", "action": action}

    repo      = payload["repository"]["full_name"]
    pr_number = payload["pull_request"]["number"]
    pr_title  = payload["pull_request"]["title"]
    background_tasks.add_task(process_pr, repo, pr_number, pr_title)
    return {"status": "reviewing", "pr": pr_number, "repo": repo}


@app.post("/review")
async def manual_review(request: Request):
    body      = await request.json()
    repo      = body.get("repo")
    pr_number = body.get("pr_number")
    if not repo or not pr_number:
        raise HTTPException(400, "repo and pr_number required")
    asyncio.create_task(process_pr(repo, int(pr_number), "Manual review"))
    return {"status": "reviewing", "pr": pr_number, "repo": repo}
