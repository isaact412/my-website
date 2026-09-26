# Makes the server bible work when Ollama is set to always answer in JSON.
# Keeps your other changes: backs up, test-applies, only applies if it fits cleanly.
cd ~/discord-ai-bot || { echo "❌ ~/discord-ai-bot not found"; exit 1; }
if grep -q "def read_answer" bot/memory/bible.py 2>/dev/null; then
  echo "ℹ️  already installed. nothing changed."; exit 0
fi
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP=~/discord-ai-bot-backup-$STAMP
mkdir -p "$BACKUP" && cp -R bot "$BACKUP"/ && echo "📦 backed up your code to $BACKUP"
PATCH_FILE=$(mktemp)
curl -fsSL https://raw.githubusercontent.com/isaact412/my-website/claude/fervent-lamport-jh3erl/discord-ai-bot/patches/bible_json.patch -o "$PATCH_FILE" \
  || { echo "❌ couldn't download the patch. nothing changed."; exit 1; }
if patch -p1 -N --dry-run < "$PATCH_FILE" > /tmp/bible_json_check.txt 2>&1; then
  patch -p1 -N < "$PATCH_FILE" > /dev/null
  if .venv/bin/python -m py_compile bot/memory/bible.py; then
    echo "✅ bible JSON fix installed. your other changes were kept."
    echo "👉 now restart the bot."
  else
    cp -R "$BACKUP"/bot ./ && echo "❌ something didn't compile, so I put your original code back. nothing changed."
  fi
else
  echo "❌ doesn't fit your version. NOTHING was changed. send Claude a screenshot of this:"
  cat /tmp/bible_json_check.txt
fi
