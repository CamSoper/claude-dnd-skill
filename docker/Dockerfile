# Headless host image for the claude-dnd-skill game.
#
# Bundles: the Claude Code CLI (the headless "DM"), Python 3 + the display
# companion's deps, git (for the campaign store), and this repo itself as a LOCAL
# Claude Code plugin marketplace. At runtime docker/entrypoint.sh enables the
# `dm` plugin, clones/pulls the campaigns repo, starts the Flask display, and
# runs the per-turn driver (docker/dnd_loop.py).
#
# Built/published by .github/workflows/docker-publish.yml as
# ghcr.io/camsoper/claude-dnd; consumed by CamSoper/home-lab-iac (DndGame.cs).
#
# Auth is NOT baked in: mount a seeded ~/.claude (with .credentials.json from an
# interactive `claude /login`, subscription option) at runtime. See docker/README.md.
#
# NOTE: the import toolchain (pymupdf/pdftotext) is intentionally NOT installed --
# campaign authoring/import runs locally on your machine and is pushed to the
# campaigns git repo; the server only plays. See docker/README.md.
FROM node:22-bookworm-slim

# Python (display companion + helper scripts), git (campaign store), curl + certs.
# --break-system-packages: single-purpose container, no venv needed (PEP 668).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-pip git ca-certificates curl \
 && rm -rf /var/lib/apt/lists/* \
 && pip3 install --no-cache-dir --break-system-packages \
      flask flask-cors numpy

# Claude Code CLI (provides the `claude` binary).
RUN npm install -g @anthropic-ai/claude-code

# The repo doubles as a local plugin marketplace (.claude-plugin/marketplace.json,
# plugin "dm", source "./"). The Docker build context is the repo root, so this
# copies the whole repo (including docker/). Read-only at runtime.
COPY . /opt/claude-dnd-skill
RUN chmod +x /opt/claude-dnd-skill/docker/entrypoint.sh \
             /opt/claude-dnd-skill/docker/git-sync.sh \
             /opt/claude-dnd-skill/docker/dnd_loop.py

ENV HOME=/home/node \
    DND_CAMPAIGN_ROOT=/home/node/dnd

# Run unprivileged as the base image's `node` user (UID 1000) -- matches the
# bind-mount ownership documented in home-lab-iac DEPLOY.md ("claude-dnd game").
USER node
WORKDIR /home/node

ENTRYPOINT ["/opt/claude-dnd-skill/docker/entrypoint.sh"]
