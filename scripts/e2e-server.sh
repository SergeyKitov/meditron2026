#!/usr/bin/env bash
set -euo pipefail
task_tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/meditron-e2e.XXXXXX")
export DATABASE_URL="sqlite:///$task_tmp_dir/demo.db"
exec bash "$(dirname "$0")/dev.sh"
