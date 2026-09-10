#!/bin/bash
#
# Manage a local install of the Military Personal Finance.
#
#   ./roth.sh update    pull the latest from GitHub, refresh deps, restart
#   ./roth.sh start     start the app in the background
#   ./roth.sh stop      stop it
#   ./roth.sh restart   stop, then start
#   ./roth.sh status    is it running, on what port, at what commit
#   ./roth.sh test      run the test suite
#   ./roth.sh push "message"
#                       commit and push your local changes to GitHub
#
# Your saved plans live in saved_plans/ and are git-ignored, so nothing here
# ever touches them.
#
# Written for macOS: bash 3.2 compatible, no GNU-only flags.

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENTRY="Military_Finance.py"
PORT="${ROTH_PORT:-8501}"
VENV="$APP_DIR/.venv"
PY="$VENV/bin/python3"
PIDFILE="$APP_DIR/.streamlit-run.pid"
LOG="$APP_DIR/.streamlit-run.log"

say()  { printf '\033[1;36m==>\033[0m %s\n' "$1"; }
ok()   { printf '\033[1;32m  ✓\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33m  !\033[0m %s\n' "$1"; }
die()  { printf '\033[1;31mError:\033[0m %s\n' "$1" >&2; exit 1; }

# --------------------------------------------------------------------------

ensure_python() {
    command -v python3 >/dev/null 2>&1 || die "python3 is not installed.
       Run:  xcode-select --install"
    if [ ! -x "$PY" ]; then
        say "Creating the virtual environment"
        [ -d "$VENV" ] && rm -rf "$VENV"
        python3 -m venv "$VENV" || die "Could not create a virtual environment."
        "$PY" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
        ok "Created"
    fi
}

# A virtual environment can exist while being empty -- a fresh venv, or one
# left half-built by an interrupted install. Anything that launches the app
# must confirm streamlit is actually in there, not just that the venv exists.
ensure_env() {
    ensure_python
    if [ ! -x "$VENV/bin/streamlit" ]; then
        install_deps
    fi
}

install_deps() {
    say "Installing dependencies"
    "$PY" -m pip install --quiet --upgrade -r "$APP_DIR/requirements.txt" \
        || die "Dependency install failed. Check your network and retry."
    ok "Dependencies up to date"
}

running_pid() {
    if [ -f "$PIDFILE" ]; then
        pid="$(cat "$PIDFILE" 2>/dev/null || true)"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "$pid"; return 0
        fi
    fi
    # Fall back to whatever is holding the port.
    lsof -ti tcp:"$PORT" 2>/dev/null | head -1
}

port_holders() {
    lsof -ti tcp:"$PORT" 2>/dev/null || true
}

do_stop() {
    pid="$(running_pid || true)"
    if [ -z "$pid" ]; then
        ok "Not running"
        rm -f "$PIDFILE"
        return 0
    fi
    say "Stopping (pid $pid)"

    # Streamlit forks, so the recorded pid is not necessarily the process
    # holding the port. Killing it alone leaves an orphan bound to the port and
    # the next start silently attaches to the stale server. The port is the
    # real resource, so keep going until nothing holds it.
    kill "$pid" 2>/dev/null || true

    n=0
    while [ "$n" -lt 24 ]; do
        holders="$(port_holders)"
        [ -z "$holders" ] && break
        if [ "$n" -eq 8 ]; then
            for h in $holders; do kill "$h" 2>/dev/null || true; done
        elif [ "$n" -eq 16 ]; then
            for h in $holders; do kill -9 "$h" 2>/dev/null || true; done
        fi
        sleep 0.5; n=$((n + 1))
    done

    rm -f "$PIDFILE"
    if [ -n "$(port_holders)" ]; then
        die "Something is still holding port $PORT. Find it with:
       lsof -i tcp:$PORT"
    fi
    ok "Stopped"
}

do_start() {
    ensure_env
    [ -f "$APP_DIR/$ENTRY" ] || die "$ENTRY not found in $APP_DIR"

    pid="$(running_pid || true)"
    if [ -n "$pid" ]; then
        warn "Already running on port $PORT (pid $pid). Use restart."
        return 0
    fi

    say "Starting on port $PORT"
    # Detach all three streams. Without "< /dev/null" and the subshell's own
    # redirect, the background server inherits this script's stdout -- so
    # "./roth.sh update | tail" would hang forever waiting for a pipe that the
    # server holds open for as long as it runs.
    ( cd "$APP_DIR" && nohup "$VENV/bin/streamlit" run "$ENTRY" \
        --server.port "$PORT" --server.headless true \
        > "$LOG" 2>&1 < /dev/null & echo $! > "$PIDFILE" ) > /dev/null 2>&1

    n=0
    while [ "$n" -lt 40 ]; do
        if curl -s -o /dev/null "http://127.0.0.1:$PORT/" 2>/dev/null; then
            ok "Running at http://localhost:$PORT"
            command -v open >/dev/null 2>&1 && open "http://localhost:$PORT" || true
            return 0
        fi
        sleep 0.5; n=$((n + 1))
    done
    rm -f "$PIDFILE"
    printf '\033[1;31mError:\033[0m the app did not start. Last lines of the log:\n' >&2
    tail -15 "$LOG" 2>/dev/null | sed 's/^/    /' >&2
    exit 1
}

do_update() {
    cd "$APP_DIR"
    [ -d .git ] || die "$APP_DIR is not a git clone. Re-clone it:
       git clone https://github.com/quesohusker/military-personal-finance.git"

    branch="$(git rev-parse --abbrev-ref HEAD)"
    say "Updating from GitHub (branch: $branch)"

    if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
        die "You have uncommitted changes. Commit them first:
       ./roth.sh push \"what you changed\"
       ...or discard them:  git checkout -- ."
    fi

    before="$(git rev-parse HEAD)"
    git pull --ff-only origin "$branch" || die "Pull failed -- git's reason is printed just above.
       The usual causes are local commits you have not pushed, or untracked
       files that the update would overwrite. To see the state:
         git status
       To throw away local work and take GitHub's version outright:
         git fetch origin $branch && git reset --hard origin/$branch"
    after="$(git rev-parse HEAD)"

    if [ "$before" = "$after" ]; then
        ok "Already up to date ($(git log -1 --format='%h %s'))"
    else
        ok "Updated to $(git log -1 --format='%h %s')"
        echo
        git log --oneline "$before..$after" | sed 's/^/    /'
        echo
    fi

    if [ "$branch" != "main" ]; then
        warn "You are on '$branch', not main. To follow the released version:"
        warn "  git checkout main && ./roth.sh update"
    fi

    ensure_python
    install_deps
    do_test_quiet
    do_stop
    do_start
}

do_test_quiet() {
    say "Running tests"
    if ( cd "$APP_DIR" && "$PY" -m pytest tests/ -q >/dev/null 2>&1 ); then
        ok "All tests pass"
    else
        warn "Some tests fail. The app will still run, but treat its numbers"
        warn "with suspicion. To see the failures:"
        warn "  cd $APP_DIR && .venv/bin/python3 -m pytest tests/ -q"
    fi
}

do_status() {
    cd "$APP_DIR"
    pid="$(running_pid || true)"
    if [ -n "$pid" ]; then
        ok "Running on http://localhost:$PORT (pid $pid)"
    else
        warn "Not running"
    fi
    if [ -d .git ]; then
        echo "    Branch:  $(git rev-parse --abbrev-ref HEAD)"
        echo "    Commit:  $(git log -1 --format='%h %s (%cr)')"
        git fetch -q origin 2>/dev/null || true
        branch="$(git rev-parse --abbrev-ref HEAD)"
        if git rev-parse --verify -q "origin/$branch" >/dev/null; then
            behind="$(git rev-list --count "HEAD..origin/$branch" 2>/dev/null || echo 0)"
            if [ "$behind" -gt 0 ]; then
                warn "$behind new commit(s) on GitHub. Run: ./roth.sh update"
            else
                ok "Up to date with GitHub"
            fi
        fi
    fi
    if [ -d saved_plans ]; then
        echo "    Plans:   $(ls -1 saved_plans 2>/dev/null | wc -l | tr -d ' ') saved"
    fi
}

do_push() {
    cd "$APP_DIR"
    msg="${1:-}"
    [ -n "$msg" ] || die "Give a commit message:  ./roth.sh push \"what you changed\""

    if [ -z "$(git status --porcelain)" ]; then
        ok "Nothing to commit"
        return 0
    fi

    say "Changes to be pushed"
    git status --short | sed 's/^/    /'
    echo
    printf 'Commit and push these? [y/N] '
    read -r reply || reply="n"
    case "$reply" in
        [Yy]*) ;;
        *) ok "Cancelled"; return 0 ;;
    esac

    git add -A
    git commit -q -m "$msg"
    branch="$(git rev-parse --abbrev-ref HEAD)"
    git push origin "$branch"
    ok "Pushed to origin/$branch"
    echo
    echo "    If this repo is deployed on Streamlit Community Cloud, it will"
    echo "    redeploy on its own within a minute or two. If it does not, open"
    echo "    share.streamlit.io, find the app, and use Manage app → Reboot."
}

# --------------------------------------------------------------------------

case "${1:-}" in
    update)  do_update ;;
    start)   do_start ;;
    stop)    do_stop ;;
    restart) do_stop; do_start ;;
    status)  do_status ;;
    test)    ensure_env; do_test_quiet ;;
    push)    shift; do_push "${1:-}" ;;
    logs)    tail -40 "$LOG" 2>/dev/null || warn "No log yet." ;;
    ""|help|-h|--help)
        awk 'NR>2 { if ($0 !~ /^#/) exit; sub(/^# ?/, ""); print }' "${BASH_SOURCE[0]}"
        ;;
    *) die "Unknown command: $1  (run ./roth.sh help)" ;;
esac
