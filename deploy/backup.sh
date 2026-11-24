#!/bin/sh
# Database backups: a pg_dump every BACKUP_INTERVAL_HOURS (default 24), aligned to
# BACKUP_HOUR, kept for KEEP_DAYS days.
#
# Crash-safe: on start it checks the newest dump, and if one is overdue (the server was
# off when it should have run) it makes one right away. Dumps are written to a temp
# file, checked with gzip -t and only then renamed, so a crash mid-dump never leaves a
# truncated file that looks like a backup. status.json records the last result for
# monitoring and off-site copy scripts.
set -eu
umask 077
INTERVAL_H=${BACKUP_INTERVAL_HOURS:-24}
INTERVAL=$((INTERVAL_H * 3600))
DIR=/backups

status() { # $1 = ok|failed, $2 = file or message
  printf '{"result":"%s","at":"%s","detail":"%s"}\n' "$1" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$2" > "$DIR/status.json.tmp"
  chmod 644 "$DIR/status.json.tmp" && mv "$DIR/status.json.tmp" "$DIR/status.json"
}

dump() {
  f="$DIR/schnaeppli-$(date +%Y%m%d-%H%M).sql.gz"
  rm -f "$DIR/.dump-failed"
  # sh has no pipefail: record a pg_dump failure separately, or a half dump would pass.
  { pg_dump -h db -U "${POSTGRES_USER:-schnaeppli}" -d "${POSTGRES_DB:-schnaeppli}" --no-owner || touch "$DIR/.dump-failed"; } \
    | gzip -9 > "$f.tmp"
  if [ ! -e "$DIR/.dump-failed" ] && gzip -t "$f.tmp"; then
    mv "$f.tmp" "$f"
    echo "backup ok: $f ($(du -h "$f" | cut -f1))"
    status ok "$(basename "$f")"
  else
    rm -f "$f.tmp" "$DIR/.dump-failed"
    echo "backup FAILED" >&2
    status failed "pg_dump or gzip check failed"
  fi
  find "$DIR" -name 'schnaeppli-*.sql.gz' -mtime +"$KEEP_DAYS" -delete
}

newest_age() { # seconds since the newest dump, or a huge number if none
  n=$(ls -t "$DIR"/schnaeppli-*.sql.gz 2>/dev/null | head -1 || true)
  if [ -z "$n" ]; then echo 999999999; else echo $(( $(date +%s) - $(date -r "$n" +%s) )); fi
}

next_slot() { # next time aligned to BACKUP_HOUR + k * interval
  now=$(date +%s)
  hh=$(printf "%02d" "${BACKUP_HOUR:-3}")
  t=$(date -d "$(date +%Y-%m-%d) ${hh}:00" +%s 2>/dev/null || echo "$now")
  t=$((t - 86400))
  while [ "$t" -le "$now" ]; do t=$((t + INTERVAL)); done
  echo "$t"
}

# Leftovers of a dump that a crash interrupted are never valid backups.
find "$DIR" -name '*.sql.gz.tmp' -delete
sleep 20  # let the database finish starting
if [ "$(newest_age)" -ge "$INTERVAL" ]; then
  echo "backup overdue after start, running now"
  dump
fi
while true; do
  t=$(next_slot)
  sleep $((t - $(date +%s)))
  dump
done
