"""Match settled Kalshi CBB game/period markets to ESPN games (research only).

Event tickers encode the scheduled ET date and the two Kalshi team codes (e.g. KXNCAAMBSPREAD-26APR06CONNMICH).
Kalshi codes are ESPN abbreviations for most teams; a game matches when the concatenated ESPN abbreviations of its two
teams (either order) equal the event code and the ESPN date is within one day.  Ambiguous or unmatched events are
dropped and counted, never guessed.  Market side = ticker suffix with the strike digits removed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

SERIES = ["KXNCAAMBSPREAD", "KXNCAAMBTOTAL", "KXNCAAMBTEAMTOTAL", "KXNCAAMBGAME", "KXNCAAMB1HSPREAD", "KXNCAAMB1HTOTAL",
          "KXNCAAMB1HWINNER", "KXNCAAMB1H", "KXNCAAMB2HSPREAD", "KXNCAAMB2HTOTAL", "KXNCAAMB2H"]
_EV = re.compile(r"^(?P<series>[A-Z0-9]+)-(?P<yy>\d\d)(?P<mon>[A-Z]{3})(?P<day>\d\d)(?P<code>[A-Z0-9]+)$")


def load_markets(root: Path) -> pd.DataFrame:
    rows = {}
    for s in SERIES:
        for tier in ("historical", "live"):
            f = root / f"{s}.{tier}.jsonl"
            if not f.exists():
                continue
            for line in f.open():
                d = json.loads(line)
                if d.get("status") not in ("finalized", "settled") or d.get("result") not in ("yes", "no"):
                    continue
                rows[d["ticker"]] = {"series": s, "ticker": d["ticker"], "event": d["event_ticker"],
                                     "strike": d.get("floor_strike"), "result": int(d["result"] == "yes"),
                                     "suffix": d["ticker"][len(d["event_ticker"]) + 1:], "rules": d.get("rules_primary", "")}
    return pd.DataFrame(rows.values())


def match_events(mk: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Adds game_id, side ('home'/'away'/'tie'/None for totals).  games needs date, home_abbr, away_abbr, game_id."""
    ev = mk[["event"]].drop_duplicates().copy()
    parts = ev.event.str.extract(_EV)
    ev = ev.join(parts)
    ev["date"] = pd.to_datetime("20" + ev.yy + ev["mon"].str.title() + ev.day, format="%Y%b%d", errors="coerce")
    keys = []
    for gid, d, h, a in zip(games.game_id, games.date, games.home_abbr.fillna(""), games.away_abbr.fillna(""), strict=False):
        for code in {a + h, h + a}:
            for dd in (-1, 0, 1):
                keys.append((code, d + pd.Timedelta(days=dd), gid, abs(dd)))
    K = pd.DataFrame(keys, columns=["code", "date", "game_id", "dd"])
    m = ev.merge(K, on=["code", "date"], how="left")
    m = m[m.game_id.notna()]
    best = m.sort_values("dd").groupby("event").head(1)
    amb = m.groupby("event").dd.apply(lambda x: (x == x.min()).sum() > 1)
    best = best[~best.event.map(amb).fillna(False).astype(bool)][["event", "game_id"]].assign(alias="")
    # fallback: one team's ESPN abbreviation sits at the matching end of the code and exactly one game qualifies;
    # the remaining code is that game's other team (Kalshi alias), recorded for side resolution
    rest = ev[~ev.event.isin(best.event)]
    gd = games[["game_id", "date", "home_abbr", "away_abbr"]].dropna()
    fb = []
    for e, code, d in zip(rest.event, rest.code, rest.date, strict=False):
        if pd.isna(d) or not isinstance(code, str):
            continue
        c = gd[(gd.date >= d - pd.Timedelta(days=1)) & (gd.date <= d + pd.Timedelta(days=1))]
        hits = []
        for gid, h, a in zip(c.game_id, c.home_abbr, c.away_abbr, strict=False):
            for first, second in ((a, h), (h, a)):
                if code.startswith(first) and len(code) > len(first):
                    hits.append((gid, code[len(first):], first))
                if code.endswith(second) and len(code) > len(second):
                    hits.append((gid, code[: -len(second)], second))
        # (game, alias = unmatched remainder of the code, known = the ESPN abbreviation that matched)
        ok = set(hits)
        gids = {g_ for g_, _, _ in ok}
        if len(gids) == 1:
            g_, al, kn = sorted(ok)[0]
            fb.append((e, g_, al + "|" + kn))
    if fb:
        best = pd.concat([best, pd.DataFrame(fb, columns=["event", "game_id", "alias"])], ignore_index=True)
    out = mk.merge(best, on="event", how="inner")
    g = games.set_index("game_id")
    team = out.suffix.str.replace(r"\d+$", "", regex=True).values
    ha, aa = g.home_abbr.reindex(out.game_id).values, g.away_abbr.reindex(out.game_id).values
    side = pd.Series([None] * len(out), dtype=object)
    side[team == ha] = "home"
    side[team == aa] = "away"
    side[team == "TIE"] = "tie"
    # alias resolution: suffix equals the alias of the team whose ESPN code was not found
    al = out.alias.str.split("|").str[0].values
    kn = out.alias.str.split("|").str[1].values
    m_alias = (out.alias.values != "") & side.isna().values & (team == al)
    side[m_alias & (kn == ha)] = "away"
    side[m_alias & (kn == aa)] = "home"
    out["side"] = side.values
    out["match"] = (out.alias.values == "").astype(int)
    return out


def match_report(mk: pd.DataFrame, matched: pd.DataFrame) -> dict:
    tot = mk.groupby("series").event.nunique()
    got = matched.groupby("series").event.nunique()
    return {s: {"events": int(tot[s]), "matched": int(got.get(s, 0))} for s in tot.index}
