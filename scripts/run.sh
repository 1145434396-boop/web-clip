#!/usr/bin/env bash
# web-clip runner: config check + clip + human-readable output
set -uo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$SKILL_DIR/scripts/clip.py"

# No URL → show config only
if [ $# -eq 0 ]; then
    python3 "$PY" --show-config
    exit 0
fi

# Check if output dir is set (unless --out is already passed)
if ! echo "$*" | grep -q -- '--out'; then
    CONFIG=$(python3 "$PY" --show-config 2>/dev/null || echo '{}')
    OUT=$(python3 -c "import json,sys; print(json.loads('$CONFIG').get('out') or '')" 2>/dev/null || echo "")
    if [ -z "$OUT" ]; then
        echo "NEED_DIR"
        exit 2
    fi
fi

# Run clip
RAW=$(python3 "$PY" "$@" 2>&1)
EXIT_CODE=$?

# Format output
python3 - "$RAW" <<'EOF'
import sys, json, re

raw = sys.argv[1]
try:
    d = json.loads(raw)
except Exception:
    print(raw)
    sys.exit(1)

if d.get('ok'):
    title   = d.get('title') or '（无标题）'
    article = d.get('article', '')
    images  = d.get('images', 0)
    warns   = d.get('warnings', [])
    preview = d.get('preview', '')
    print(f"✅ {title}")
    print(f"   路径：{article}")
    print(f"   图片：{images} 张")
    if preview:
        print(f"   预览：{preview[:60]}…")
    if warns:
        print(f"   ⚠️  {' | '.join(warns)}")
else:
    err  = d.get('error', '未知错误')
    stub = d.get('stub', '')
    print(f"❌ 抓取失败：{err}")
    if stub:
        print(f"   Stub：{stub}")
EOF
