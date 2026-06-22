#!/usr/bin/env python3
"""dnd_loop.py -- headless per-turn driver for the claude-dnd-skill game.

Model B: the Flask display server collects player moves from browsers into the
input queue; this loop blocks on that queue (reusing the skill's autorun_wait.py),
then runs ONE `claude -p` turn so the DM resolves the batch, narrates to the
display, and saves. One-shot per turn keeps Claude on the subscription (same as
home-lab-iac's ClaudeAgent) and bounds context. After each turn, play-state is
committed/pushed to the campaigns git repo.

VALIDATE IN YOUR ENVIRONMENT (can't be exercised without a live subscription):
  * Slash commands (/dm:dnd ...) do NOT run in `claude -p` (Claude Code limitation,
    anthropics/claude-code#837), so turns are driven by a natural-language system
    prompt that auto-invokes the enabled `dnd` skill. Tune SYSTEM_PROMPT against a
    real run if the skill doesn't pick up the load/play/save procedures cleanly.
  * autorun_wait.py expects the display server on localhost:5001 and the active
    campaign in <runtime>/.campaign (set below).
"""
import importlib.util
import os
import subprocess
import sys
import time

SKILL_REPO = os.environ.get("SKILL_REPO", "/opt/claude-dnd-skill")
SKILL = os.path.join(SKILL_REPO, "skills", "dnd")
DISPLAY = os.path.join(SKILL, "display")
SCRIPTS = os.path.join(SKILL, "scripts")
for _p in (DISPLAY, SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Reuse the skill's own resolvers so we agree with the display + autorun_wait.
from paths import campaigns_dir, find_campaign, runtime_dir  # type: ignore

RT = str(runtime_dir())
AUTORUN_WAIT = os.path.join(DISPLAY, "autorun_wait.py")
GIT_SYNC = os.path.join(SKILL_REPO, "docker", "git-sync.sh")
IDLE_RESCAN_SECS = 30

# Model the headless DM runs each turn. Overridable via DND_MODEL (set from the
# Pulumi config in home-lab-iac → the container env); defaults to Sonnet — fast
# and cheap enough for per-turn narration while staying on the subscription.
# Accepts a Claude Code alias ("sonnet", "opus", "haiku") or a full model id.
MODEL = os.environ.get("DND_MODEL", "").strip() or "sonnet"


def _load_sanitize():
    """Reuse wrapper.py._sanitize (structural [Name]: action validation + strip)."""
    try:
        spec = importlib.util.spec_from_file_location(
            "dnd_wrapper", os.path.join(DISPLAY, "wrapper.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # main() is guarded by __main__
        return mod._sanitize
    except Exception as e:  # pragma: no cover
        print(f"[dnd_loop] could not load wrapper._sanitize ({e}); passing moves through.",
              file=sys.stderr)
        return None


_sanitize = _load_sanitize()

SYSTEM_PROMPT = (
    "You are the headless Dungeon Master for an online D&D 5e game, using the 'dnd' "
    "skill (the 'dm' plugin). There is NO human DM -- you run the table.\n"
    "- The active campaign is '{campaign}', under $DND_CAMPAIGN_ROOT/campaigns/{campaign}/. "
    "Load/refresh its state from disk (state.md, world.md, npcs.md index, the current "
    "chapter's source, characters/) the way the skill's load procedure does.\n"
    "- Each user message is the party's submitted action(s) for ONE turn, one line per "
    "character as '[Name]: action'. Resolve exactly that turn: make any required rolls "
    "(scripts/dice.py, combat.py), then narrate to the PLAYERS by piping narration to "
    "display/send.py and pushing stat changes via display/push_stats.py -- the players "
    "watch the browser display, not this process's stdout.\n"
    "- Then SAVE per the skill's save procedure (update state.md live flags, append "
    "session-log.md, update character sheets).\n"
    "- Do NOT run autorun_wait.py and do NOT wait for further input; the driver owns the "
    "turn loop. Keep narration tight and end the turn after saving."
)


def active_campaign() -> str:
    name = os.environ.get("DND_CAMPAIGN", "").strip()
    if name:
        return name
    # Fall back to the most-recently-played campaign (state.md mtime).
    best, best_mt = "", -1.0
    try:
        for d in campaigns_dir().iterdir():
            sm = d / "state.md"
            if sm.exists() and sm.stat().st_mtime > best_mt:
                best, best_mt = d.name, sm.stat().st_mtime
    except FileNotFoundError:
        pass
    return best


def set_active(name: str) -> None:
    """autorun_wait.py + wrapper._sanitize read <runtime>/.campaign for the active game."""
    try:
        os.makedirs(RT, exist_ok=True)
        with open(os.path.join(RT, ".campaign"), "w") as f:
            f.write(name)
    except OSError:
        pass


def wait_for_moves() -> str:
    """Block (~9 min max) on the browser input queue; returns queued '[Name]: action' lines."""
    try:
        r = subprocess.run([sys.executable, AUTORUN_WAIT],
                           capture_output=True, text=True)
        return (r.stdout or "").strip()
    except Exception as e:
        print(f"[dnd_loop] autorun_wait failed: {e}", file=sys.stderr)
        time.sleep(5)
        return ""


def run_turn(campaign: str, moves: str) -> None:
    env = dict(os.environ)
    env.setdefault("CLAUDE_SKILL_DIR", SKILL)
    cmd = [
        "claude", "-p", moves,
        "--model", MODEL,
        "--append-system-prompt", SYSTEM_PROMPT.format(campaign=campaign),
        "--dangerously-skip-permissions",
    ]
    try:
        subprocess.run(cmd, cwd=str(find_campaign(campaign)), env=env, check=False)
    except FileNotFoundError:
        print("[dnd_loop] `claude` not found on PATH.", file=sys.stderr)
        time.sleep(5)


def git_push() -> None:
    if os.environ.get("DND_CAMPAIGNS_REPO"):
        subprocess.run(["bash", GIT_SYNC, "push", "play: turn update"], check=False)


def main() -> None:
    campaign = active_campaign()
    if campaign:
        set_active(campaign)
        print(f"[dnd_loop] Active campaign: {campaign}. Waiting for player moves...",
              file=sys.stderr)
    else:
        print("[dnd_loop] No campaign found under campaigns/. Author one and push to the "
              "campaigns repo (docker/README.md). Idling until one appears.", file=sys.stderr)

    while True:
        if not campaign:
            time.sleep(IDLE_RESCAN_SECS)
            campaign = active_campaign()
            if campaign:
                set_active(campaign)
                print(f"[dnd_loop] Campaign now available: {campaign}.", file=sys.stderr)
            continue

        moves = wait_for_moves()
        if not moves:
            continue  # idle/timeout -- loop keeps the display's countdown alive

        if _sanitize is not None:
            cleaned = _sanitize(moves)
            if not cleaned:
                continue  # malformed/blocked submission -- silent skip
            moves = cleaned

        run_turn(campaign, moves)
        git_push()


if __name__ == "__main__":
    main()
