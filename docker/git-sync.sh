#!/usr/bin/env bash
# Git-backed campaign store helper for the headless host.
#
#   git-sync.sh clone-or-pull   # on startup: clone the campaigns repo (first run)
#                               # or pull --rebase (later runs)
#   git-sync.sh push [message]  # after a turn: commit + push play-state
#
# Auth: DND_CAMPAIGNS_REPO is the https remote; GITHUB_TOKEN (the scoped PAT /
# deploy token) is injected as x-access-token. Runtime state under .runtime/ is
# never committed (the display writes per-session tokens/queues there).
set -uo pipefail

: "${DND_CAMPAIGN_ROOT:=/home/node/dnd}"
ACTION="${1:-}"

authed_url() {
  local url="${DND_CAMPAIGNS_REPO:-}"
  if [ -n "${GITHUB_TOKEN:-}" ] && [[ "$url" == https://* ]]; then
    printf '%s' "${url/https:\/\//https://x-access-token:${GITHUB_TOKEN}@}"
  else
    printf '%s' "$url"
  fi
}

git config --global user.email "${DND_GIT_EMAIL:-dnd-game@soper.ninja}"
git config --global user.name  "${DND_GIT_NAME:-claude-dnd}"
git config --global --add safe.directory "$DND_CAMPAIGN_ROOT"

case "$ACTION" in
  clone-or-pull)
    if [ -z "${DND_CAMPAIGNS_REPO:-}" ]; then
      echo "[git-sync] DND_CAMPAIGNS_REPO unset; skipping." >&2; exit 0
    fi
    if [ -d "$DND_CAMPAIGN_ROOT/.git" ]; then
      git -C "$DND_CAMPAIGN_ROOT" remote set-url origin "$(authed_url)"
      git -C "$DND_CAMPAIGN_ROOT" pull --rebase --autostash || true
    elif [ -z "$(ls -A "$DND_CAMPAIGN_ROOT" 2>/dev/null)" ]; then
      git clone "$(authed_url)" "$DND_CAMPAIGN_ROOT"
    else
      echo "[git-sync] $DND_CAMPAIGN_ROOT is non-empty and not a git repo; not cloning." >&2
      exit 1
    fi
    # Make sure session runtime state is never committed.
    if ! grep -qxF '.runtime/' "$DND_CAMPAIGN_ROOT/.gitignore" 2>/dev/null; then
      echo '.runtime/' >> "$DND_CAMPAIGN_ROOT/.gitignore"
    fi
    ;;
  push)
    [ -d "$DND_CAMPAIGN_ROOT/.git" ] || { echo "[git-sync] not a git repo; skip push." >&2; exit 0; }
    git -C "$DND_CAMPAIGN_ROOT" add -A
    if ! git -C "$DND_CAMPAIGN_ROOT" diff --cached --quiet; then
      git -C "$DND_CAMPAIGN_ROOT" commit -q -m "${2:-play: turn update}"
      git -C "$DND_CAMPAIGN_ROOT" push origin HEAD || \
        echo "[git-sync] push failed (will retry next turn)." >&2
    fi
    ;;
  *)
    echo "usage: git-sync.sh {clone-or-pull|push [message]}" >&2
    exit 2
    ;;
esac
