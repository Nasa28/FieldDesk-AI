#!/usr/bin/env bash
#
# Pre-commit secret scanner. Blocks the commit if staged content matches any
# of the known-secret patterns below. Runs entirely from bash + git — no
# external tools required.
#
# False positives can be bypassed with `LEFTHOOK=0 git commit ...` and an
# explanation in the PR description.

set -euo pipefail

scope="${CHECK_SECRETS_SCOPE:-staged}"

patterns=(
  "AKIA[0-9A-Z]{16}"                                # AWS Access Key ID
  "aws_secret_access_key.*=.*[A-Za-z0-9/+]{40}"     # AWS Secret
  "sk-ant-[a-zA-Z0-9_-]{40,}"                       # Anthropic API key
  "sk-proj-[a-zA-Z0-9_-]{40,}"                      # OpenAI project key
  "sk-[a-zA-Z0-9]{40,}"                             # OpenAI / generic sk- prefix
  "pk_live_[a-zA-Z0-9]{20,}"                        # Stripe live publishable
  "sk_live_[a-zA-Z0-9]{20,}"                        # Stripe live secret
  "ghp_[a-zA-Z0-9]{36}"                             # GitHub personal access token
  "gho_[a-zA-Z0-9]{36}"                             # GitHub OAuth token
  "github_pat_[a-zA-Z0-9_]{80,}"                    # GitHub fine-grained PAT
  "xox[baprs]-[a-zA-Z0-9-]+"                        # Slack tokens
  "-----BEGIN [A-Z ]*PRIVATE KEY-----"              # PEM-encoded private keys
)

if [ "$scope" != "staged" ] && [ "$scope" != "all" ]; then
  echo "❌ Invalid CHECK_SECRETS_SCOPE: $scope" >&2
  exit 1
fi

found=0

scan_staged() {
  local pattern="$1"
  # Diff of staged changes only; -U0 keeps the noise low.
  # `-e` disambiguates patterns that start with `-` (e.g. -----BEGIN ...PRIVATE KEY-----).
  git diff --cached -U0 | grep -E -e '^\+' | grep -vE -e '^\+\+\+' | grep -E -e "$pattern" || true
}

scan_all() {
  local pattern="$1"
  set +e
  git grep -n -I -E -e "$pattern" -- . ':(exclude)*.lock' ':(exclude)go.sum' ':(exclude)package-lock.json'
  local status=$?
  set -e
  if [ "$status" -ge 2 ]; then
    echo "❌ git grep internal error ($status) on pattern: $pattern" >&2
    exit 1
  fi
  return 0
}

for pattern in "${patterns[@]}"; do
  if [ "$scope" = "staged" ]; then
    matches=$(scan_staged "$pattern")
  else
    matches=$(scan_all "$pattern" || true)
  fi

  if [ -n "$matches" ]; then
    if [ "$found" -eq 0 ]; then
      echo "❌ Possible secrets detected ($scope):"
      echo ""
    fi
    echo "   Pattern: $pattern"
    printf '%s\n' "$matches" | head -3 | sed 's/^/      /'
    echo ""
    found=1
  fi
done

if [ "$found" -ne 0 ]; then
  echo "If this is a false positive, bypass with LEFTHOOK=0 and explain in the PR." >&2
  exit 1
fi

echo "✓ no secret patterns detected ($scope)"
