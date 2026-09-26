# Makes replies actually use the server knowledge (+ saves the last prompt to data/last_prompt.txt).
# Keeps your other changes: backs up, test-applies, only applies if it fits cleanly.
cd ~/discord-ai-bot || { echo "❌ ~/discord-ai-bot not found"; exit 1; }
if grep -q "SERVER_SPECIFIC" bot/ai/prompts.py 2>/dev/null; then
  echo "ℹ️  already installed. nothing changed."; exit 0
fi
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP=~/discord-ai-bot-backup-$STAMP
mkdir -p "$BACKUP" && cp -R bot "$BACKUP"/ && echo "📦 backed up your code to $BACKUP"
PATCH_FILE=$(mktemp)
curl -fsSL https://raw.githubusercontent.com/isaact412/my-website/claude/fervent-lamport-jh3erl/discord-ai-bot/patches/prompt_focus.patch -o "$PATCH_FILE" \
  || { echo "❌ couldn't download the patch. nothing changed."; exit 1; }
if patch -p1 -N --dry-run < "$PATCH_FILE" > /tmp/prompt_focus_check.txt 2>&1; then
  patch -p1 -N < "$PATCH_FILE" > /dev/null
  if .venv/bin/python -m py_compile bot/ai/prompts.py bot/services/responder.py; then
    echo "✅ prompt focus installed. your other changes were kept."
    echo "👉 now restart the bot."
  else
    cp -R "$BACKUP"/bot ./ && echo "❌ something didn't compile, so I put your original code back. nothing changed."
  fi
else
  echo "❌ doesn't fit your version. NOTHING was changed. send Claude a screenshot of this:"
  cat /tmp/prompt_focus_check.txt
fi
