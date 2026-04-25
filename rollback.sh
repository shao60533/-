#!/bin/bash
# ============================================================================
# rollback.sh — Interactive rollback to any Claude session checkpoint.
#
# Lists every git anchor created by Claude hooks (claude-start-*, claude-wip-*,
# safe-*) plus recent commits, and lets you pick one to reset to.
#
# Safe by default:
#   - Always shows a diff preview of what would change
#   - Creates a "claude-rollback-undo-<TS>" tag at current HEAD before reset,
#     so even the rollback itself is undoable
#   - Asks for typed confirmation ("yes")
#
# Usage:  ./rollback.sh                — interactive picker
#         ./rollback.sh --list          — list anchors and exit
#         ./rollback.sh <tag-or-commit> — non-interactive (still asks confirm)
# ============================================================================

set -e

cd "$(dirname "$0")"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "✗ Not in a git repo"
    exit 1
fi

YELLOW='\033[33m'
GREEN='\033[32m'
RED='\033[31m'
CYAN='\033[36m'
GRAY='\033[90m'
NC='\033[0m'

# ── Collect candidates ─────────────────────────────────────────────────────

list_anchors() {
    echo -e "${CYAN}== Permanent safety baselines ==${NC}"
    git for-each-ref --sort=-creatordate \
        --format='%(refname:short)|%(creatordate:short) %(creatordate:format:%H:%M)|%(subject)' \
        refs/tags/safe-* 2>/dev/null | head -10 \
        | awk -F'|' '{printf "  %-40s  %s  %s\n", $1, $2, $3}'

    echo
    echo -e "${CYAN}== Session-start anchors (created by hook) ==${NC}"
    git for-each-ref --sort=-creatordate \
        --format='%(refname:short)|%(creatordate:short) %(creatordate:format:%H:%M)|%(subject)' \
        refs/tags/claude-start-* 2>/dev/null | head -15 \
        | awk -F'|' '{printf "  %-40s  %s  %s\n", $1, $2, $3}'

    echo
    echo -e "${CYAN}== Session-end WIP snapshots ==${NC}"
    git for-each-ref --sort=-creatordate \
        --format='%(refname:short)|%(creatordate:short) %(creatordate:format:%H:%M)|%(subject)' \
        refs/tags/claude-wip-* 2>/dev/null | head -10 \
        | awk -F'|' '{printf "  %-40s  %s  %s\n", $1, $2, $3}'

    echo
    echo -e "${CYAN}== Recent commits ==${NC}"
    git log --oneline -10
}

if [ "$1" = "--list" ]; then
    list_anchors
    exit 0
fi

# ── Pick target ─────────────────────────────────────────────────────────────

TARGET="$1"
if [ -z "$TARGET" ]; then
    list_anchors
    echo
    echo -e "${YELLOW}Paste the tag or commit SHA you want to rewind to (Enter to cancel):${NC}"
    read -r TARGET
    [ -z "$TARGET" ] && { echo "Cancelled."; exit 0; }
fi

# Validate
if ! git rev-parse --verify "$TARGET" >/dev/null 2>&1; then
    echo -e "${RED}✗ '$TARGET' is not a valid tag/commit${NC}"
    exit 1
fi

TARGET_SHA=$(git rev-parse "$TARGET")
CURRENT_SHA=$(git rev-parse HEAD)

if [ "$TARGET_SHA" = "$CURRENT_SHA" ]; then
    echo -e "${YELLOW}HEAD is already at $TARGET. Nothing to do.${NC}"
    exit 0
fi

# ── Show diff preview ──────────────────────────────────────────────────────

echo
echo -e "${CYAN}== Change preview (HEAD → $TARGET) ==${NC}"
git diff --stat "$TARGET" HEAD | tail -25
COUNT=$(git diff --name-only "$TARGET" HEAD | wc -l | tr -d ' ')
echo
echo -e "${YELLOW}This rollback will affect ${COUNT} file(s).${NC}"

# ── Show files newer than target that are about to be lost ────────────────

UNCOMMITTED=$(git status --porcelain | wc -l | tr -d ' ')
if [ "$UNCOMMITTED" -gt 0 ]; then
    echo -e "${RED}⚠ You have $UNCOMMITTED uncommitted change(s). They will be DESTROYED.${NC}"
fi

# ── Safety net: tag current HEAD ───────────────────────────────────────────

UNDO_TS=$(date +%Y-%m-%d-%H%M%S)
UNDO_TAG="claude-rollback-undo-${UNDO_TS}"

echo
echo -e "${GREEN}A safety tag '${UNDO_TAG}' will be created at the current HEAD${NC}"
echo -e "${GREEN}so you can run \"git reset --hard ${UNDO_TAG}\" to undo this rollback.${NC}"

echo
echo -e "${RED}Type 'yes' to perform the rollback, anything else to cancel:${NC}"
read -r CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Cancelled."
    exit 0
fi

# ── Do it ──────────────────────────────────────────────────────────────────

git tag "$UNDO_TAG" -m "Pre-rollback HEAD anchor (rollback target was $TARGET)"

# If there are uncommitted changes, snapshot them too so they're recoverable
if [ "$UNCOMMITTED" -gt 0 ]; then
    git add -A
    git -c user.name="Claude Auto" \
        -c user.email="claude-auto@noreply.anthropic.com" \
        commit -m "wip: pre-rollback snapshot ${UNDO_TS}" --no-verify >/dev/null
    git tag "claude-rollback-undo-${UNDO_TS}-wip"
    echo "  💾 Snapshotted uncommitted changes as claude-rollback-undo-${UNDO_TS}-wip"
fi

git reset --hard "$TARGET"

echo
echo -e "${GREEN}✓ Rolled back to $TARGET${NC}"
echo -e "${GRAY}  Undo this rollback:  git reset --hard ${UNDO_TAG}${NC}"
echo -e "${GRAY}  See all anchors:     ./rollback.sh --list${NC}"
