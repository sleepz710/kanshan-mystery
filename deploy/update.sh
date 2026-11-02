#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ "$EUID" -ne 0 ]]; then
    echo '请执行 sudo bash deploy/update.sh。' >&2
    exit 1
fi
if [[ -n "$(sudo -u kanshan git status --porcelain --untracked-files=no)" ]]; then
    echo '请先提交已跟踪文件的本地改动，再更新。' >&2
    exit 1
fi
sudo -u kanshan git pull --ff-only
sudo -u kanshan .venv/bin/python -m pip install -r requirements.txt
sudo -u kanshan .venv/bin/python -m pytest -q
systemctl restart kanshan
sudo -u kanshan .venv/bin/python deploy/smoke.py --wait
