#!/usr/bin/env python3
"""
reviewer.py — AI PR Reviewer using Groq (free)
Triggered by GitHub Actions on every PR open/update.
Posts a summary + inline code review comments.
"""
import os
import sys
import json
import urllib.request
import urllib.error

GROQ_API_KEY   = os.environ["GROQ_API_KEY"]
GITHUB_TOKEN   = os.environ["GITHUB_TOKEN"]
REPO           = os.environ["GITHUB_REPOSITORY"]
PR_NUMBER      = os.environ["PR_NUMBER"]
GROQ_MODEL     = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
MAX_FILES      = int(os.environ.get("MAX_FILES", "10"))
MAX_PATCH_CHARS = int(os.environ.get("MAX_PATCH_CHARS", "3000"))

GH_API  = "https://api.github.com"
GH_HDR  = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept":        "application/vnd.github+json",
    "User-Agent":    "ai-code-review-bot",
    "Content-Type":  "application/json",
}
GROQ_HDR = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type":  "application/json",
}


def gh(method, path, body=None):
    url  = f"{GH_API}{path}"
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(url, data=data, headers=GH_HDR, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"GitHub API error {e.code}: {e.read().decode()}")
        return {}


def groq_chat(messages, temperature=0.3):
    body = {
        "model":       GROQ_MODEL,
        "messages":    messages,
        "temperature": temperature,
        "max_tokens":  2048,
    }
    data = json.dumps(body).encode()
    req  = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=data, headers=GROQ_HDR, method="POST"
    )
    try:
        with urllib.request.urlopen(req) as r:
            resp = json.loads(r.read())
            return resp["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Groq API error {e.code}: {e.read().decode()}")


def get_pr_files():
    files = gh("GET", f"/repos/{REPO}/pulls/{PR_NUMBER}/files")
    return files[:MAX_FILES] if files else []


def get_pr_info():
    return gh("GET", f"/repos/{REPO}/pulls/{PR_NUMBER}")


def post_review(summary, comments):
    """Post a PR review with summary and inline comments."""
    body = {
        "body":     summary,
        "event":    "COMMENT",
        "comments": comments,
    }
    result = gh("POST", f"/repos/{REPO}/pulls/{PR_NUMBER}/reviews", body)
    return result


def build_file_diff(f):
    filename = f.get("filename", "")
    patch    = f.get("patch", "")[:MAX_PATCH_CHARS]
    status   = f.get("status", "")
    return f"File: {filename} ({status})\n```diff\n{patch}\n```"


def review_file(f):
    """Ask Groq to review a single file diff. Returns list of comment dicts."""
    filename = f.get("filename", "")
    patch    = f.get("patch", "")
    if not patch:
        return []

    patch = patch[:MAX_PATCH_CHARS]

    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert code reviewer. Review the git diff below and identify "
                "issues like bugs, security problems, performance issues, or bad practices. "
                "Be concise and specific. Format your response as a JSON array of objects, "
                "each with keys: 'line' (integer, the + line number in the diff to comment on), "
                "'comment' (string, your review comment). "
                "Only include issues worth flagging. If the code looks good, return empty array []."
            )
        },
        {
            "role": "user",
            "content": f"Review this diff for {filename}:\n\n```diff\n{patch}\n```"
        }
    ]

    try:
        response = groq_chat(messages, temperature=0.2)
        # Extract JSON from response
        start = response.find("[")
        end   = response.rfind("]") + 1
        if start == -1 or end == 0:
            return []
        items = json.loads(response[start:end])
        # Build GitHub review comments
        comments = []
        patch_lines = patch.split("\n")
        position = 1
        for item in items:
            if isinstance(item, dict) and "comment" in item:
                comments.append({
                    "path":     filename,
                    "position": min(position, max(1, len(patch_lines))),
                    "body":     f"**AI Review:** {item['comment']}",
                })
                position += 1
        return comments
    except Exception as e:
        print(f"  Error reviewing {filename}: {e}")
        return []


def generate_summary(pr_info, files):
    """Generate overall PR summary."""
    pr_title = pr_info.get("title", "")
    pr_body  = pr_info.get("body", "") or ""
    changed  = "\n".join([
        f"- {f['filename']} ({f.get('status','')}, +{f.get('additions',0)} -{f.get('deletions',0)})"
        for f in files
    ])
    diffs = "\n\n".join([build_file_diff(f) for f in files[:5]])

    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert code reviewer. Provide a clear, concise PR review summary. "
                "Include: 1) What the PR does, 2) Key concerns or issues, 3) Overall assessment. "
                "Use markdown formatting. Be constructive and specific."
            )
        },
        {
            "role": "user",
            "content": (
                f"PR Title: {pr_title}\n"
                f"PR Description: {pr_body[:500]}\n\n"
                f"Files changed:\n{changed}\n\n"
                f"Diffs:\n{diffs}"
            )
        }
    ]

    try:
        return groq_chat(messages, temperature=0.3)
    except Exception as e:
        return f"AI review summary unavailable: {e}"


def main():
    print(f"Reviewing PR #{PR_NUMBER} in {REPO}...")

    pr_info = get_pr_info()
    if not pr_info:
        print("Could not fetch PR info. Exiting.")
        sys.exit(1)

    files = get_pr_files()
    print(f"Found {len(files)} changed files")

    # Collect inline comments
    all_comments = []
    for f in files:
        fname = f.get("filename", "")
        print(f"  Reviewing {fname}...")
        comments = review_file(f)
        all_comments.extend(comments)
        print(f"    -> {len(comments)} comments")

    # Generate overall summary
    print("Generating summary...")
    summary = generate_summary(pr_info, files)

    # Add bot header to summary
    full_summary = (
        "## AI Code Review Bot\n\n"
        f"*Powered by Groq ({GROQ_MODEL}) — Free AI PR Reviewer*\n\n"
        "---\n\n"
        f"{summary}\n\n"
        "---\n"
        f"*Reviewed {len(files)} file(s), found {len(all_comments)} inline comment(s).*"
    )

    # Post review
    print(f"Posting review with {len(all_comments)} inline comments...")
    result = post_review(full_summary, all_comments)
    if result.get("id"):
        print(f"Review posted successfully! ID: {result['id']}")
    else:
        print(f"Review post result: {result}")


if __name__ == "__main__":
    main()
