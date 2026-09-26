# Fixes the overnight scan crash (duplicate memory sources) WITHOUT overwriting your other changes.
cd ~/discord-ai-bot || { echo "❌ ~/discord-ai-bot not found"; exit 1; }
if grep -q "cites the same message twice" bot/memory/store.py 2>/dev/null; then
  echo "ℹ️  fix already installed. nothing changed."; exit 0
fi
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP=~/discord-ai-bot-backup-$STAMP
mkdir -p "$BACKUP" && cp -R bot "$BACKUP"/ && echo "📦 backed up your code to $BACKUP"
PATCH_FILE=$(mktemp)
curl -fsSL https://raw.githubusercontent.com/isaact412/my-website/claude/fervent-lamport-jh3erl/discord-ai-bot/patches/fix_duplicate_sources.patch -o "$PATCH_FILE" \
  || { echo "❌ couldn't download the fix. nothing changed."; exit 1; }
if patch -p1 -N --dry-run < "$PATCH_FILE" > /tmp/fix_dup_check.txt 2>&1; then
  patch -p1 -N < "$PATCH_FILE" > /dev/null
  if .venv/bin/python -m py_compile bot/memory/store.py; then
    echo "✅ crash fix installed. your other changes were kept."
    echo "👉 now restart the bot: the scan resumes where it stopped."
  else
    cp -R "$BACKUP"/bot ./ && echo "❌ something didn't compile, so I put your original code back. nothing changed."
  fi
else
  echo "❌ the fix doesn't fit your version. NOTHING was changed. send Claude a screenshot of this:"
  cat /tmp/fix_dup_check.txt
fi
