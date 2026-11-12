#!/usr/bin/env bash
set -e

PORT="${1:-8085}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

echo "=================================================================="
echo "  Enterprise Qlik-to-Looker Migration Engine Studio"
echo "=================================================================="
echo "Starting local server on port ${PORT}..."
echo "Open your browser at: http://localhost:${PORT}"
echo "Press Ctrl+C to stop."
echo "=================================================================="

python3 -m enterprise_qlik.cli serve --port "${PORT}"
