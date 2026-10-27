#!/usr/bin/env bash
set -euo pipefail

PROVIDER="${CORSENTINEL_PROVIDER:-cortensor-router}"
MODEL="${CORSENTINEL_MODEL:-gpt-oss-20b}"
HOME_DIR="${CORSENTINEL_HOME:-.runtime_home}"

export CORTENSOR_API_KEY="${CORTENSOR_API_KEY:-cor-mainnet-alpha-session-key}"
openminion --home-root "$HOME_DIR" setup --provider "$PROVIDER" --model "$MODEL" --no-chat
echo "CorSentinel OpenMinion 0.1 config initialized in $HOME_DIR/.openminion/agents.json"
