# Adds the who-is-who nickname list (config/nicknames.yaml) WITHOUT overwriting your other changes.
# 1) backs up your code  2) test-applies the patch  3) only applies it if it fits cleanly.
cd ~/discord-ai-bot || { echo "❌ ~/discord-ai-bot not found"; exit 1; }
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP=~/discord-ai-bot-backup-$STAMP
mkdir -p "$BACKUP" && cp -R bot config migrations "$BACKUP"/ 2>/dev/null
echo "📦 backed up your code to $BACKUP"
PATCH_FILE=$(mktemp)
curl -fsSL https://raw.githubusercontent.com/isaact412/my-website/claude/fervent-lamport-jh3erl/discord-ai-bot/patches/nicknames.patch -o "$PATCH_FILE" \
  || { echo "❌ couldn't download the patch. nothing changed."; exit 1; }
if [ -f bot/character/nicknames.py ]; then
  echo "ℹ️  already installed (bot/character/nicknames.py exists). nothing changed."; exit 0
fi
if patch -p1 -N --dry-run < "$PATCH_FILE" > /tmp/nicknames_check.txt 2>&1; then
  patch -p1 -N < "$PATCH_FILE" > /dev/null
  if .venv/bin/python -m py_compile bot/character/nicknames.py bot/memory/bible.py bot/ai/prompts.py bot/services/responder.py; then
    echo "✅ nickname list installed. your other changes were kept."
    echo "👉 now restart your bot the way you normally do."
  else
    cp -R "$BACKUP"/bot ./ && echo "❌ something didn't compile, so I put your original code back. nothing changed."
  fi
else
  echo "❌ the upgrade doesn't fit cleanly with your version (someone changed the same lines). NOTHING was changed."
  echo "   send Claude a screenshot of this:"
  cat /tmp/nicknames_check.txt
fi
