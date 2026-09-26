#!/usr/bin/env bash
# Regenerates setup_mac.sh: a one-paste installer that writes every project file
# into ~/discord-ai-bot, keeps .env secrets, installs packages, and starts the bot.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=setup_mac.sh
FILES=$(git ls-files --others --cached --exclude-standard | grep -v '^setup_mac.sh$' | sort)
{
echo '# Installs/updates the bot files in ~/discord-ai-bot. Never touches your token or API keys.'
echo 'cd ~/discord-ai-bot || exit 1'
for f in $FILES; do
  d=$(dirname "$f"); [ "$d" != "." ] && echo "mkdir -p $d"
  echo "cat > $f <<'EOF_FILE'"; cat "$f"; echo "EOF_FILE"
done
cat <<'EOS'
touch .env
add_default() { grep -q "^$1=" .env || echo "$1=$2" >> .env; }
add_default DISCORD_TOKEN ""
add_default OWNER_USER_ID 819246808671977482
add_default DEV_GUILD_ID 1203498616560295946
add_default LOG_LEVEL INFO
add_default ALLOW_PAID_MODELS false
add_default AI_PROVIDER_CHAIN groq
add_default GROQ_API_KEY ""
add_default GROQ_MODEL auto
add_default BACKGROUND_DAILY_CALL_LIMIT 150
add_default HISTORY_DAILY_CALL_LIMIT 250
add_default OLLAMA_MODEL auto
add_default WORKER_PROVIDER_CHAIN ollama
add_default BACKGROUND_PARALLEL 2
if ! grep -qE '^DISCORD_TOKEN=.+' .env; then echo "⚠️  DISCORD_TOKEN missing in .env"; fi
if ! grep -qE '^GROQ_API_KEY=.+' .env; then echo "⚠️  GROQ_API_KEY missing in .env"; fi
echo "✅ files updated, secrets kept"
source .venv/bin/activate && pip install -q --disable-pip-version-check -r requirements.txt && python -m bot.main
EOS
} > "$OUT"
echo "wrote $OUT"
