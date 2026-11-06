set -uo pipefail
ROOT=/c/Users/fa1nt/SemiTaskBot-GHG
cd "$ROOT/meetup-planner-main/backend"
./.venv/Scripts/python.exe -m pytest -q 2>&1 | tee /tmp/bt.log | tail -3
TESTS=$(python - <<'PY'
import re
log = open('/tmp/bt.log', encoding='utf-8', errors='replace').read()
found = re.findall(r'(\d+) passed', log)
print(found[-1] if found else '0')
PY
)
echo "tests=$TESTS"
grep -qE '[0-9]+ failed' /tmp/bt.log && { echo "TESTS_FAILED"; exit 2; }
cd "$ROOT/meetup-planner-main"
git add -A
git commit -q -F - <<'EOF'
Смена просит открыть чек-лист сама

Напоминания умели только про сроки поручений, поэтому про неначатую смену
человек не узнавал вовсе, а любой не-задачный push вёл в корень приложения.

Новый вид shift_start смотрит смены на сегодня, чьё время уже началось,
пропускает тех, у кого есть прогон чек-листа, и присылает одно сообщение в
день. Тап открывает чек-лист.
EOF
GIT_ASKPASS=$ROOT/tools/git-askpass.sh GIT_TERMINAL_PROMPT=0 git -c credential.helper= push
git log -1 --format='%h %s'
cd "$ROOT"
python tools/deploy-amvera.py all 2>&1 | tee /tmp/amvera.log | tail -8
echo "--- meta ---"
for i in $(seq 1 24); do
  sleep 10
  if curl -s --max-time 10 https://meetup-planner-youmakemefry.waw0.amvera.tech/api/meta -o /tmp/meta.json && [ -s /tmp/meta.json ]; then
    echo "meta_try=$i"
    cat /tmp/meta.json
    break
  fi
done
