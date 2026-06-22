# Headless hosting (`docker/`)

Run the D&D game **headless** — a Claude Code "DM" plus the skill's Flask display
companion, in one container — so friends play from a browser with no human DM and
no laptop kept open. This bundle is what `CamSoper/home-lab-iac` deploys as the
`dnd-game` container behind Cloudflare Access at `https://dnd.soper.ninja`.

> **Status:** the C# infra (homelab container + Cloudflare tunnel/Access) is wired
> up, but the pieces below that need a live Claude **subscription** to exercise —
> plugin auto-load in `claude -p`, skill auto-invocation, and the exact per-turn
> prompt — must be validated in your environment. Search this file for **VALIDATE**.

## What's in here

| File | Purpose |
|------|---------|
| `Dockerfile` | Image: Claude Code CLI + Python display deps + git + this repo as a local plugin marketplace. Published as `ghcr.io/camsoper/claude-dnd`. |
| `entrypoint.sh` | Enable the `dm` plugin → sync the campaigns repo → start Flask (`--lan`) → exec the driver. |
| `dnd_loop.py` | The per-turn driver (the only net-new gameplay code). Blocks on the browser input queue, runs one `claude -p` turn, commits play-state. |
| `git-sync.sh` | Clone/pull the campaigns repo on start; commit+push play-state each turn. |
| `settings.json` | Enables the `dm` plugin from the local marketplace (installed into `~/.claude` at startup). |

## How a turn flows

```
browser (friend) ──/player-input──▶ Flask display (:5001) ──▶ .input_queue
                                                                   │
   dnd_loop.py  ◀── autorun_wait.py (blocks on the queue) ◀────────┘
        │  claude -p "<moves>" --append-system-prompt "<DM turn contract>"
        ▼
   Claude (dnd skill, DM) ── send.py/push_stats.py ──▶ Flask ──SSE──▶ browsers (+ Gemini TTS)
        │  saves state to disk → git-sync.sh push
```

Slash commands (`/dm:dnd …`) **don't run in `claude -p`** (Claude Code
[#837](https://github.com/anthropics/claude-code/issues/837)), so the driver uses a
natural-language system prompt that auto-invokes the enabled skill. **VALIDATE** the
prompt in `dnd_loop.py` (`SYSTEM_PROMPT`) against a real run and tune as needed.

## Build / publish

`.github/workflows/docker-publish.yml` builds and pushes `ghcr.io/camsoper/claude-dnd:latest`
on push to `main` (and tags), or via **workflow_dispatch**. The image must exist
before `home-lab-iac` runs `pulumi up`.

Local build for testing:

```bash
docker build -f docker/Dockerfile -t ghcr.io/camsoper/claude-dnd:dev .
```

## Run / seed (standalone, for testing)

The homelab path is documented in `home-lab-iac/DEPLOY.md` ("claude-dnd game").
To exercise the image directly:

```bash
# 1. Seed the subscription credential into an auth dir (choose the subscription
#    option, NOT an API key, when prompted):
docker run -it --rm -v "$PWD/auth:/home/node/.claude" \
  ghcr.io/camsoper/claude-dnd:dev claude /login

# 2. Run the game. (Behind Cloudflare it's http on the tunnel; locally, map 5001.)
docker run --rm -p 5001:5001 \
  -v "$PWD/auth:/home/node/.claude" \
  -v "$PWD/campaigns:/home/node/dnd" \
  -e DND_TTS_KEY=<gemini-key> \
  -e DND_CAMPAIGNS_REPO=https://github.com/camsoper/dnd-campaigns.git \
  -e GITHUB_TOKEN=<scoped-pat> \
  -e DND_CAMPAIGN=<campaign-name> \
  ghcr.io/camsoper/claude-dnd:dev

# Verify the plugin loaded (VALIDATE):
docker run --rm -v "$PWD/auth:/home/node/.claude" \
  ghcr.io/camsoper/claude-dnd:dev claude plugin list
```

### Environment

| Var | Meaning |
|-----|---------|
| `DND_CAMPAIGN_ROOT` | Campaign git working tree (default `/home/node/dnd`). |
| `DND_CAMPAIGNS_REPO` | https remote of the private campaigns repo. |
| `GITHUB_TOKEN` | Scoped PAT/deploy token for clone/pull/push. |
| `DND_TTS_KEY` | Gemini Flash TTS key (narration audio). Optional → text-only. |
| `DND_CAMPAIGN` | Campaign the driver loads (default: most-recently-played). |
| `DND_MODEL` | Model the DM runs each turn — alias (`sonnet`/`opus`/`haiku`) or full id. Default `sonnet`. Set from the Pulumi config in home-lab-iac. |
| `ANTHROPIC_API_KEY` | **Optional.** Set to bill at API rates instead of the subscription. **Do NOT** set `CLAUDE_CODE_OAUTH_TOKEN`. |

## Authoring campaigns (you, locally — not on the server)

You're the sole author; friends only play. Author with Claude Code on your machine
against a clone of the campaigns repo, then push — the container pulls it:

```bash
git clone https://github.com/camsoper/dnd-campaigns.git && cd dnd-campaigns
# In Claude Code with this skill installed:
#   /dm:dnd new my-campaign            (improvise a world)
#   /dm:dnd import my-campaign book.md (import a module you have the right to use)
git add -A && git commit -m "add my-campaign" && git push
```

Keep `.runtime/` in the repo's `.gitignore` (the display writes per-session
tokens/queues there). The server image deliberately omits the PDF import toolchain
— import runs locally.

### Maps & images

Import is **text-only**. A markdown `![alt](path.png)` contributes only its **alt
text** (the pixels are dropped); PDF import skips images entirely. So:

- For a map to be *usable by the DM*, describe its layout in **prose** during
  authoring (rooms, exits, keyed areas, distances). Claude Code can open an image
  locally and help you write that description — then the DM reasons over the text.
- Write rich **alt text** on any image references; that text imports and gives the
  DM useful labels/captions for free.
- Showing battlemaps to players, or DM vision over the image at play time, are
  possible extensions but are not wired up here.

Only feed content you have the right to use (your own prep, SRD-based, or
openly-licensed adventures).
