#!/usr/bin/env bash
# Run the same fast checks CI runs. Use before every push.
set -euo pipefail
python -m cbb_edge.data.cost_policy audit
ruff check .
ruff format --check .
python -m mypy
python -m pytest -q
