import ast
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crawler import collector


class CollectorArtifactModeTests(unittest.TestCase):
    def run_empty_collection(self, tmp, translate=True, output_dir=None, sources=None):
        root = Path(tmp)
        legacy = root / "data" / "news.json"
        log_dir = root / "logs"
        raw_dir = root / "raw"
        with patch.object(collector, "load_sources", return_value=sources or []), patch.object(
            collector, "LOG_DIR", log_dir
        ), patch.object(collector, "RAW_DIR", raw_dir), patch.object(
            collector, "LEGACY_DATA_FILE", legacy
        ), patch.object(
            collector, "apply_relevance", return_value=([], [])
        ), patch.object(
            collector, "dedupe_news", side_effect=lambda items: items
        ), patch.object(
            collector, "cluster_same_event_items", return_value=([], [])
        ), patch.object(
            collector, "apply_competitor_mapping", side_effect=lambda items: items
        ), patch.object(
            collector, "TitleTranslator"
        ) as translator_cls:
            translator_cls.return_value.translate.side_effect = lambda items: items
            return collector.collect_week(
                start_arg="2020-01-06",
                translate=translate,
                output_dir=output_dir or root / "output",
            )

    def test_every_enabled_source_method_has_callable_dispatch(self):
        tree = ast.parse(inspect.getsource(collector.collect_week))
        routes = {}
        for node in ast.walk(tree):
            if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                    and isinstance(node.test.left, ast.Name) and node.test.left.id == "method"
                    and isinstance(node.test.comparators[0], ast.Constant)):
                routes[node.test.comparators[0].value] = node.body[0].value.func.id
        for source in collector.load_sources():
            if source.get("enabled", True):
                with self.subTest(source=source["id"], method=source["method"]):
                    self.assertIn(source["method"], routes)
                    self.assertTrue(callable(getattr(collector, routes[source["method"]], None)))

    def test_enabled_ccp_source_reaches_adapter(self):
        source = next(source for source in collector.load_sources() if source["id"] == "SRC-107")
        self.assertTrue(source["enabled"])
        self.assertEqual(source["method"], "ccp_global_publications")
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            collector, "collect_ccp_global_publications",
            return_value=([], [], {"candidates": 1, "dated_candidates": 1, "target_period_reached": True})
        ) as adapter:
            result = self.run_empty_collection(tmp, sources=[source])
            adapter.assert_called_once()
            self.assertEqual(adapter.call_args.args[0], source)
            statuses = json.loads(Path(result["source_status_path"]).read_text())
            self.assertEqual(statuses[0]["status"], "true_no_updates")

    def test_normal_collection_artifact_marked_bilingual(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_empty_collection(tmp, translate=True)
            payload = json.loads(Path(result["weekly_data_path"]).read_text(encoding="utf-8"))
        self.assertEqual(payload["translation_mode"], "bilingual")

    def test_no_translate_collection_artifact_marked_no_translate(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_empty_collection(tmp, translate=False)
            payload = json.loads(Path(result["weekly_data_path"]).read_text(encoding="utf-8"))
        self.assertEqual(payload["translation_mode"], "no_translate")

    def test_ci_output_dir_does_not_overwrite_production_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            production = root / "output" / "weekly_data_20200106.json"
            production.parent.mkdir(parents=True)
            production.write_text("production artifact", encoding="utf-8")

            result = self.run_empty_collection(root, translate=False, output_dir=root / "output" / "ci" / "20200106")

            self.assertEqual(production.read_text(encoding="utf-8"), "production artifact")
            self.assertEqual(Path(result["weekly_data_path"]).parent, root / "output" / "ci" / "20200106")

    def test_web_source_max_items_still_caps_retained_items_after_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "data" / "news.json"
            log_dir = root / "logs"
            raw_dir = root / "raw"
            source = {
                "id": "SRC-TEST",
                "name": "Mock Web",
                "url": "https://example.test/news",
                "method": "web",
                "enabled": True,
                "max_items": 1,
            }
            filtered = [
                {"source": "Mock Web", "title_original": "Item 1", "url": "https://example.test/1", "date": "2020-01-06"},
                {"source": "Mock Web", "title_original": "Item 2", "url": "https://example.test/2", "date": "2020-01-07"},
                {"source": "Mock Web", "title_original": "Item 3", "url": "https://example.test/3", "date": "2020-01-08"},
            ]
            meta = {
                "candidates": 3,
                "candidates_discovered": 3,
                "candidates_scanned": 3,
                "list_items_with_date": 3,
                "dated_candidates": 3,
                "target_period_reached": True,
                "stopped_reason": "passed_target_start",
            }

            def capture_relevance(items):
                captured.extend(items)
                return items, items

            captured = []
            with patch.object(collector, "load_sources", return_value=[source]), patch.object(
                collector, "LOG_DIR", log_dir
            ), patch.object(collector, "RAW_DIR", raw_dir), patch.object(
                collector, "LEGACY_DATA_FILE", legacy
            ), patch.object(
                collector, "collect_web", return_value=(filtered, filtered, meta)
            ), patch.object(
                collector, "apply_relevance", side_effect=capture_relevance
            ), patch.object(
                collector, "dedupe_news", side_effect=lambda items: items
            ), patch.object(
                collector, "cluster_same_event_items", side_effect=lambda items: (items, [])
            ), patch.object(
                collector, "apply_competitor_mapping", side_effect=lambda items: items
            ):
                result = collector.collect_week(
                    start_arg="2020-01-06",
                    translate=False,
                    output_dir=root / "output",
                )

            payload = json.loads(Path(result["weekly_data_path"]).read_text(encoding="utf-8"))
            self.assertEqual([item["title_original"] for item in captured], ["Item 1"])
            self.assertEqual(payload["item_count"], 1)
            status = json.loads(Path(result["source_status_path"]).read_text(encoding="utf-8"))[0]
            self.assertEqual(status["candidates_scanned"], 3)
            self.assertEqual(status["within_period"], 3)
            self.assertEqual(status["final_items"], 1)


if __name__ == "__main__":
    unittest.main()
