"""Canonical identity tests (committed registry; no fuzzy joins)."""

from __future__ import annotations

import json

import pandas as pd

from cbb_edge.data.ids import teams


def test_registry_ids_unique_and_well_formed():
    reg = pd.read_csv(teams.TEAMS_CSV, dtype=str)
    assert len(reg) > 340
    assert reg.team_id.is_unique
    assert reg.espn_team_id.is_unique
    assert reg.team_id.str.fullmatch(r"T\d{4}").all()


def test_canonical_from_espn():
    reg = pd.read_csv(teams.TEAMS_CSV)
    duke = reg[reg.espn_display_name == "Duke Blue Devils"].iloc[0]
    assert teams.canonical_from_espn(int(duke.espn_team_id)) == duke.team_id
    assert teams.canonical_from_espn(None) is None
    assert teams.canonical_from_espn(99999999) is None  # non-D-I -> no canonical ID


def test_resolve_exact_scoped():
    reg = pd.read_csv(teams.TEAMS_CSV)
    duke = reg[reg.espn_display_name == "Duke Blue Devils"].team_id.iloc[0]
    assert teams.resolve("Duke Blue Devils", "espn") == duke
    assert teams.resolve("duke blue devils", "espn") == duke  # normalization only


def test_resolve_does_not_fuzzy_match_and_logs(tmp_path):
    assert teams.resolve("Duke Blu Devils", "espn") is None
    log = (tmp_path / "data" / "ids" / "unresolved.jsonl").read_text().splitlines()
    rec = json.loads(log[-1])
    assert rec["name"] == "Duke Blu Devils" and rec["reason"] == "missing"


def test_ambiguous_alias_returns_none():
    al = pd.read_csv(teams.ALIASES_CSV, dtype=str)
    dup = al.groupby("alias_norm").team_id.nunique()
    amb = dup[dup > 1]
    if len(amb):
        name = al[al.alias_norm == amb.index[0]].alias.iloc[0]
        # cross-source ambiguity must not silently resolve
        assert teams.resolve(name, "nonexistent_source") is None


def test_normalize():
    assert teams.normalize("Hawai'i") == "hawaii"
    assert teams.normalize("San José State") == "san jose state"
    assert teams.normalize("Texas A&M") == "texas a and m"
