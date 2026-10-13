#!/usr/bin/env bash
# Run py-xiaozhi exactly as usual, but record what ends the process.
#
# The app has twice vanished mid-reply with no traceback, no signal, no core
# dump and nothing on the terminal - the signature of native code calling
# exit()/_exit() directly. strace watches only the calls that end a process or
# send a signal (seccomp keeps the overhead negligible) and records the C call
# stack of each, so the library responsible is named in:
#
#     ~/.local/share/py-xiaozhi/logs/exit-trace.txt
#
# Usage: ./run_traced.sh            (any main.py arguments pass through)
set -u
LOG_DIR="${XIAOZHI_LOG_DIR:-$HOME/.local/share/py-xiaozhi/logs}"
mkdir -p "$LOG_DIR"
TRACE="$LOG_DIR/exit-trace.txt"
cd "$(dirname "$0")"
echo "=== $(date '+%F %T') started" >> "$TRACE"
strace -f --seccomp-bpf -k -tt \
  -e trace=exit_group,kill,tgkill,tkill \
  -o "$TRACE.tmp" \
  uv run python main.py "$@"
code=$?
# Keep only what matters: the process-ending calls and the stacks under them.
cat "$TRACE.tmp" >> "$TRACE" && rm -f "$TRACE.tmp"
echo "=== $(date '+%F %T') ended with exit code $code" >> "$TRACE"
echo "py-xiaozhi ended with exit code $code (details: $TRACE)"
exit $code
