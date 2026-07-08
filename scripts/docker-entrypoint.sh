#!/usr/bin/env sh
set -eu

if [ -z "${FEISHU_APP_ID:-}" ]; then
  echo "FEISHU_APP_ID is required" >&2
  exit 1
fi

if [ -z "${FEISHU_APP_SECRET:-}" ]; then
  echo "FEISHU_APP_SECRET is required" >&2
  exit 1
fi

if [ -z "${LLM_API_KEY:-}" ]; then
  echo "LLM_API_KEY is required" >&2
  exit 1
fi

printf '%s' "$FEISHU_APP_SECRET" \
  | lark-cli config init \
      --app-id "$FEISHU_APP_ID" \
      --app-secret-stdin \
      --brand "${FEISHU_BRAND:-feishu}" >/dev/null

exec sh -c 'tail -f /dev/null | lark-cli event consume im.message.receive_v1 --as bot --quiet | python -u -m diet_tracker.feishu_cli_bridge'
