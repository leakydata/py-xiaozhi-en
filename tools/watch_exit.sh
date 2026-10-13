#!/usr/bin/env bash
# Wait for py-xiaozhi to start, attach gdb, and record what ends it.
#
# For the silent exits: no traceback, no signal, no core dump, nothing on the
# terminal - native code calling _exit()/exit(). Breakpoints on those cost
# nothing until hit; when one is, the C stack of every thread is written out,
# naming the library responsible. Attaching freezes the app for a moment while
# gdb reads its libraries, which is why this attaches right as it starts up.
#
# Usage: sudo tools/watch_exit.sh [pattern] [output]
# The pattern is anchored at the start of the command line, so it matches the
# interpreter itself and never a shell whose command text merely mentions it.
PATTERN="${1:-^[^ ]*/\.venv/bin/python3? main\.py}"
OUT="${2:-/home/scholyx/.local/share/py-xiaozhi/logs/exit-gdb.txt}"
CMDS=$(mktemp)
cat > "$CMDS" <<'GDB'
set pagination off
set confirm off
set print thread-events off
handle all nostop noprint pass
break _exit
commands
  silent
  printf "\n========== _exit(%d) called ==========\n", $rdi
  printf "--- the thread that called it ---\n"
  bt 50
  printf "\n--- every thread ---\n"
  thread apply all bt 15
  continue
end
break abort
commands
  silent
  printf "\n========== abort() called ==========\n"
  bt 50
  continue
end
continue
GDB
echo "waiting for a process matching: $PATTERN"
until pid=$(pgrep -f -n "$PATTERN"); do sleep 0.5; done
{
  echo "=== $(date '+%F %T') attaching to pid $pid: $(tr '\0' ' ' < /proc/$pid/cmdline)"
  gdb -nx -batch -p "$pid" -x "$CMDS" 2>&1 | grep -vE "^\[New Thread|^\[Thread .* exited|^Reading symbols|^Downloading"
  echo "=== $(date '+%F %T') pid $pid is gone"
} >> "$OUT"
rm -f "$CMDS"
echo "recorded to $OUT"
