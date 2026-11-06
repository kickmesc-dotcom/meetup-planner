set -uo pipefail
ROOT=/c/Users/fa1nt/SemiTaskBot-GHG
cd "$ROOT/meetup-planner-main"
echo "--- commit? ---"
git log -3 --format='%h %s'
echo "--- temp files ---"
ls tools/_tmp_pack3.sh tools/_tmp_journal3.py 2>/dev/null
echo "--- prod ---"
MAIN=$(curl -s --max-time 25 https://semitaskbot.pages.dev/ | grep -oE '/assets/index-[A-Za-z0-9_-]+\.js' | head -1)
echo "prod_main=$MAIN"
COUNT=$(curl -s --max-time 25 "https://semitaskbot.pages.dev$MAIN" | grep -c 'Раскрыть пункт с фотоотчётом')
echo "prod_fold=$COUNT"
PAGES=""
if [ "$COUNT" = "0" ]; then
  echo "--- deploy needed ---"
  cd "$ROOT/meetup-planner-main/frontend"
  npm run build 2>&1 | tail -2
  CF=$(cd "$ROOT" && python -c "import sys;sys.path.insert(0,'tools');import creds;print(creds.parse().get('CLOUDFLARE_API_TOKEN') or '')")
  CLOUDFLARE_API_TOKEN="$CF" npx wrangler@4 pages deploy dist --project-name=semitaskbot --branch=main --commit-dirty=true 2>&1 | tee /tmp/deploy3.log | tail -2
  PAGES=$(grep -oE 'https://[a-z0-9]+\.semitaskbot\.pages\.dev' /tmp/deploy3.log | head -1)
  echo "pages=$PAGES"
  MAIN=$(curl -s --max-time 25 https://semitaskbot.pages.dev/ | grep -oE '/assets/index-[A-Za-z0-9_-]+\.js' | head -1)
  echo "prod_main_after=$MAIN"
  echo -n "prod_fold_after="
  curl -s --max-time 25 "https://semitaskbot.pages.dev$MAIN" | grep -c 'Раскрыть пункт с фотоотчётом'
fi
cd "$ROOT/meetup-planner-main"
if ! git log --format=%s -5 | grep -q 'Фото-пункты чек-листа'; then
  if [ -n "$PAGES" ]; then
    python tools/_tmp_journal3.py "$PAGES" 824 || echo "journal_failed"
  fi
  rm -f tools/_tmp_journal3.py tools/_tmp_pack3.sh
  git add -A
  git commit -q -F - <<'EOF'
Фото-пункты чек-листа свёрнуты в строку

На телефоне пункт с фотоотчётом занимал пол-экрана, и в список помещалось
полтора пункта. Теперь название видно всегда, а описание и камера — по тапу;
«Свернуть» возвращает компактный вид.
EOF
  GIT_ASKPASS=$ROOT/tools/git-askpass.sh GIT_TERMINAL_PROMPT=0 git -c credential.helper= push
fi
echo "--- final ---"
git log -1 --format='%h %s'
git status --short | head -3
