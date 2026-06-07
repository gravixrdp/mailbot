#!/usr/bin/env bash
#
# auto_push.sh — watches the mailbot folder and automatically commits &
# pushes every change to GitHub. Run continuously (via mailbot-autopush.service).
#
# It watches recursively, ignores noise (.git, __pycache__, *.pyc), and
# debounces: after a change it waits QUIET_SECS of silence before pushing,
# so a burst of writes becomes a single commit.

set -uo pipefail

REPO_DIR="/home/ubuntu/mailbot"
BRANCH="main"
QUIET_SECS=8          # wait this many seconds of no changes before pushing
IGNORE_REGEX='(/\.git/|/__pycache__/|\.pyc$|/\.git$)'

cd "$REPO_DIR" || exit 1

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

do_push() {
    # Stage everything (respecting .gitignore) and only push when something changed.
    git add -A
    if git diff --cached --quiet; then
        return 0
    fi
    local msg
    msg="Auto-sync: $(date '+%Y-%m-%d %H:%M:%S')"
    if git commit -m "$msg" >/dev/null 2>&1; then
        if git push origin "$BRANCH" >/dev/null 2>&1; then
            log "Pushed changes to origin/$BRANCH"
        else
            log "Commit OK but push FAILED (will retry on next change)"
        fi
    fi
}

# Push anything that changed while the watcher was not running.
log "auto_push watcher starting for $REPO_DIR"
do_push

# Main loop: block on the next filesystem event, then drain a quiet window.
while true; do
    # Block until at least one relevant change occurs.
    inotifywait -r -q -e modify,create,delete,move \
        --exclude "$IGNORE_REGEX" "$REPO_DIR" >/dev/null 2>&1

    # Debounce: keep absorbing events until it's been quiet for QUIET_SECS.
    while inotifywait -r -q -t "$QUIET_SECS" -e modify,create,delete,move \
        --exclude "$IGNORE_REGEX" "$REPO_DIR" >/dev/null 2>&1; do
        :
    done

    do_push
done
