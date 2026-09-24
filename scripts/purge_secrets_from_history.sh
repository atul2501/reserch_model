#!/usr/bin/env bash
# Runbook helper: remove committed .env files from the WHOLE git history.
#
# THIS SCRIPT DOES NOT REWRITE ANYTHING BY DEFAULT. It prints what it would do.
# Rewriting history + force-pushing is destructive and must be done by an
# authorised operator, on a fresh mirror clone, AFTER the credentials below have
# been rotated (rotation is mandatory: anyone who cloned/forked already has them).
#
#   1. ROTATE FIRST: Hyperliquid wallet key (move funds to a new wallet),
#      Ollama API keys, database password.
#   2. ./scripts/purge_secrets_from_history.sh            # dry run: lists commits touching the files
#   3. ./scripts/purge_secrets_from_history.sh --execute  # runs filter-repo in a *mirror clone*
#   4. Inspect the mirror, then force-push it yourself and ask collaborators to re-clone.
set -euo pipefail

PATHS=(.env backend/.env frontend/.env)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "Commits that touched secret-bearing paths (hashes only):"
for p in "${PATHS[@]}"; do
  git log --all --format='  %h %s' -- "$p" | sed "s|^|[$p]|"
done

if [ "${1:-}" != "--execute" ]; then
  echo
  echo "Dry run only. Re-run with --execute to prepare a cleaned MIRROR clone (no push is performed)."
  exit 0
fi

command -v git-filter-repo >/dev/null || { echo "git-filter-repo is required (pip install git-filter-repo)" >&2; exit 1; }
MIRROR="${REPO_ROOT}/../$(basename "$REPO_ROOT")-cleaned.git"
[ -e "$MIRROR" ] && { echo "$MIRROR already exists; refusing to overwrite" >&2; exit 1; }
git clone --mirror "$REPO_ROOT" "$MIRROR"
cd "$MIRROR"
args=()
for p in "${PATHS[@]}"; do args+=(--path "$p"); done
git filter-repo --invert-paths "${args[@]}"
echo "Cleaned mirror at: $MIRROR"
echo "Review it, then push YOURSELF:  git -C '$MIRROR' push --force --mirror <remote-url>"
