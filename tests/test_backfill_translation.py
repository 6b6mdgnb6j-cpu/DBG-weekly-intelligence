import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import backfill_translation
import run_weekly


class FakeTranslator:
    def _translate_text(self, text, source):
        if "fail" in text.lower():
            return ""
        return f"中文:{text}"


def item(title, summary="English summary", **overrides):
    value = {
        "title_original": title,
        "title_en": title,
        "summary": summary,
        "summary_original": summary,
        "summary_en": summary,
        "date": "2020-01-01",
        "url": f"https://example.test/{title[:8]}",
        "source": "Source",
        "category": "Macro",
        "relevance_score": 10,
    }
    value.update(overrides)
    return value


class TranslationBackfillTests(unittest.TestCase):
    def payload(self, items):
        return {
            "week_start": "2020-01-01",
            "week_end": "2020-01-07",
            "source_count": 5,
            "registered_source_count": 5,
            "item_count": len(items),
            "items": items,
            "highlights": items[:1],
        }

    def test_backfill_preserves_non_language_fields(self):
        source = self.payload([item("Market infrastructure update")])
        candidate, report = backfill_translation.backfill_payload(source, FakeTranslator())

        self.assertEqual(candidate["translation_mode"], "bilingual")
        self.assertEqual(candidate["item_count"], source["item_count"])
        self.assertEqual(candidate["items"][0]["url"], source["items"][0]["url"])
        self.assertEqual(candidate["items"][0]["date"], source["items"][0]["date"])
        self.assertEqual(candidate["items"][0]["relevance_score"], source["items"][0]["relevance_score"])
        self.assertEqual(report["structural_diff_count"], 0)

    def test_existing_chinese_translation_is_preserved(self):
        source = self.payload(
            [
                item(
                    "Market infrastructure update",
                    title_cn="已有中文标题",
                    summary_cn="已有中文摘要",
                )
            ]
        )
        candidate, report = backfill_translation.backfill_payload(source, FakeTranslator())

        self.assertEqual(candidate["items"][0]["title_cn"], "已有中文标题")
        self.assertEqual(candidate["items"][0]["summary_cn"], "已有中文摘要")
        self.assertEqual(report["title_translated"], 0)
        self.assertEqual(report["summary_translated"], 0)

    def test_english_fallback_title_is_backfilled(self):
        source = self.payload(
            [
                item(
                    "Market infrastructure update",
                    title_cn="Market infrastructure update",
                    summary_cn="English summary",
                )
            ]
        )
        candidate, report = backfill_translation.backfill_payload(source, FakeTranslator())

        self.assertEqual(candidate["items"][0]["title_cn"], "中文:Market infrastructure update")
        self.assertEqual(candidate["items"][0]["summary_cn"], "中文:English summary")
        self.assertEqual(report["title_translated"], 1)
        self.assertEqual(report["summary_translated"], 1)

    def test_translation_failure_does_not_delete_item(self):
        source = self.payload([item("fail title", summary="fail summary")])
        candidate, report = backfill_translation.backfill_payload(source, FakeTranslator())

        self.assertEqual(candidate["item_count"], 1)
        self.assertEqual(len(candidate["items"]), 1)
        self.assertEqual(candidate["items"][0]["title_cn"], "")
        self.assertEqual(candidate["items"][0]["summary_cn"], "")
        self.assertEqual(report["title_failures"], 1)
        self.assertEqual(report["summary_failures"], 1)

    def test_historical_override_applies_only_after_translation_failure(self):
        source = self.payload([item("fail title", summary="fail summary", url="https://example.test/override")])
        overrides = {"https://example.test/override": {"title_cn": "历史标题", "summary_cn": "历史摘要"}}
        candidate, report = backfill_translation.backfill_payload(source, FakeTranslator(), overrides)

        self.assertEqual(candidate["items"][0]["title_cn"], "历史标题")
        self.assertEqual(candidate["items"][0]["summary_cn"], "历史摘要")
        self.assertEqual(report["title_overridden"], 1)
        self.assertEqual(report["summary_overridden"], 1)
        self.assertEqual(report["title_failures"], 0)
        self.assertEqual(report["summary_failures"], 0)

    def test_historical_override_does_not_overwrite_successful_translation(self):
        source = self.payload([item("Market infrastructure update", summary="English summary", url="https://example.test/override")])
        overrides = {"https://example.test/override": {"title_cn": "历史标题", "summary_cn": "历史摘要"}}
        candidate, report = backfill_translation.backfill_payload(source, FakeTranslator(), overrides)

        self.assertEqual(candidate["items"][0]["title_cn"], "中文:Market infrastructure update")
        self.assertEqual(candidate["items"][0]["summary_cn"], "中文:English summary")
        self.assertEqual(report["title_overridden"], 0)
        self.assertEqual(report["summary_overridden"], 0)

    def test_existing_chinese_translation_beats_historical_override(self):
        source = self.payload(
            [
                item(
                    "fail title",
                    summary="fail summary",
                    url="https://example.test/override",
                    title_cn="已有中文标题",
                    summary_cn="已有中文摘要",
                )
            ]
        )
        overrides = {"https://example.test/override": {"title_cn": "历史标题", "summary_cn": "历史摘要"}}
        candidate, report = backfill_translation.backfill_payload(source, FakeTranslator(), overrides)

        self.assertEqual(candidate["items"][0]["title_cn"], "已有中文标题")
        self.assertEqual(candidate["items"][0]["summary_cn"], "已有中文摘要")
        self.assertEqual(report["title_overridden"], 0)
        self.assertEqual(report["summary_overridden"], 0)

    def test_unknown_url_has_no_override(self):
        source = self.payload([item("fail title", summary="fail summary", url="https://example.test/unknown")])
        overrides = {"https://example.test/override": {"title_cn": "历史标题", "summary_cn": "历史摘要"}}
        candidate, report = backfill_translation.backfill_payload(source, FakeTranslator(), overrides)

        self.assertEqual(candidate["items"][0]["title_cn"], "")
        self.assertEqual(candidate["items"][0]["summary_cn"], "")
        self.assertEqual(report["title_failures"], 1)
        self.assertEqual(report["summary_failures"], 1)

    def test_empty_original_summary_remains_empty(self):
        source = self.payload([item("Market infrastructure update", summary="", summary_original="", summary_en="", summary_cn="")])
        overrides = {source["items"][0]["url"]: {"summary_cn": "不应使用"}}
        candidate, report = backfill_translation.backfill_payload(source, FakeTranslator(), overrides)

        self.assertEqual(candidate["items"][0]["summary_original"], "")
        self.assertEqual(candidate["items"][0]["summary_cn"], "")
        self.assertEqual(report["summary_overridden"], 0)

    def test_historical_override_preserves_structural_fields(self):
        source = self.payload([item("fail title", summary="fail summary", url="https://example.test/override")])
        overrides = {"https://example.test/override": {"title_cn": "历史标题", "summary_cn": "历史摘要"}}
        candidate, report = backfill_translation.backfill_payload(source, FakeTranslator(), overrides)

        self.assertEqual(candidate["items"][0]["url"], source["items"][0]["url"])
        self.assertEqual(candidate["items"][0]["date"], source["items"][0]["date"])
        self.assertEqual(candidate["items"][0]["category"], source["items"][0]["category"])
        self.assertEqual(candidate["items"][0]["relevance_score"], source["items"][0]["relevance_score"])
        self.assertEqual(report["structural_diff_count"], 0)

    def test_malformed_override_file_fails_safely(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not valid json", encoding="utf-8")

            self.assertEqual(backfill_translation.load_historical_overrides(path), {})

    def test_production_run_weekly_does_not_load_historical_overrides(self):
        source = Path(run_weekly.__file__).read_text(encoding="utf-8")

        self.assertNotIn("historical_translation_overrides", source)

    def test_highlights_reuse_translated_item_without_reselection(self):
        source = self.payload([item("Market infrastructure update")])
        source["highlights"][0]["highlight_score"] = 12
        candidate, _ = backfill_translation.backfill_payload(source, FakeTranslator())

        self.assertEqual(len(candidate["highlights"]), 1)
        self.assertEqual(candidate["highlights"][0]["title_cn"], "中文:Market infrastructure update")
        self.assertEqual(candidate["highlights"][0]["url"], source["highlights"][0]["url"])
        self.assertEqual(candidate["highlights"][0]["highlight_score"], 12)


if __name__ == "__main__":
    unittest.main()
