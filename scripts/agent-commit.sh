#!/usr/bin/env bash
# Agent uchun checkpoint: o'zgarishlarni commit qilib, to'g'ridan-to'g'ri main'ga push qiladi.
# Ishlatish: bash scripts/agent-commit.sh "qisqa izoh"
set -euo pipefail

msg="${1:-checkpoint}"
branch="${GIT_PUSH_BRANCH:-main}"
ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

git config user.name "opencode-agent"
git config user.email "opencode-agent@users.noreply.github.com"

git add -A

if git diff --cached --quiet; then
  echo "agent-commit: o'zgarish yo'q, commit qilinmadi"
  exit 0
fi

git commit -m "ai: ${msg} [${ts}]"

# Force-push hech qachon. Faqat oddiy fast-forward push.
git push origin "HEAD:${branch}"

echo "agent-commit: push qilindi -> ${branch}"
