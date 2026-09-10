#!/usr/bin/env bash
#
# Fetch the published figures this app hard-codes, from the agencies that own
# them, and bundle the result to send back.
#
# The app was built in a container with no route to any .gov or .mil host, so
# every rate in it -- Part B and IRMAA, the EITC table, VA funding fees, SSA
# bend points, the mortality table, TRICARE costs -- was written from
# recollection and marked VERIFY. This runs somewhere with real network access
# and replaces recollection with the source.
#
# RUN IT
#     bash fetch.sh                 everything, then bundle it
#     bash fetch.sh --list          what it would fetch, and why
#     bash fetch.sh irs ssa         just those categories
#
# Categories: ssa medicare irs dod va tricare housing
#
# It needs nothing but python3, which macOS already has. No pip, no key.

set -uo pipefail

REPO_URL="https://github.com/quesohusker/Military-Personal-Finance.git"
RAW_URL="https://raw.githubusercontent.com/quesohusker/Military-Personal-Finance/main/scripts/fetch_gov_data.py"

bold=$(tput bold 2>/dev/null || true); dim=$(tput dim 2>/dev/null || true)
red=$(tput setaf 1 2>/dev/null || true); grn=$(tput setaf 2 2>/dev/null || true)
off=$(tput sgr0 2>/dev/null || true)

say()  { printf '%s\n' "$*"; }
head1(){ printf '\n%s%s%s\n' "$bold" "$*" "$off"; }
warn() { printf '%s%s%s\n' "$red" "$*" "$off"; }
good() { printf '%s%s%s\n' "$grn" "$*" "$off"; }

# ---------------------------------------------------------------- python ----
PY=""
for c in python3 python3.12 python3.11 python3.10 python3.9 python; do
    if command -v "$c" >/dev/null 2>&1; then
        v=$("$c" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null) || continue
        maj=${v%%.*}; min=${v##*.}
        if [ "${maj:-0}" -eq 3 ] && [ "${min:-0}" -ge 9 ]; then PY="$c"; break; fi
    fi
done
if [ -z "$PY" ]; then
    warn "No python3 3.9 or newer found."
    say  "On macOS, either install the Xcode command line tools:"
    say  "    xcode-select --install"
    say  "or install Python from https://www.python.org/downloads/"
    exit 1
fi

# ------------------------------------------------------------ where we are --
# Run from inside a clone if there is one, because the parsers install straight
# into data/ and the importers are there. Otherwise fetch the one script and
# work standalone -- the archive is the part that matters either way.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STANDALONE=0

if [ -f "$HERE/fetch_gov_data.py" ] && [ -f "$HERE/../engine/mortality.py" ]; then
    ROOT="$(cd "$HERE/.." && pwd)"
    SCRIPT="$HERE/fetch_gov_data.py"
elif [ -d "$HOME/military-personal-finance/.git" ]; then
    ROOT="$HOME/military-personal-finance"
    SCRIPT="$ROOT/scripts/fetch_gov_data.py"
    head1 "Using the clone at $ROOT"
    git -C "$ROOT" pull --ff-only 2>&1 | tail -2 || warn "Could not pull; using what is on disk."
else
    head1 "No clone found. Fetching the script on its own."
    ROOT="$(pwd)/gov-data-$(date +%Y%m%d)"
    mkdir -p "$ROOT/scripts"
    SCRIPT="$ROOT/scripts/fetch_gov_data.py"
    if ! curl -fsSL "$RAW_URL" -o "$SCRIPT"; then
        warn "Could not download the script from GitHub."
        say  "Clone the repo instead and run scripts/fetch.sh from inside it:"
        say  "    git clone $REPO_URL"
        exit 1
    fi
    STANDALONE=1
    say "Working in $ROOT"
    say "${dim}Standalone: the raw archive still gets built, but the life table"
    say "cannot be installed without the repo. That is fine -- send the zip.${off}"
fi

# ------------------------------------------------------------------- args ---
ARGS=()
BUNDLE=1
for a in "$@"; do
    case "$a" in
        --list|-l) ARGS+=("--list"); BUNDLE=0 ;;
        --no-zip)  BUNDLE=0 ;;
        -h|--help) sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        --*)       ARGS+=("$a") ;;
        *)         ONLY="${ONLY:-}${ONLY:+,}$a" ;;
    esac
done
[ -n "${ONLY:-}" ] && ARGS+=("--only" "$ONLY")
[ "$BUNDLE" -eq 1 ] && ARGS+=("--zip")

# -------------------------------------------------------------------- run ---
head1 "Fetching from SSA, CMS, IRS, DFAS, DTMO, TSP, VA, TRICARE and FHFA"
say "${dim}One request per source, a real browser User-Agent, a pause between"
say "hosts. A 403 is bot filtering, not a missing page -- the script says so"
say "and names the file to save by hand.${off}"
say ""

cd "$ROOT" || exit 1
"$PY" "$SCRIPT" "${ARGS[@]}"
STATUS=$?

[ "$BUNDLE" -eq 0 ] && exit $STATUS

# ------------------------------------------------------------- what next ----
ZIP="$(ls -t "$ROOT"/data/_gov_raw/*.zip 2>/dev/null | head -1)"

head1 "What to do with this"
if [ -n "$ZIP" ] && [ -f "$ZIP" ]; then
    good "Bundle: $ZIP"
    say  "$(cd "$(dirname "$ZIP")" && du -h "$(basename "$ZIP")" | cut -f1) on disk."
    say  ""
    say  "Send that zip back to Claude. Every raw response is in it with a"
    say  "SHA-256 and a manifest, so the figures can be read out of it even"
    say  "where the parser could not."
    if command -v open >/dev/null 2>&1; then
        open -R "$ZIP" 2>/dev/null && say "" && say "${dim}Revealed in Finder.${off}"
    fi
else
    warn "No bundle was written -- nothing fetched successfully."
    say  "Check the network, then try one category to see the error:"
    say  "    bash fetch.sh ssa"
fi

if [ "$STANDALONE" -eq 0 ]; then
    say ""
    say "Anything the script installed is now in data/. To commit it:"
    say "    cd $ROOT && git status"
fi

exit $STATUS
