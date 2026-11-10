"""Render research/reports/ORIENTATION_SCORING.md from orientation_comparison.json + the model_inputs dry run.

    python scripts/research/render_orientation_report.py research/orientation research/wave13/model_inputs_dry_run.json \
        research/reports/ORIENTATION_SCORING.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    d, dry, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    r = json.loads((d / "orientation_comparison.json").read_text())
    dr = json.loads(dry.read_text())
    sb, ka = r["scoreboard"], r["kalshi"]
    L: list[str] = []
    a = L.append
    a("# Orientation integration — before/after on the complete archive (2026-11-10)\n")
    a("RESEARCH_ONLY. Follow-up to PR #46 (Wave 12/13 results unchanged, no predictive challenger promoted). **Not merged; the production "
      "scoring change awaits owner review.** OLD = production code at "
      f"`{r['baseline_ref']}` loaded unmodified from git; NEW = this branch. Identical inputs, archives read-only "
      f"(projections-archive `{r['archive_heads']['projections'][:10]}`, roster-archive `{r['archive_heads']['rosters'][:10]}`, clock `{r['now']}`).\n")  # fmt: skip
    a("## What changed\n")
    a("`cbb_edge/data/ids/orientation.py::classify` is the single decision (canonical team ids): `SAME`, `SWAPPED` (same two teams reversed, accepted only "
      "when the neutral-site flag is true on every source that carries one), `UNVERIFIED` (anything else; fail closed).\n"
      "* **Scoreboard** (`prospective_score.score`): a verified reversal is no longer `UNSCORABLE: schedule_identity_changed`; its result margin is mapped onto "
      "the projected teams (totals are orientation-free). A schedule row whose teams do not resolve is now `UNVERIFIED` (the earlier rule silently scored it). "
      "`remap_swapped=False` keeps the earlier reversal handling.\n"
      "* **Kalshi panel** (`kalshi/history._projections` via `selection.select`): a verified reversal is reframed into the schedule's frame, which is the "
      "frame `parse_contract` / `settle` use for `subject_side`, so model probabilities point the right way. Contract parsing, `subject_team_id` and settlement "
      "code are untouched. The Sift app still treats every change as changed (unchanged behaviour).\n"
      "* Archived projections and schedule rows are never rewritten; reframing is a copy made at read time.\n")  # fmt: skip
    a("## A. Scoreboard, old vs new\n")
    a(f"Records read {sb['records_read']}; completed games {sb['completed_games']}. Verified neutral-site reversals: `{sb['reversed_neutral_games']}` "
      f"(the four Wave 12 games). Unverified identities in the archive: `{sb['unverified_identity_games']}`.\n")  # fmt: skip
    a("| check | result |\n|---|---|")
    for k, lab in (("paired_games", "paired_games, all other games (every column)"), ("integrity_gate_unaffected_rows", "integrity gate, all other games"),
                   ("team_games_unaffected", "team-game view, all other games")):  # fmt: skip
        x = sb[k]
        a(
            f"| {lab} | {'**identical**' if x['identical'] else '**DIFFERENT**'} ({x['rows_compared']} rows × {x['columns']} columns) |"
        )
    a(f"| gate counts | old {sb['gate_counts_old']} → new {sb['gate_counts_new']} |")
    a(f"| rows that differ | exactly `{sb['gate_rows_that_differ']}` |\n")
    a("The four reversed games (projected-home frame; base pure-0.5.0):\n")
    a("| game | old gate | new gate | schedule-home margin | result mapped to projected home | projected margin | error (old pairing would have used the wrong sign) |\n|---|---|---|---|---|---|---|")  # fmt: skip
    for g, x in sb["reversed_games_detail"].items():
        c = sb["gate_changes"][g]
        a(f"| {g} | {c['old'][0]} ({c['old'][1]}) | {c['new'][0]} | {x['schedule_margin_for_schedule_home']:+.0f} | {x['new_result_margin_for_projected_home']:+.0f} | "
          f"{x['new_base_margin']:+.1f} | {x['new_base_err']:+.1f} |")  # fmt: skip
    a("\n### Fail closed (schedule inputs perturbed in memory for real games; old and new code)\n")
    a("| case | old | new |\n|---|---|---|")
    for k, x in sb["fail_closed_perturbations"].items():
        a(
            f"| {k} | {x['old']['status']} | {x['new']['status']}{' — reason ' + x['new']['reasons'] if x['new']['reasons'] else ''} |"
        )
    a("\nThe one behavioural difference outside the reversals: an unresolved schedule team id was previously scored as if it were the projected matchup "
      "(fail-open); it is now UNSCORABLE. No archived game is in that state, so no historical result moves because of it.\n")  # fmt: skip
    a("## B. Kalshi path, old vs new\n")
    s = ka["settlement_all_settled_panel_contracts"]
    a(f"* Frozen-projection selection compared per game at one minute before the tip: **{ka['games_with_frozen_records_compared']}** games; old and new differ in "
      f"**{ka['games_where_old_and_new_selection_differ']}** — the four reversals (old: no usable version, all five skipped as identity-changed; new: all five "
      "reframed). Every other game is identical.\n"
      f"* Settlement of every settled panel contract against the schedule-archive final: **{s['agree']:,} agree, {s['disagree']} disagree** "
      f"({s['not_checkable']:,} not checkable: halves, overtime, race, ties). On the reversed games: {s['agree_on_reversed_games']:,} agree, "
      f"{s['disagree_on_reversed_games']} disagree. Settlement code is unchanged; this confirms contract directions are untouched.\n")  # fmt: skip
    b = ka["reversed_games_probability_brier"]
    if b.get("n_contracts"):
        a(f"* Model probabilities for the reversed games (last pre-tip panel row per contract, outcome from the settled score, {b['n_contracts']} version×contract "
          f"probabilities): Brier **{b['reframed']:.4f}** reframed vs {b['raw_unframed']:.4f} if the projection were applied without reframing (backwards). The old panel held "
          f"{b['stored_nonnull_probabilities_in_old_panel']} such probabilities (they were skipped).\n")  # fmt: skip
    a("## C. `model_inputs` real-data dry run (before integration)\n")
    c, p = dr["checks"], dr.get("future_row_perturbation", {})
    a(f"Production projection code on a locally rebuilt free-input lake, `{dr['version']}` at as-of `{dr['as_of']}` ({c['records']} records). "
      f"Pass: **{dr['pass']}**.\n"
      f"* games / possessions seen vs an independent recomputation from raw silver rows: **{len(c['seen_mismatches_vs_independent'])} mismatches**;\n"
      f"* pace / efficiency noise vs an independent loop recomputation: max |diff| {c['noise_max_abs_diff']:.1e};\n"
      f"* exported efficiency and tempo vs the same run's `ratings` block: max |diff| {c['same_run_ratings_max_abs_diff']:.1e}; vs the archived record of the same as-of "
      "(incumbent): 0.0 (the checkpoint-based challengers differ by up to 2.0 across environments because their roster/availability inputs are not reproducible "
      "locally — that is input data, not the export);\n"
      f"* **future-row perturbation**: {p.get('future_rows_perturbed')} team-game rows with `available_at ≥ as_of` scaled (possessions ×1.6, ppp ×0.5): "
      f"`model_inputs` changed in {p.get('model_inputs_changed')} of {p.get('records')} records and the projection changed in {p.get('projections_changed')}. "
      "Nothing after `as_of` leaks in.\n"
      "Problems found: none requiring a fix. Caveats recorded: the prior weight is the stated ridge-diagonal approximation (ignores recency decay and opponent "
      "coupling, ≈5% at this date); `days_since_last_game` uses the schedule as known when the projection runs.\n")  # fmt: skip
    a("## Reproduce\n")
    a("```bash\n"
      "# archive checkouts (read-only) and a lake built like scripts/prospective/refresh_and_project.py\n"
      "CBB_DATA_DIR=$LAKE python scripts/research/orientation_before_after.py --projections $A/projections-archive --rosters $A/roster-archive \\\n"
      "  --schedule $A/schedule-archive --espn $A/espn-lines-archive --panel $A/kalshi-panel-archive --now 2026-11-10T12:00:00Z \\\n"
      "  --baseline-ref b3203a31 --out research/orientation\n"
      "CBB_DATA_DIR=$LAKE python scripts/prospective/model_inputs_dry_run.py --as-of 2026-11-05T23:06:44.762463Z --version pure-0.2.0 \\\n"
      "  --out research/wave13/model_inputs_dry_run.json\n"
      "python scripts/research/render_orientation_report.py research/orientation research/wave13/model_inputs_dry_run.json research/reports/ORIENTATION_SCORING.md\n```\n")  # fmt: skip
    out.write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
