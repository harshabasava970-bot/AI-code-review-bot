# AI Code Review Bot

Automatically reviews every Pull Request using **Groq's free LLM API** (Llama 3.3 70B).
Posts a PR summary + inline code review comments — fully free, no OpenAI needed.

## How it works

```
PR opened/updated
      ↓
GitHub Actions triggers
      ↓
reviewer.py fetches PR diff via GitHub API
      ↓
Each file diff sent to Groq (Llama 3.3 70B) for review
      ↓
Overall summary generated
      ↓
Review posted as PR comment with inline annotations
```

## Setup (2 steps)

### Step 1 — Add your Groq API key to GitHub Secrets

1. Go to your repo → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Name: `GROQ_API_KEY`
4. Value: your key from [console.groq.com](https://console.groq.com) (free)
5. Click **Add secret**

### Step 2 — Open a Pull Request

That's it. Every PR will now get auto-reviewed.

## What the bot reviews

- Bugs and logic errors
- Security vulnerabilities
- Performance issues
- Bad practices and code smells
- Suggests improvements inline

## Cost

**100% free.**
- GitHub Actions: free (2000 min/month on free tier)
- Groq API: free tier with generous rate limits
- No server, no database, no deployment needed

## Stack

| Component | Technology |
|---|---|
| AI Model | Llama 3.3 70B via Groq |
| Runtime | GitHub Actions (ubuntu-latest) |
| Language | Python 3.11 (stdlib only) |
| GitHub API | REST via urllib |

## Configuration

Set these as GitHub Actions environment variables in the workflow:

| Variable | Default | Description |
|---|---|---|
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Groq model to use |
| `MAX_FILES` | `10` | Max files to review per PR |
| `MAX_PATCH_CHARS` | `3000` | Max diff chars per file |
