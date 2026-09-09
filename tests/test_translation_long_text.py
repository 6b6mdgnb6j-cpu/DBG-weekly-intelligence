import unittest
from unittest.mock import patch

import crawler.translator as translator
from crawler.translator import (
    GENERATION_CONFIG_VERSION,
    LocalNLLBProvider,
    TitleTranslator,
    TranslationSanityValidator,
    TranslationUnavailableError,
    _cache_key,
)


class FakeTokenizer:
    src_lang = ""

    def encode(self, text, add_special_tokens=False):
        return [token for token in str(text).split() if token]

    def __call__(self, text, return_tensors=None, truncation=False, max_length=None, add_special_tokens=True):
        ids = self.encode(text)
        if truncation and max_length is not None:
            ids = ids[:max_length]
        return {"input_ids": [ids]}

    def decode(self, ids, skip_special_tokens=True):
        return " ".join(str(token) for token in ids)

    def convert_tokens_to_ids(self, token):
        return 256200


class EchoModel:
    def eval(self):
        return None

    def generate(self, **inputs):
        source = "_".join(inputs["input_ids"][0])
        return [[f"译:{source}"]]


class FailingSecondChunkModel(EchoModel):
    def __init__(self):
        self.calls = 0

    def generate(self, **inputs):
        self.calls += 1
        if self.calls == 2:
            return [[""]]
        return super().generate(**inputs)


def fake_provider(model=None):
    provider = LocalNLLBProvider(local_files_only=True)
    provider.tokenizer = FakeTokenizer()
    provider.model = model or EchoModel()
    provider.forced_bos_token_id = 256200
    return provider


class LongTextTranslationTests(unittest.TestCase):
    def test_short_text_within_budget_uses_one_translation_call(self):
        provider = fake_provider()
        with patch.object(translator, "SOURCE_CHUNK_TOKEN_LIMIT", 10):
            output = provider.translate("short market update")
        self.assertEqual(output, "译:short_market_update")
        self.assertEqual(provider.translation_call_count, 1)
        self.assertEqual(provider.chunked_text_count, 0)

    def test_long_summary_beyond_budget_splits_into_multiple_chunks(self):
        provider = fake_provider()
        with patch.object(translator, "SOURCE_CHUNK_TOKEN_LIMIT", 5):
            output = provider.translate("one two three four five six seven eight")
        self.assertIn("译:one_two_three_four_five", output)
        self.assertIn("译:six_seven_eight", output)
        self.assertEqual(provider.translation_call_count, 2)
        self.assertEqual(provider.chunked_text_count, 1)

    def test_all_long_text_chunks_are_translated_and_joined_in_order(self):
        provider = fake_provider()
        with patch.object(translator, "SOURCE_CHUNK_TOKEN_LIMIT", 3):
            output = provider.translate("alpha beta gamma delta epsilon zeta")
        self.assertEqual(output, "译:alpha_beta_gamma 译:delta_epsilon_zeta")
        self.assertEqual(provider.translated_chunk_count, 2)

    def test_no_source_tail_is_silently_discarded(self):
        provider = fake_provider()
        with patch.object(translator, "SOURCE_CHUNK_TOKEN_LIMIT", 4):
            output = provider.translate("start middle tailtoken")
        self.assertIn("tailtoken", output)

    def test_sentence_boundaries_are_preferred_where_practical(self):
        provider = fake_provider()
        with patch.object(translator, "SOURCE_CHUNK_TOKEN_LIMIT", 3):
            output = provider.translate("First sentence. Second sentence.")
        self.assertEqual(output, "译:First_sentence. 译:Second_sentence.")

    def test_oversized_single_sentence_uses_token_safe_fallback(self):
        provider = fake_provider()
        with patch.object(translator, "SOURCE_CHUNK_TOKEN_LIMIT", 3):
            output = provider.translate("alpha beta gamma delta epsilon")
        self.assertEqual(output, "译:alpha_beta_gamma 译:delta_epsilon")

    def test_one_chunk_failure_in_strict_mode_reports_chunk_failure(self):
        provider = fake_provider(FailingSecondChunkModel())
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        item = {
            "title_original": "短标题",
            "summary": "alpha beta gamma delta epsilon zeta",
            "source": "Source",
        }
        with patch.object(translator, "SOURCE_CHUNK_TOKEN_LIMIT", 3):
            with self.assertRaises(TranslationUnavailableError) as ctx:
                title_translator.translate([item])
        self.assertIn("chunk 2/2", str(ctx.exception))
        self.assertIn("field=summary", str(ctx.exception))

    def test_non_strict_chunk_failure_returns_empty_translation(self):
        provider = fake_provider(FailingSecondChunkModel())
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=False)
        title_translator.cache = {}
        item = {
            "title_original": "短标题",
            "summary": "alpha beta gamma delta epsilon zeta",
            "source": "Source",
        }
        with patch.object(translator, "SOURCE_CHUNK_TOKEN_LIMIT", 3):
            output = title_translator.translate([item])
        self.assertEqual(output[0]["summary_cn"], "")

    def test_full_assembled_translation_is_sanity_validated(self):
        provider = fake_provider()
        seen = {}

        def fake_validate(original, translated, source=""):
            seen["original"] = original
            seen["translated"] = translated
            return translator.ValidationResult(True)

        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        item = {"title_original": "Short title", "summary": "alpha beta gamma delta epsilon zeta", "source": "Source"}
        with patch.object(translator, "SOURCE_CHUNK_TOKEN_LIMIT", 3), patch.object(
            TranslationSanityValidator, "validate_with_reason", side_effect=fake_validate
        ):
            title_translator.translate([item])
        self.assertEqual(seen["original"], "alpha beta gamma delta epsilon zeta")
        self.assertEqual(seen["translated"], "译:alpha_beta_gamma 译:delta_epsilon_zeta")

    def test_long_original_complete_translation_does_not_fail_due_to_length_alone(self):
        original = " ".join(["market"] * 120)
        translated = "市场基础设施监管政策正在推进清算结算机制透明度资本市场跨境合作风险管理效率提升投资者保护安排并支持金融稳定与交易后服务发展，同时增强跨境产品服务和风险监测能力"
        result = TranslationSanityValidator.validate_with_reason(original, translated)
        self.assertTrue(result.valid)

    def test_genuinely_too_short_translation_still_rejects(self):
        original = " ".join(["market"] * 120)
        result = TranslationSanityValidator.validate_with_reason(original, "短")
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "length_ratio_low")

    def test_critical_term_missing_still_rejects_with_reason(self):
        result = TranslationSanityValidator.validate_with_reason("CFTC market rule", "市场规则")
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "critical_term_missing:CFTC")

    def test_bad_terminology_still_rejects_with_reason(self):
        result = TranslationSanityValidator.validate_with_reason("Market update", "外汇清算更新")
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "bad_term:外汇清算")

    def test_validation_reason_api_preserves_is_valid_compatibility(self):
        result = TranslationSanityValidator.validate_with_reason("", "")
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "empty_translation")
        self.assertFalse(TranslationSanityValidator.is_valid("", ""))

    def test_cache_key_changes_with_chunked_pipeline_version(self):
        key = _cache_key("model", "en", "zh", "text", 1)
        self.assertIn("chunked", GENERATION_CONFIG_VERSION)
        self.assertIn("v8", GENERATION_CONFIG_VERSION)
        self.assertEqual(len(key), 64)

    def test_old_invalid_cached_entry_cannot_poison_new_chunked_key(self):
        old_version = "nllb-v1-norepeat-terminology-chunked-v7"
        with patch.object(translator, "GENERATION_CONFIG_VERSION", old_version):
            old_key = _cache_key("model", "en", "zh", "long text", 1)
        new_key = _cache_key("model", "en", "zh", "long text", 1)
        self.assertNotEqual(old_key, new_key)

    def test_intercontinental_exchange_bad_translation_normalizes_to_ice(self):
        normalizer = translator.TerminologyNormalizer()
        normalized, changes = normalizer.normalize(
            "欧元交易所公布市场数据增长",
            "Intercontinental Exchange reports market data growth",
            "洲际交易所",
        )
        self.assertIn("ICE", normalized)
        self.assertNotIn("欧元交易所", normalized)
        self.assertIn("Intercontinental Exchange", changes)
        self.assertTrue(TranslationSanityValidator.is_valid("Intercontinental Exchange reports market data growth", normalized))

    def test_unrelated_euro_exchange_bad_term_still_rejects(self):
        result = TranslationSanityValidator.validate_with_reason("Market data growth", "欧元交易所公布市场数据增长")
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "bad_term:欧元交易所")

    def test_eurex_existing_normalization_remains_unchanged(self):
        normalizer = translator.TerminologyNormalizer()
        normalized, _ = normalizer.normalize("欧元交易所推出清算服务", "Eurex launches clearing service", "Eurex")
        self.assertIn("Eurex", normalized)
        self.assertNotIn("欧元交易所", normalized)

    def test_intercontinental_exchange_rule_is_not_headline_specific(self):
        normalizer = translator.TerminologyNormalizer()
        normalized, _ = normalizer.normalize(
            "欧元交易所宣布新的数据服务",
            "Intercontinental Exchange announces a new data service",
            "洲际交易所",
        )
        self.assertEqual(normalized, "ICE宣布新的数据服务")


if __name__ == "__main__":
    unittest.main()
