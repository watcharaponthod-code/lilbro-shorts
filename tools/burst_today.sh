#!/usr/bin/env bash
# Fire uploads back-to-back until TARGET uploads exist in state/history.json for today (Thai time),
# then restore the normal 110-min spacing. One run at a time (the workflow's concurrency group keeps only one pending run).
cd "$(dirname "$0")/.." || exit 1
TARGET=${1:-10}
R=watcharaphon-dotcom/lilbro-shorts
gh variable set MIN_GAP_MIN -R $R -b 0
count_today() {
  git pull -q --rebase --autostash >/dev/null 2>&1
  python -c "
import json,time,datetime as d
h=json.load(open('state/history.json',encoding='utf-8'))
tz=d.timezone(d.timedelta(hours=7)); today=d.datetime.now(tz).date()
print(sum(1 for x in h if x.get('id') and d.datetime.fromtimestamp(x['t'],tz).date()==today))"
}
wait_idle() {
  while gh run list -R $R -L 5 --json status -q '.[].status' | grep -qE 'in_progress|queued|pending|waiting'; do sleep 30; done
}
fails=0
for i in $(seq 1 14); do
  wait_idle
  n=$(count_today); q=$(ls state/script_queue 2>/dev/null | wc -l)
  echo "$(date '+%H:%M') today=$n queue=$q"
  [ "$n" -ge "$TARGET" ] && break
  [ "$(date -u +%H)" = "17" ] && { echo "past midnight, stop"; break; }
  if [ "$q" -eq 0 ]; then echo "queue empty, waiting for the writer"; sleep 300; continue; fi
  before=$n
  gh workflow run short.yml -R $R >/dev/null; sleep 20
  wait_idle
  after=$(count_today)
  if [ "$after" -le "$before" ]; then fails=$((fails+1)); tail -1 state/runs.jsonl | cut -c1-300; else fails=0; fi
  [ "$fails" -ge 3 ] && { echo "3 runs in a row without an upload, stopping"; break; }
done
gh variable set MIN_GAP_MIN -R $R -b 110
echo "done: today=$(count_today), MIN_GAP_MIN back to 110"
