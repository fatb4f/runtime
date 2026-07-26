#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

from codex_profile.cli import main as cli_main
from codex_profile.collector import ingest_rollouts
from codex_profile.adapters.usage import (
    ADAPTER_DIGEST,
    ADAPTER_ID,
    ADAPTER_VERSION,
    LEGACY_ADAPTER_DIGEST,
    LEGACY_ADAPTER_VERSION,
    adapt_rollout_record,
)
from codex_profile.sources.rollout import iter_complete_records, stable_source_id
from codex_profile.storage import ProfileStorage


def usage(total: int, input_tokens: int, output_tokens: int, cached: int = 0, reasoning: int = 0) -> dict:
    return {
        "total_tokens": total,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning,
    }


def token_event(timestamp: str, *, total: dict | None = None, last: dict | None = None) -> dict:
    info: dict = {}
    if total is not None:
        info["total_token_usage"] = total
    if last is not None:
        info["last_token_usage"] = last
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {"type": "token_count", "info": info},
    }


def session_meta() -> dict:
    return {
        "timestamp": "2026-07-18T00:00:00Z",
        "type": "session_meta",
        "payload": {"cwd": "/home/_404/src/dotfiles"},
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


class IngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sessions = self.root / "sessions"
        self.sessions.mkdir()
        self.rollout = self.sessions / "session.jsonl"
        self.database = self.root / "profile.duckdb"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def storage(self) -> ProfileStorage:
        return ProfileStorage(self.database)

    def test_ingesting_same_rollout_twice_is_idempotent(self) -> None:
        write_jsonl(self.rollout, [
            session_meta(),
            token_event("2026-07-18T00:01:00Z", last=usage(10, 8, 2)),
        ])
        storage = self.storage()
        source_id = stable_source_id(self.rollout)
        try:
            first = ingest_rollouts(root=self.root, repo="dotfiles", storage=storage)
            checkpoint = storage.get_source_checkpoint(source_id, 0)
            second = ingest_rollouts(root=self.root, repo="dotfiles", storage=storage)
            self.assertEqual(first.counts.raw_inserted, 2)
            self.assertEqual(first.counts.normalized_inserted, 1)
            self.assertEqual(second.active_sources, ((source_id, 0),))
            self.assertEqual(second.counts.raw_inserted, 0)
            self.assertEqual(second.counts.normalized_inserted, 0)
            self.assertEqual(storage.get_source_checkpoint(source_id, 0), checkpoint)
            self.assertEqual(storage.table_count("raw_rollout_observations"), 2)
            self.assertEqual(storage.table_count("normalized_usage_observations"), 1)
        finally:
            storage.close()

    def test_incremental_append_admits_exactly_one_new_record(self) -> None:
        write_jsonl(self.rollout, [session_meta()])
        storage = self.storage()
        source_id = stable_source_id(self.rollout)
        try:
            ingest_rollouts(root=self.root, repo="dotfiles", storage=storage)
            with self.rollout.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(token_event("2026-07-18T00:01:00Z", last=usage(10, 8, 2))) + "\n")
            result = ingest_rollouts(root=self.root, repo="dotfiles", storage=storage)
            self.assertEqual(result.active_sources, ((source_id, 0),))
            self.assertEqual(result.counts.raw_inserted, 1)
            self.assertEqual(result.counts.normalized_inserted, 1)
            self.assertEqual(storage.table_count("raw_rollout_observations"), 2)
        finally:
            storage.close()

    def test_truncation_below_watermark_uses_new_generation(self) -> None:
        write_jsonl(self.rollout, [
            session_meta(),
            token_event("2026-07-18T00:01:00Z", last=usage(10, 8, 2)),
        ])
        storage = self.storage()
        source_id = stable_source_id(self.rollout)
        try:
            first = ingest_rollouts(root=self.root, repo="dotfiles", storage=storage)
            self.assertEqual(first.counts.raw_inserted, 2)
            self.assertGreater(storage.get_watermark(source_id, 0), 0)

            write_jsonl(self.rollout, [session_meta()])
            second = ingest_rollouts(root=self.root, repo="dotfiles", storage=storage)
            self.assertEqual(second.active_sources, ((source_id, 1),))
            self.assertEqual(second.counts.raw_inserted, 1)
            self.assertGreater(storage.get_watermark(source_id, 1), 0)
            self.assertEqual(storage.table_count("raw_rollout_observations"), 3)
            same_offset = storage.connection.execute(
                """
                SELECT count(*)
                FROM raw_rollout_observations
                WHERE source_id = ? AND source_offset = 0
                """,
                [source_id],
            ).fetchone()
            self.assertEqual(int(same_offset[0]), 2)
        finally:
            storage.close()

    def test_same_path_replacement_larger_than_watermark_uses_new_generation(self) -> None:
        write_jsonl(self.rollout, [session_meta()])
        storage = self.storage()
        source_id = stable_source_id(self.rollout)
        try:
            ingest_rollouts(root=self.root, repo="dotfiles", storage=storage)
            replacement = self.sessions / "replacement.jsonl"
            write_jsonl(replacement, [
                session_meta(),
                token_event("2026-07-18T00:01:00Z", last=usage(10, 8, 2)),
                token_event("2026-07-18T00:02:00Z", last=usage(5, 4, 1)),
            ])
            replacement.replace(self.rollout)

            result = ingest_rollouts(root=self.root, repo="dotfiles", storage=storage)
            self.assertEqual(result.active_sources, ((source_id, 1),))
            self.assertEqual(result.counts.raw_inserted, 3)
            self.assertEqual(result.counts.normalized_inserted, 2)
            self.assertEqual(storage.table_count("raw_rollout_observations"), 4)
        finally:
            storage.close()

    def test_truncate_then_regrow_uses_anchor_mismatch_generation(self) -> None:
        write_jsonl(self.rollout, [
            session_meta(),
            token_event("2026-07-18T00:01:00Z", last=usage(10, 8, 2)),
        ])
        storage = self.storage()
        source_id = stable_source_id(self.rollout)
        try:
            ingest_rollouts(root=self.root, repo="dotfiles", storage=storage)
            old_watermark = storage.get_watermark(source_id, 0)
            with self.rollout.open("w", encoding="utf-8") as handle:
                for row in [
                    {
                        "timestamp": "2026-07-18T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"cwd": "/home/_404/src/dotfiles", "replacement": True},
                    },
                    token_event("2026-07-18T00:03:00Z", last=usage(20, 15, 5)),
                    token_event("2026-07-18T00:04:00Z", last=usage(7, 6, 1)),
                ]:
                    handle.write(json.dumps(row, sort_keys=True) + "\n")
            self.assertGreater(self.rollout.stat().st_size, old_watermark)

            result = ingest_rollouts(root=self.root, repo="dotfiles", storage=storage)
            self.assertEqual(result.active_sources, ((source_id, 1),))
            self.assertEqual(result.counts.raw_inserted, 3)
            self.assertEqual(storage.table_count("raw_rollout_observations"), 5)
        finally:
            storage.close()

    def test_incomplete_replacement_does_not_advance_new_watermark(self) -> None:
        write_jsonl(self.rollout, [session_meta()])
        storage = self.storage()
        source_id = stable_source_id(self.rollout)
        try:
            ingest_rollouts(root=self.root, repo="dotfiles", storage=storage)
            replacement = self.sessions / "replacement.jsonl"
            replacement.write_text(
                json.dumps(token_event("2026-07-18T00:01:00Z", last=usage(10, 8, 2))),
                encoding="utf-8",
            )
            replacement.replace(self.rollout)

            result = ingest_rollouts(root=self.root, repo="", storage=storage)
            self.assertEqual(result.active_sources, ((source_id, 1),))
            self.assertEqual(result.counts.raw_inserted, 0)
            self.assertEqual(storage.get_watermark(source_id, 1), 0)
            self.assertEqual(storage.table_count("raw_rollout_observations"), 1)
        finally:
            storage.close()

    def test_rotation_followed_by_append_continues_new_generation(self) -> None:
        write_jsonl(self.rollout, [
            session_meta(),
            token_event("2026-07-18T00:01:00Z", last=usage(10, 8, 2)),
        ])
        storage = self.storage()
        source_id = stable_source_id(self.rollout)
        try:
            ingest_rollouts(root=self.root, repo="dotfiles", storage=storage)
            self.rollout.replace(self.sessions / "session.jsonl.1")
            write_jsonl(self.rollout, [session_meta()])
            rotated = ingest_rollouts(root=self.root, repo="dotfiles", storage=storage)
            self.assertEqual(rotated.active_sources, ((source_id, 1),))
            self.assertEqual(rotated.counts.raw_inserted, 1)

            with self.rollout.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(token_event("2026-07-18T00:02:00Z", last=usage(5, 4, 1))) + "\n")
            appended = ingest_rollouts(root=self.root, repo="dotfiles", storage=storage)
            self.assertEqual(appended.active_sources, ((source_id, 1),))
            self.assertEqual(appended.counts.raw_inserted, 1)
            self.assertEqual(appended.counts.normalized_inserted, 1)
            self.assertEqual(storage.table_count("raw_rollout_observations"), 4)
        finally:
            storage.close()

    def test_rotation_between_yield_and_admission_restarts_at_replacement(self) -> None:
        write_jsonl(self.rollout, [
            session_meta(),
            token_event("2026-07-18T00:01:00Z", last=usage(10, 8, 2)),
        ])
        replacement = self.root / "replacement.jsonl"
        write_jsonl(replacement, [
            {**session_meta(), "replacement": True},
            token_event("2026-07-18T00:02:00Z", last=usage(20, 15, 5)),
        ])
        storage = self.storage()
        source_id = stable_source_id(self.rollout)
        records_adapted = 0

        def rotate_before_second_admission(record, state=None):
            nonlocal records_adapted
            records_adapted += 1
            adapted = adapt_rollout_record(record, state)
            if records_adapted == 2:
                replacement.replace(self.rollout)
            return adapted

        try:
            with patch("codex_profile.collector.adapt_rollout_record", side_effect=rotate_before_second_admission):
                result = ingest_rollouts(root=self.root, repo="dotfiles", storage=storage)

            self.assertEqual(result.active_sources, ((source_id, 0), (source_id, 1)))
            counts = storage.connection.execute(
                """
                SELECT source_generation, count(*)
                FROM raw_rollout_observations
                WHERE source_id = ?
                GROUP BY source_generation
                ORDER BY source_generation
                """,
                [source_id],
            ).fetchall()
            self.assertEqual(counts, [(0, 1), (1, 2)])
            self.assertEqual(storage.get_watermark(source_id, 0), len(json.dumps(session_meta(), sort_keys=True)) + 1)
            self.assertEqual(storage.summary()["tokens"]["total"], 20)
        finally:
            storage.close()

    def test_incomplete_tail_is_ignored_until_completed(self) -> None:
        self.rollout.write_text(json.dumps(session_meta()) + "\n", encoding="utf-8")
        partial = json.dumps(token_event("2026-07-18T00:01:00Z", last=usage(10, 8, 2)))
        with self.rollout.open("a", encoding="utf-8") as handle:
            handle.write(partial)
        storage = self.storage()
        try:
            first = ingest_rollouts(root=self.root, repo="dotfiles", storage=storage)
            self.assertEqual(first.counts.raw_inserted, 1)
            self.assertEqual(storage.table_count("normalized_usage_observations"), 0)
            with self.rollout.open("a", encoding="utf-8") as handle:
                handle.write("\n")
            second = ingest_rollouts(root=self.root, repo="dotfiles", storage=storage)
            self.assertEqual(second.counts.raw_inserted, 1)
            self.assertEqual(second.counts.normalized_inserted, 1)
        finally:
            storage.close()

    def test_failed_transaction_does_not_advance_watermark(self) -> None:
        write_jsonl(self.rollout, [session_meta()])
        storage = self.storage()
        source_id = stable_source_id(self.rollout)
        try:
            first = ingest_rollouts(root=self.root, repo="dotfiles", storage=storage)
            self.assertEqual(first.counts.raw_inserted, 1)
            checkpoint = storage.get_source_checkpoint(source_id, 0)
            failed_offset = storage.get_watermark(source_id, 0)
            with self.rollout.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(token_event("2026-07-18T00:01:00Z", last=usage(10, 8, 2))) + "\n")

            with self.assertRaises(RuntimeError):
                ingest_rollouts(
                    root=self.root,
                    repo="dotfiles",
                    storage=storage,
                    fail_after_raw_at=(source_id, 0, failed_offset),
                )
            self.assertEqual(storage.table_count("raw_rollout_observations"), 1)
            self.assertEqual(storage.get_source_checkpoint(source_id, 0), checkpoint)
            result = ingest_rollouts(root=self.root, repo="dotfiles", storage=storage)
            self.assertEqual(result.counts.raw_inserted, 1)
            self.assertGreater(storage.get_watermark(source_id, 0), failed_offset)
        finally:
            storage.close()

    def test_storage_rejects_non_collector_writer(self) -> None:
        with self.assertRaises(PermissionError):
            ProfileStorage(self.database, writer_id="reporter")
        write_jsonl(self.rollout, [session_meta()])
        storage = self.storage()
        try:
            ingest_rollouts(root=self.root, repo="dotfiles", storage=storage)
        finally:
            storage.close()
        reader = ProfileStorage(self.database, readonly=True)
        try:
            self.assertEqual(reader.summary()["raw_observations"], 1)
            source_id = stable_source_id(self.rollout)
            record = next(iter_complete_records(self.rollout))
            adapted = adapt_rollout_record(record)
            with self.assertRaises(PermissionError):
                reader.admit(adapted)
            self.assertEqual(reader.get_watermark(source_id, 0), len(json.dumps(session_meta(), sort_keys=True)) + 1)
        finally:
            reader.close()

    def test_strict_cli_returns_nonzero_for_invalid_accounting(self) -> None:
        write_jsonl(self.rollout, [
            session_meta(),
            token_event("2026-07-18T00:01:00Z", last=usage(10, 5, 5, cached=6)),
        ])
        status = cli_main([
            "ingest",
            "--root",
            str(self.root),
            "--repo",
            "dotfiles",
            "--database",
            str(self.database),
            "--strict",
        ])
        self.assertEqual(status, 3)
        second_status = cli_main([
            "ingest",
            "--root",
            str(self.root),
            "--repo",
            "dotfiles",
            "--database",
            str(self.database),
            "--strict",
        ])
        self.assertEqual(second_status, 3)
        storage = self.storage()
        try:
            self.assertEqual(storage.table_count("collector_diagnostics"), 1)
            self.assertEqual(storage.table_count("normalized_usage_observations"), 0)
        finally:
            storage.close()

    def test_two_invalid_token_surfaces_do_not_collide(self) -> None:
        write_jsonl(self.rollout, [
            session_meta(),
            token_event(
                "2026-07-18T00:01:00Z",
                last=usage(10, 5, 5, cached=6),
                total=usage(10, 5, 5, cached=6),
            ),
        ])
        status = cli_main([
            "ingest",
            "--root",
            str(self.root),
            "--repo",
            "dotfiles",
            "--database",
            str(self.database),
            "--strict",
        ])
        self.assertEqual(status, 3)
        storage = self.storage()
        try:
            self.assertEqual(storage.table_count("raw_rollout_observations"), 2)
            self.assertEqual(storage.table_count("collector_diagnostics"), 2)
            self.assertEqual(storage.table_count("normalized_usage_observations"), 0)
        finally:
            storage.close()

    def test_malformed_token_values_are_rejected_before_normalization(self) -> None:
        cases = [
            {"total_tokens": -1, "input_tokens": 8, "output_tokens": 2},
            {"total_tokens": True, "input_tokens": 8, "output_tokens": 2},
            {"total_tokens": "ten", "input_tokens": 8, "output_tokens": 2},
            {"total_tokens": 10, "input_tokens": "bad", "output_tokens": 2},
        ]
        for index, last_usage in enumerate(cases):
            with self.subTest(index=index):
                rollout = self.sessions / f"malformed-{index}.jsonl"
                database = self.root / f"malformed-{index}.duckdb"
                write_jsonl(rollout, [
                    session_meta(),
                    token_event("2026-07-18T00:01:00Z", last=last_usage),
                ])
                status = cli_main([
                    "ingest",
                    "--root",
                    str(rollout),
                    "--repo",
                    "dotfiles",
                    "--database",
                    str(database),
                    "--strict",
                ])
                self.assertEqual(status, 3)
                storage = ProfileStorage(database)
                try:
                    self.assertEqual(storage.table_count("raw_rollout_observations"), 2)
                    self.assertEqual(storage.table_count("collector_diagnostics"), 1)
                    self.assertEqual(storage.table_count("normalized_usage_observations"), 0)
                finally:
                    storage.close()

    def test_strict_cli_records_unknown_shape_and_missing_attribution(self) -> None:
        self.rollout.write_text('[1, 2, 3]\n{"type": "message"}\n', encoding="utf-8")
        status = cli_main([
            "ingest",
            "--root",
            str(self.root),
            "--database",
            str(self.database),
            "--strict",
        ])
        self.assertEqual(status, 3)
        storage = self.storage()
        try:
            codes = {
                row[0]
                for row in storage.connection.execute(
                    "SELECT code FROM collector_diagnostics ORDER BY code"
                ).fetchall()
            }
            self.assertIn("rollout.unknown-shape", codes)
            self.assertIn("rollout.missing-event-timestamp", codes)
        finally:
            storage.close()

    def test_analyze_and_export_cli_emit_summary(self) -> None:
        write_jsonl(self.rollout, [
            session_meta(),
            token_event("2026-07-18T00:01:00Z", last=usage(10, 8, 2, cached=3)),
        ])
        self.assertEqual(cli_main([
            "ingest",
            "--root",
            str(self.root),
            "--repo",
            "dotfiles",
            "--database",
            str(self.database),
        ]), 0)
        self.assertEqual(cli_main(["analyze", "--database", str(self.database)]), 0)
        out = self.root / "export"
        self.assertEqual(cli_main(["export", "--database", str(self.database), "--out", str(out)]), 0)
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["tokens"]["total"], 10)
        self.assertEqual(summary["tokens"]["fresh_input"], 5)
        self.assertTrue((out / "summary.md").exists())
        self.assertTrue((out / "summary.csv").exists())

    def test_legacy_normalized_rows_are_reprojected_under_active_adapter(self) -> None:
        write_jsonl(self.rollout, [
            session_meta(),
            token_event("2026-07-18T00:01:00Z", last=usage(10, 8, 2, cached=3)),
        ])
        storage = self.storage()
        try:
            ingest_rollouts(root=self.root, repo="dotfiles", storage=storage)
            storage.connection.execute(
                """
                CREATE TABLE normalized_usage_observations_legacy AS
                SELECT
                  source_id,
                  source_generation,
                  source_offset,
                  event_timestamp,
                  event_kind,
                  normalization_method,
                  usage_observation_index,
                  reported_input_tokens,
                  cached_input_tokens,
                  fresh_input_tokens,
                  output_tokens,
                  reasoning_output_tokens,
                  total_tokens
                FROM normalized_usage_observations
                """
            )
            storage.connection.execute("DROP TABLE normalized_usage_observations")
            storage.connection.execute(
                "ALTER TABLE normalized_usage_observations_legacy RENAME TO normalized_usage_observations"
            )
            storage.connection.execute("DROP TABLE adapter_projection_admissions")
        finally:
            storage.close()

        storage = self.storage()
        try:
            migrated = storage.connection.execute(
                """
                SELECT adapter_id, adapter_version, adapter_digest, count(*)
                FROM normalized_usage_observations
                GROUP BY adapter_id, adapter_version, adapter_digest
                """
            ).fetchall()
            self.assertEqual(
                migrated,
                [(ADAPTER_ID, LEGACY_ADAPTER_VERSION, LEGACY_ADAPTER_DIGEST, 1)],
            )
            self.assertEqual(storage.summary()["normalized_usage_observations"], 0)
            self.assertEqual(storage.summary()["tokens"]["total"], 0)

            replayed = ingest_rollouts(root=self.root, repo="dotfiles", storage=storage)
            self.assertEqual(replayed.counts.raw_inserted, 0)
            self.assertEqual(replayed.counts.normalized_inserted, 1)
            versions = storage.connection.execute(
                """
                SELECT adapter_id, adapter_version, adapter_digest, count(*)
                FROM normalized_usage_observations
                GROUP BY adapter_id, adapter_version, adapter_digest
                ORDER BY adapter_version
                """
            ).fetchall()
            self.assertEqual(
                versions,
                [
                    (ADAPTER_ID, LEGACY_ADAPTER_VERSION, LEGACY_ADAPTER_DIGEST, 1),
                    (ADAPTER_ID, ADAPTER_VERSION, ADAPTER_DIGEST, 1),
                ],
            )
            self.assertEqual(storage.summary()["normalized_usage_observations"], 1)
            self.assertEqual(storage.summary()["tokens"]["total"], 10)

            idempotent = ingest_rollouts(root=self.root, repo="dotfiles", storage=storage)
            self.assertEqual(idempotent.counts.normalized_inserted, 0)
            self.assertEqual(storage.table_count("normalized_usage_observations"), 2)
        finally:
            storage.close()


if __name__ == "__main__":
    unittest.main()
