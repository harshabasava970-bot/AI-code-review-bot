# AI Code Review Bot

Auto-reviews every GitHub PR using **Groq AI** (Llama 3.3 70B) — 100% free.

## Live Demo
- **Bot URL:** https://ai-code-review-bot.onrender.com
- **Health:** https://ai-code-review-bot.onrender.com/health

## Architecture
```
PR opened on any repo
        ↓
GitHub webhook → POST /webhook on Render
        ↓
FastAPI receives event
        ↓
Fetches PR diff via GitHub API
        ↓
Sends diff to Groq (Llama 3.3 70B) - FREE
        ↓
Posts review comment back to PR
```

## Setup in 3 steps

### Step 1 — Add webhook to your repo
1. Go to your repo → **Settings** → **Webhooks** → **Add webhook**
2. Payload URL: `https://YOUR-RENDER-URL/webhook`
3. Content type: `application/json`
4. Events: select **Pull requests** only
5. Save

### Step 2 — Done!
Open a PR and the bot will auto-review it.

## Stack
- **Backend:** FastAPI + Python
- **AI:** Groq Llama 3.3 70B (free)
- **Deploy:** Render.com (free)
- **Trigger:** GitHub Webhooks + GitHub Actions

## Cost
100% free forever.
