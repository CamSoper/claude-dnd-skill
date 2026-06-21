#!/usr/bin/env bash
# Entrypoint for the claude-dnd headless game host. See docker/README.md.
#
# Order: enable the dnd plugin -> sanity-check auth -> sync the campaigns git
# repo -> start the Flask display (LAN/HTTP) -> exec the per-turn driver.
set -uo pipefail

SKILL_REPO=/opt/claude-dnd-skill
DISPLAY_DIR="$SKILL_REPO/skills/dnd/display"
CLAUDE_DIR="$HOME/.claude"
: "${DND_CAMPAIGN_ROOT:=/home/node/dnd}"
export DND_CAMPAIGN_ROOT CLAUDE_SKILL_DIR="$SKILL_REPO/skills/dnd"

mkdir -p "$CLAUDE_DIR" "$DND_CAMPAIGN_ROOT"

# --- 1. Enable the dnd plugin (non-interactively) ---------------------------
# settings.json points Claude Code at this repo as a local plugin marketplace and
# enables the `dm` plugin. It is written into the (bind-mounted) ~/.claude at
# startup, because that dir is the auth volume and would otherwise shadow anything
# baked into the image. The `claude plugin` CLI calls are a belt-and-suspenders
# fallback in case the settings schema differs across Claude Code versions.
if [ ! -f "$CLAUDE_DIR/settings.json" ]; then
  cp "$SKILL_REPO/docker/settings.json" "$CLAUDE_DIR/settings.json"
fi
claude plugin marketplace add "$SKILL_REPO" >/dev/null 2>&1 || true
claude plugin install dm@neural-initiative >/dev/null 2>&1 || true

# --- 2. Auth sanity check ---------------------------------------------------
if [ ! -f "$CLAUDE_DIR/.credentials.json" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "[entrypoint] WARNING: no ~/.claude/.credentials.json and no ANTHROPIC_API_KEY set." >&2
  echo "[entrypoint] Seed the subscription credential (docker/README.md) or turns will fail." >&2
fi

# --- 3. Campaign store (git) ------------------------------------------------
if [ -n "${DND_CAMPAIGNS_REPO:-}" ]; then
  bash "$SKILL_REPO/docker/git-sync.sh" clone-or-pull \
    || echo "[entrypoint] WARNING: campaign repo sync failed; using whatever is on the volume." >&2
fi

# --- 4. Flask display companion (HTTP on 0.0.0.0:5001; CF terminates TLS) ----
# --lan binds 0.0.0.0 so the cloudflared tunnel reaches it as http://dnd-game:5001.
# Never --tls behind the tunnel.
bash "$DISPLAY_DIR/start-display.sh" --lan \
  || echo "[entrypoint] WARNING: display server did not start cleanly." >&2

# --- 5. Per-turn driver (foreground; PID1 init provided by docker --init) -----
exec python3 "$SKILL_REPO/docker/dnd_loop.py"
