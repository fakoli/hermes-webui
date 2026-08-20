#!/usr/bin/env bash
# sync-upstream.sh — keep this fork in sync with upstream nesquena/hermes-webui
# without losing local modifications.
#
# Usage:
#   scripts/sync-upstream.sh          # dry-run: fetch + report sync state only
#   scripts/sync-upstream.sh --rebase # fetch + rebase local master onto upstream
#
# Design:
#   - origin   = your fork (fakoli/hermes-webui)
#   - upstream = original (nesquena/hermes-webui)
#   - Never force-push. Rebase replays your local commits on top of upstream's
#     new commits; any commit that touches the same lines as our local patch
#     surfaces as a conflict to resolve manually (that's the safety net).
set -euo pipefail
cd "$(dirname "$0")/.."

REBASE=0
for a in "$@"; do
  case "$a" in
    --rebase) REBASE=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Unknown arg: $a (use --rebase to apply, otherwise dry-run)" >&2; exit 2 ;;
  esac
done

echo "==> fetching upstream..."
git fetch upstream --prune --tags

# How far apart are we?
LEFT=$(git rev-list --left-right --count master...upstream/master 2>/dev/null | awk '{print $1}')
RIGHT=$(git rev-list --left-right --count master...upstream/master 2>/dev/null | awk '{print $2}')
echo "    local master:  ${RIGHT:-0} ahead"
echo "    upstream:      ${LEFT:-0} ahead (we are ${LEFT:-0} behind)"

if [ "$REBASE" = "0" ]; then
  echo
  echo "Dry-run (no changes made). Upstream commits that would be applied:"
  git log --oneline --no-merges HEAD..upstream/master | head -20 || true
  if [ -z "$(git log --oneline HEAD..upstream/master 2>/dev/null)" ]; then
    echo "  (none — already up to date)"
  fi
  echo
  echo "Files upstream has changed since our HEAD (potential conflict surface):"
  git diff --name-only HEAD...upstream/master | sed 's/^/  /' || true
  echo
  echo "Run with --rebase to fetch + rebase local commits on top of upstream."
  exit 0
fi

# Actual sync: rebase local master onto upstream/master
if ! git diff --quiet; then
  echo "!! Working tree has uncommitted changes. Commit or stash them first." >&2
  exit 1
fi

echo "==> rebasing master onto upstream/master..."
git rebase upstream/master
echo "==> done. Local commits now sit on top of the latest upstream."
echo "    Review with:  git log --oneline -5"
echo "    Push to fork: git push origin master"
