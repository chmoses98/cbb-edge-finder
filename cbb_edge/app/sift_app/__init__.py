"""CBB application publisher for Sift Sports Intelligence (``edge_finder.app.v1``).

An ADAPTER, never a model: it reads what the frozen prospective system already archived
(projection records, roster truth, schedule observations, the prospective scoreboard, the
read-only Kalshi capture) and translates it into the generic app contract authored in
``chmoses98/kalshi-bet-router`` (vendored at ``contract/edge_finder_contract``).

    archives / model outputs -> sift_app -> app/latest (edge_finder.app.v1) -> Sift

Rules this package keeps (tested in ``tests/test_sift_app*.py``):

* it never imports or runs a projection, a rating fit or the roster overlay;
* it never writes into an archive checkout (inputs are read-only);
* the projection shown for a game is the newest archived record PROVABLY made before tip
  (``selection.py``); a record made after tip is never shown as the game's projection;
* models keep their frozen roles: ``pure-0.2.0`` incumbent, challengers shadow, the
  P-ROSTER-1 overlay ``pure-0.5.0+roster``; nothing ranks them before the preregistered
  evaluation allows it;
* no recommendations, no wagers, no model prices against markets.
"""

from __future__ import annotations

import sys
from pathlib import Path

# the vendored contract lives beside the package, not inside it (every sport repo vendors it
# at contract/edge_finder_contract, byte-for-byte, checked against its MANIFEST.json)
CONTRACT_DIR = Path(__file__).resolve().parents[3] / "contract"
if CONTRACT_DIR.exists() and str(CONTRACT_DIR) not in sys.path:
    sys.path.insert(0, str(CONTRACT_DIR))

SPORT = "CBB"
REPO = "chmoses98/cbb-edge-finder"
APP_BRANCH = "app-data"
APP_ROOT = "app/latest"
