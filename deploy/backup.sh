#!/bin/sh
# Daily pg_dump at BACKUP_HOUR (container time), keeps KEEP_DAYS days.
set -eu
umask 077
while true; do
  now=$(date +%s)
  hh=$(printf "%02d" "$BACKUP_HOUR")
  next=$(date -d "$(date +%Y-%m-%d) ${hh}:00" +%s 2>/dev/null || echo $((now + 86400)))
  [ "$next" -le "$now" ] && next=$((next + 86400))
  sleep $((next - now))
  f="/backups/schnaeppli-$(date +%Y%m%d-%H%M).sql.gz"
  if pg_dump -h db -U "${POSTGRES_USER:-schnaeppli}" -d "${POSTGRES_DB:-schnaeppli}" --no-owner | gzip -9 > "$f.tmp"; then
    mv "$f.tmp" "$f"
    echo "backup ok: $f ($(du -h "$f" | cut -f1))"
  else
    rm -f "$f.tmp"
    echo "backup FAILED" >&2
  fi
  find /backups -name 'schnaeppli-*.sql.gz' -mtime +"$KEEP_DAYS" -delete
done
