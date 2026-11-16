"""Behavioral regression checks for the one local/dual-Mac workflow."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from workflow.live.paths import Concert, read_json, write_json
from workflow.live import pipeline, stages
from workflow.runtime import HostPool, locked
from workflow import sources
from workflow.templates import cover_text, cover_filename, compact_cover_text


class StandardWorkflowTests(unittest.TestCase):
    def test_business_modules_do_not_import_dated_batch_scripts(self):
        import ast
        root = Path(__file__).resolve().parents[1]
        for folder in (root / "workflow", root / "server"):
            for path in folder.rglob("*.py"):
                tree = ast.parse(path.read_text())
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        self.assertNotIn(node.module.split(".")[0], {"work", "posts", "concerts"}, str(path))
                    if isinstance(node, ast.Import):
                        for imported in node.names:
                            self.assertNotIn(imported.name.split(".")[0], {"work", "posts", "concerts"}, str(path))

    def concert(self, root, name="show"):
        concert = Concert(name)
        concert.dir = Path(root) / name
        concert.songs = concert.dir / "songs"
        concert.songs.mkdir(parents=True)
        source = concert.dir / "source.mp4"
        source.write_bytes(b"original")
        write_json(concert.info, {"source_file": str(source)})
        items = [{"idx": i + 1, "name": title, "title": title, "kind": "song"}
                 for i, title in enumerate(("one", "two", "three"))]
        write_json(concert.setlist, {"items": items})
        for item in items:
            directory = concert.song_dir(item)
            directory.mkdir()
            write_json(directory / "song.json", {"slice": [0, 10]})
        return concert

    def test_all_seven_modules_have_one_order_and_explicit_delivery(self):
        self.assertEqual(pipeline.selected_stages(), ["source", "split", "subtitles", "posting", "preview", "covers"])
        self.assertEqual(pipeline.selected_stages("delivery", "delivery"), ["delivery"])
        self.assertEqual(len(stages.STAGES), 7)
        with self.assertRaises(ValueError):
            pipeline.selected_stages("delivery", "subtitles")

    def test_both_macs_dynamically_claim_songs_without_static_partition(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = threading.Event()
            other_finished = threading.Event()
            both = threading.Barrier(2)
            seen = []
            mutex = threading.Lock()
            def execute(job, host):
                with mutex:
                    seen.append((job, host))
                if job in (0, 1):
                    both.wait(3)
                if host == "local" and not first.is_set():
                    first.set()
                    self.assertTrue(other_finished.wait(3))
                else:
                    other_finished.set()
                return job
            results, pending = HostPool(("local", "second-mac"), cache=tmp).run(range(6), execute)
            self.assertFalse(pending)
            self.assertEqual({row[0] for row in seen}, set(range(6)))
            self.assertEqual({row[1] for row in seen[:2]}, {"local", "second-mac"})
            self.assertEqual(len(results), 6)

    def test_pause_finishes_two_current_songs_without_claiming_more(self):
        with tempfile.TemporaryDirectory() as tmp:
            barrier = threading.Barrier(2)
            pause = threading.Event()
            done = []
            def execute(job, host):
                barrier.wait(3)
                pause.set()
                done.append(job)
            results, pending = HostPool(("local", "second"), paused=pause.is_set, cache=tmp).run(range(5), execute)
            self.assertEqual(len(done), 2)
            self.assertEqual(len(results), 2)
            self.assertEqual(len(pending), 3)

    def test_failed_song_is_isolated_and_next_song_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            def execute(job, host):
                if job == 1:
                    raise ValueError("bad source")
                return job
            results, pending = HostPool(cache=tmp).run([1, 2], execute)
            self.assertFalse(pending)
            self.assertEqual([row["status"] for row in results], ["failed", "ready"])

    def test_another_pool_cannot_use_an_owned_machine(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "host-slots" / (hashlib.sha256(b"local").hexdigest()[:24] + ".lock")
            with locked(path):
                results, pending = HostPool(cache=tmp).run(["song"], lambda *args: self.fail("duplicate host"))
            self.assertEqual(results, [])
            self.assertEqual(pending, ["song"])

    def test_source_selection_is_shared_and_explicit_offline_source_never_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            concert = self.concert(tmp)
            chosen = sources.ensure_selection(concert, concert.item("one"))
            self.assertEqual(chosen["slice"], [0, 10])
            self.assertEqual(sources.selection(concert, concert.item("one")), chosen)
            chosen["source"] = str(Path(tmp) / "offline.mkv")
            write_json(concert.dir / "vertical_source.json", {"songs": {"one": chosen}})
            with self.assertRaises(FileNotFoundError):
                sources.selection(concert, concert.item("one"))

    def test_accepted_batch_skips_delivered_held_and_blocked_without_reauditing(self):
        with tempfile.TemporaryDirectory() as tmp:
            concert = self.concert(tmp)
            write_json(Path(tmp) / "priority_status.json", {"show": {"one": "delivered", "two": "available", "three": "available"}})
            config = {"concerts": ["show"], "blocked_jobs": {"show/three": {"reason": "manual hold"}}}
            with patch.object(pipeline, "Concert", return_value=concert), patch.object(
                    pipeline, "products_ready", side_effect=lambda directory, platforms: directory.name == "one"):
                jobs, _ = pipeline.batch_tasks(config, Path(tmp), ["delivery"], {})
            self.assertEqual([row["song"] for row in jobs], ["two"])
            config["awaiting_user_review"] = ["show"]
            with patch.object(pipeline, "Concert", side_effect=AssertionError("held project opened")):
                self.assertEqual(pipeline.batch_tasks(config, Path(tmp), ["delivery"], {})[0], [])

    def test_accepted_delivery_reuses_product_without_calling_encoder_or_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            concert = self.concert(tmp)
            with patch("workflow.delivery_config.products_ready", return_value=True), patch(
                    "workflow.delivery_bundle.write_bundle") as export, patch("workflow.delivery.run") as render:
                result = stages.delivery(concert, concert.item("one"), {"confirmed": True}, "local")
            self.assertEqual(result["status"], "reused")
            export.assert_called_once()
            render.assert_not_called()

    def test_worker_records_stage_timings_and_stops_at_pending_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            concert = self.concert(tmp)
            task = Path(tmp) / "task.json"
            write_json(task, {"concert": "show", "song": "one", "stages": ["covers", "delivery"], "options": {}})
            with patch.object(pipeline, "Concert", return_value=concert), patch.object(
                    pipeline, "perform", return_value={"status": "waiting_for_review"}) as perform:
                row = pipeline.worker(task, "second")
            self.assertEqual(row["status"], "waiting_for_review")
            self.assertEqual(row["host"], "second")
            self.assertGreaterEqual(row["elapsed_seconds"], 0)
            self.assertIn("elapsed_seconds", row["stages"]["covers"])
            perform.assert_called_once()

    def test_invalid_final_posting_copy_keeps_manual_text_and_allows_preview(self):
        from workflow.templates import posting_issues
        self.assertTrue(posting_issues({"标题": "人工标题", "简介": "人工短简介", "标签": ["人工标签"]}))
        with tempfile.TemporaryDirectory() as tmp:
            concert = self.concert(tmp)
            task = Path(tmp) / "task.json"
            write_json(task, {"concert": "show", "song": "one", "stages": ["posting", "preview"], "options": {}})
            with patch.object(pipeline, "Concert", return_value=concert), patch.object(pipeline, "perform",
                    side_effect=[{"status": "needs_review", "issues": ["简介不足"]}, {}]) as perform:
                row = pipeline.worker(task, "local")
            self.assertEqual(row["status"], "waiting_for_review")
            self.assertEqual(perform.call_count, 2)
            self.assertIn("preview", row["stages"])

    def test_paused_batch_does_not_remove_marker_or_start_workers(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp)
            write_json(batch / "queue.json", {"projects": []})
            (batch / "PAUSED").write_text("user pause")
            with patch.object(pipeline, "HostPool", side_effect=AssertionError("started")):
                self.assertEqual(pipeline.run_batch(batch, ["delivery"], {})["status"], "paused")
            self.assertTrue((batch / "PAUSED").is_file())

    def test_cover_text_and_filename_do_not_reuse_the_posting_title(self):
        self.assertEqual(cover_text("Royals", "贵族", "Lorde", "ACL音乐节2026"), {
            "song": "Royals", "song_zh": "贵族", "en": "LORDE", "event": "ACL音乐节2026", "subtitles": "中英字幕"})
        self.assertEqual(cover_filename("bili", "16x9", "2611162100", ".PNG"), "bili_ai_16x9_2611162100.png")
        self.assertEqual(compact_cover_text("Royals", "洛德 Lorde", "ACL音乐节2026"),
                         {"title": "Royals", "subtitle": "洛德 Lorde · ACL音乐节2026"})

    def test_local_selection_overrides_a_batch_remote_machine(self):
        from workflow.live.__main__ import main
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp)
            write_json(batch / "queue.json", {"remote": "secondary", "projects": []})
            with patch("workflow.live.__main__.run_batch", return_value={"status": "ready"}) as run:
                main(["run", "--batch", str(batch), "--from", "delivery", "--to", "delivery", "--local"])
            self.assertEqual(run.call_args.args[2]["remote"], "")

    def test_batch_dispatches_the_same_standard_worker_on_both_macs(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            concert = self.concert(root)
            batch = root / "batch"
            batch.mkdir()
            write_json(batch / "queue.json", {"projects": [{"concert": "show"}], "remote": "secondary"})
            ready = set()
            seen = set()
            mutex = threading.Lock()
            barrier = threading.Barrier(2)
            def subprocess_run(args, **kwargs):
                self.assertEqual(args[2:5], ["-m", "workflow.live", "worker"])
                path = Path(args[5])
                task = read_json(path)
                host = args[-1]
                with mutex:
                    first = host not in seen
                    seen.add(host)
                if first:
                    barrier.wait(3)
                ready.add(task["song"])
                write_json(path.parent / "result.json", {"status": "ready", "host": host, "song": task["song"]})
                return SimpleNamespace(returncode=0)
            with patch.object(pipeline, "ROOT", root), patch.object(pipeline, "Concert", return_value=concert), patch.object(
                    pipeline, "existing_workers", return_value={}), patch.object(pipeline, "write_collections"), patch.object(
                    pipeline, "products_ready", side_effect=lambda path, platforms: path.name in ready), patch.object(
                    pipeline.subprocess, "run", side_effect=subprocess_run), patch.object(
                    pipeline, "HostPool", side_effect=lambda *args, **kwargs: HostPool(*args, cache=root / "cache", **kwargs)):
                result = pipeline.run_batch(batch, ["delivery"], {"confirmed": True})
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["completed"], 3)
            self.assertEqual(seen, {"local", "secondary"})
            self.assertEqual(set(read_json(batch / "priority_status.json")["show"].values()), {"delivered"})

    def test_a_tag_only_update_preserves_a_complete_introduction(self):
        from workflow.live.package import draft_meta
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            concert = self.concert(tmp)
            directory = concert.song_dir(concert.item("one"))
            body = {"song": "歌曲正文。" * 125, "performance": "演出正文。" * 125, "lyrics": "意象正文。" * 125}
            write_json(directory / "post_draft.json", {"title": "confirmed", "intro": body, "tags": ["one"]})
            tags = [f"相关标签{n}" for n in range(12)]
            with patch("workflow.make_meta.generate_tags", return_value=tags), patch(
                    "workflow.make_meta.generate_intro", side_effect=AssertionError("rewrote intro")), patch(
                    "workflow.live.package.post_title", return_value="confirmed"):
                draft_meta(concert, concert.item("one"), {}, SimpleNamespace(force=False))
            draft = read_json(directory / "post_draft.json")
            self.assertEqual(draft["intro"], body)
            self.assertEqual(draft["tags"], tags)

    def test_selected_cover_does_not_require_other_songs_reference_plans(self):
        with tempfile.TemporaryDirectory() as tmp:
            concert = self.concert(tmp)
            write_json(concert.dir / "fibo-cover-plan.json", {"one": {"reference": "one.jpg"}})
            def cover(queue, *args, **kwargs):
                self.assertEqual(read_json(queue), [{"slug": "show", "name": "one"}])
                write_json(queue.parent / "dual-cover-status.json", {"show/one": {"status": "released"}})
            with patch("workflow.ai_cover.reviewed_revision", return_value=None), patch.object(
                    stages, "preview"), patch("workflow.covers.run", side_effect=cover), patch(
                    "workflow.fibo_reference.reselect", side_effect=AssertionError("changed chosen reference")):
                stages.covers(concert, concert.item("one"), {"model": "existing-model"}, "local")

    def test_splitting_does_not_load_a_full_concert_separator(self):
        with tempfile.TemporaryDirectory() as tmp:
            concert = self.concert(tmp)
            def locate(*args):
                write_json(concert.segments, {"items": [dict(item, start=0, end=10) for item in concert.song_items()]})
            with patch("workflow.live.setlist.stage_setlist"), patch("workflow.live.lyrics.stage_lyrics"), patch(
                    "workflow.live.segment.stage_segment", side_effect=locate), patch(
                    "workflow.live.util.run", side_effect=AssertionError("whole-show model")):
                stages.split(concert, {})
            self.assertTrue(concert.segments.is_file())

    def test_collection_export_preserves_the_submission_contract(self):
        from workflow.bili_collection import storage_path
        with tempfile.TemporaryDirectory() as tmp:
            concert = self.concert(tmp)
            directory = concert.song_dir(concert.item("one"))
            products = directory / "products"
            products.mkdir()
            (products / "video.mp4").write_bytes(b"finished")
            write_json(products / "products.json", {"status": "ready", "run_id": "finished-run", "items": [
                {"platform": "bilibili", "status": "ready", "file": "video.mp4"}]})
            write_json(directory / "delivery_bundle.json", {"bilibili": {"合集显示名称": "One 第一首"}})
            metadata = storage_path(concert, "show")
            metadata.parent.mkdir(parents=True)
            write_json(metadata, {"title": "正式合集名", "cover_path": "/approved/cover.jpg"})
            with patch.object(pipeline, "Concert", return_value=concert):
                pipeline.write_collections(Path(tmp), {}, {"show": {"one": "delivered"}})
            row = read_json(Path(tmp) / "collections.json")["collections"][0]
            self.assertEqual(row["title"], "正式合集名")
            self.assertEqual(row["cover_path"], "/approved/cover.jpg")
            self.assertEqual(row["tracks"][0]["title"], "One 第一首")
            self.assertEqual(row["tracks"][0]["run_id"], "finished-run")
            self.assertEqual(row["tracks"][0]["status"], "ready")
            self.assertEqual(row["tracks"][0]["input_video_path"], str((products / "video.mp4").resolve()))


if __name__ == "__main__":
    unittest.main()
