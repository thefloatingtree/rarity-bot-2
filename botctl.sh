#!/usr/bin/env bash
#
# botctl — manage the discord bot systemd service
#
# Usage:  ./botctl.sh <command>
#
#   start      start the service
#   stop       stop the service
#   restart    restart the service
#   status     show current status
#   logs       follow live logs (Ctrl-C to exit)
#   deploy     pull latest code, (re)install deps, restart, verify
#   enable     start on boot
#   disable    don't start on boot
#   reset      clear a failed/crash-loop state (reset-failed)
#
# Edit the CONFIG block below to match your setup.

set -euo pipefail

# ----------------------------- CONFIG ---------------------------------
SERVICE="discordbot"                         # systemd unit name (no .service)
APP_DIR="/home/thefloatingtree/rarity-bot-2"   # where the bot code lives
PYTHON="/usr/bin/python3"                     # interpreter used to install deps
REQUIREMENTS="requirements.txt"               # relative to APP_DIR; skipped if absent
BRANCH="master"                                 # git branch to deploy
# ----------------------------------------------------------------------

# Use sudo for systemctl only if we're not already root.
if [[ $EUID -eq 0 ]]; then SUDO=""; else SUDO="sudo"; fi

# Colored status output
info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
err()   { printf '\033[1;31m==>\033[0m %s\n' "$*" >&2; }

# Confirm the service actually reached 'active' after a (re)start, instead of
# quietly dropping back into the restart loop.
verify_up() {
    info "Waiting for ${SERVICE} to settle..."
    sleep 3
    if $SUDO systemctl is-active --quiet "$SERVICE"; then
        ok "${SERVICE} is active."
        $SUDO systemctl status "$SERVICE" --no-pager --lines=0 || true
    else
        err "${SERVICE} is NOT active. Recent logs:"
        $SUDO journalctl -u "$SERVICE" --no-pager --lines=25
        return 1
    fi
}

cmd="${1:-}"

case "$cmd" in
    start)
        info "Starting ${SERVICE}..."
        $SUDO systemctl start "$SERVICE"
        verify_up
        ;;

    stop)
        info "Stopping ${SERVICE}..."
        $SUDO systemctl stop "$SERVICE"
        ok "Stopped."
        ;;

    restart)
        info "Restarting ${SERVICE}..."
        $SUDO systemctl restart "$SERVICE"
        verify_up
        ;;

    status)
        $SUDO systemctl status "$SERVICE" --no-pager
        ;;

    logs)
        info "Following logs for ${SERVICE} (Ctrl-C to quit)..."
        $SUDO journalctl -u "$SERVICE" -f
        ;;

    deploy)
        info "Deploying latest code from ${BRANCH}..."
        cd "$APP_DIR"

        # Pull latest. Fails loudly if there are uncommitted local changes.
        if [[ -d .git ]]; then
            git fetch origin "$BRANCH"
            git checkout "$BRANCH"
            git pull --ff-only origin "$BRANCH"
        else
            err "No .git directory in ${APP_DIR}; skipping git pull."
        fi

        # (Re)install dependencies if a requirements file is present.
        if [[ -f "$REQUIREMENTS" ]]; then
            info "Installing dependencies from ${REQUIREMENTS}..."
            "$PYTHON" -m pip install --user -r "$REQUIREMENTS"
        else
            info "No ${REQUIREMENTS} found; skipping dependency install."
        fi

        info "Restarting to pick up new code..."
        $SUDO systemctl restart "$SERVICE"
        verify_up
        ;;

    enable)
        $SUDO systemctl enable "$SERVICE"
        ok "${SERVICE} will start on boot."
        ;;

    disable)
        $SUDO systemctl disable "$SERVICE"
        ok "${SERVICE} will NOT start on boot."
        ;;

    reset)
        info "Clearing failed state for ${SERVICE}..."
        $SUDO systemctl reset-failed "$SERVICE"
        ok "Restart counter cleared. Use '$0 start' to try again."
        ;;

    *)
        # Print the usage header from this file's own comments.
        sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'
        exit 1
        ;;
esac