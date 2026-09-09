import unittest
from unittest.mock import Mock, patch

import crawler.translator as translator
from crawler.translator import (
    GENERATION_CONFIG_VERSION,
    LocalNLLBProvider,
    TitleTranslator,
    TranslationSanityValidator,
    TranslationUnavailableError,
    RECOVERY_SOURCE_CHUNK_TOKEN_LIMIT,
    SOURCE_CHUNK_TOKEN_LIMIT,
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


class RecordingProvider:
    model_name = "fake-model"
    last_error = ""
    load_error = ""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []
        self.last_translation_metadata = {}

    def translate(self, text, source_lang="en", target_lang="zh", chunk_token_limit=None):
        self.calls.append(
            {
                "text": text,
                "source_lang": source_lang,
                "target_lang": target_lang,
                "chunk_token_limit": chunk_token_limit,
            }
        )
        output = self.outputs.pop(0) if self.outputs else ""
        self.last_translation_metadata = {
            "chunk_token_limit": chunk_token_limit,
            "chunk_count": 2 if chunk_token_limit == SOURCE_CHUNK_TOKEN_LIMIT else 4,
            "chunk_token_counts": [chunk_token_limit or 0],
            "chunk_output_lengths": [len(output)],
        }
        return output


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
        self.assertIn("v9", GENERATION_CONFIG_VERSION)
        self.assertEqual(len(key), 64)

    def test_old_invalid_cached_entry_cannot_poison_new_recovery_key(self):
        old_version = "nllb-v1-norepeat-terminology-chunked-v8"
        with patch.object(translator, "GENERATION_CONFIG_VERSION", old_version):
            old_key = _cache_key("model", "en", "zh", "long text", 1)
        new_key = _cache_key("model", "en", "zh", "long text", 1)
        self.assertNotEqual(old_key, new_key)

    def test_current_invalid_cached_entry_is_retried_not_returned(self):
        provider = RecordingProvider(["有效中文翻译"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        key = _cache_key(provider.model_name, "en", "zh", "Market infrastructure update", title_translator.normalizer.version)
        title_translator.cache = {key: {"translation": "", "invalid": True, "invalid_reason": "length_ratio_low"}}
        with patch.object(TranslationSanityValidator, "validate_with_reason", return_value=translator.ValidationResult(True)):
            output = title_translator._translate_text("Market infrastructure update", "Source", "title")
        self.assertEqual(output, "有效中文翻译")
        self.assertEqual(len(provider.calls), 1)

    def test_validated_v9_result_is_cached_normally(self):
        provider = RecordingProvider(["市场基础设施更新"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        with patch.object(TranslationSanityValidator, "validate_with_reason", return_value=translator.ValidationResult(True)):
            first = title_translator._translate_text("Market infrastructure update", "Source", "title")
            second = title_translator._translate_text("Market infrastructure update", "Source", "title")
        self.assertEqual(first, "市场基础设施更新")
        self.assertEqual(second, "市场基础设施更新")
        self.assertEqual(len(provider.calls), 1)

    def test_length_ratio_low_triggers_one_recovery_with_smaller_chunks(self):
        original = " ".join(["market"] * 60)
        provider = RecordingProvider(["短", "市场基础设施监管政策清算结算跨境资本市场改革持续推进并保持交易后服务稳定运行"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        with patch.object(
            TranslationSanityValidator,
            "validate_with_reason",
            side_effect=[translator.ValidationResult(False, "length_ratio_low"), translator.ValidationResult(True)],
        ):
            output = title_translator._translate_text(original, "Source", "summary")
        self.assertIn("市场基础设施", output)
        self.assertEqual([call["chunk_token_limit"] for call in provider.calls], [SOURCE_CHUNK_TOKEN_LIMIT, RECOVERY_SOURCE_CHUNK_TOKEN_LIMIT])

    def test_length_ratio_recovery_retranslates_entire_original_and_preserves_order(self):
        original = "alpha beta gamma delta"
        provider = RecordingProvider(["短", "甲 乙 丙 丁"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        with patch.object(
            TranslationSanityValidator,
            "validate_with_reason",
            side_effect=[translator.ValidationResult(False, "length_ratio_low"), translator.ValidationResult(True)],
        ):
            output = title_translator._translate_text(original, "Source", "summary")
        self.assertEqual(output, "甲 乙 丙 丁")
        self.assertEqual([call["text"] for call in provider.calls], [original, original])

    def test_length_ratio_recovery_failure_strict_mode_fails(self):
        provider = RecordingProvider(["短", "仍短"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        with patch.object(
            TranslationSanityValidator,
            "validate_with_reason",
            side_effect=[
                translator.ValidationResult(False, "length_ratio_low"),
                translator.ValidationResult(False, "length_ratio_low"),
            ],
        ):
            with self.assertRaises(TranslationUnavailableError) as ctx:
                title_translator._translate_text(" ".join(["market"] * 60), "Source", "summary")
        self.assertIn("length_ratio_low", str(ctx.exception))
        self.assertEqual(len(provider.calls), 2)

    def test_bad_term_failure_does_not_trigger_recovery(self):
        provider = RecordingProvider(["外汇清算更新"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=False)
        title_translator.cache = {}
        with patch.object(
            TranslationSanityValidator,
            "validate_with_reason",
            return_value=translator.ValidationResult(False, "bad_term:外汇清算"),
        ):
            output = title_translator._translate_text("Market update", "Source", "title")
        self.assertEqual(output, "")
        self.assertEqual(len(provider.calls), 1)

    def test_critical_term_missing_does_not_trigger_recovery(self):
        provider = RecordingProvider(["市场规则"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=False)
        title_translator.cache = {}
        with patch.object(
            TranslationSanityValidator,
            "validate_with_reason",
            return_value=translator.ValidationResult(False, "critical_term_missing:CFTC"),
        ):
            output = title_translator._translate_text("CFTC market rule", "Source", "title")
        self.assertEqual(output, "")
        self.assertEqual(len(provider.calls), 1)

    def test_length_ratio_recovery_diagnostics_include_chunk_metadata(self):
        logger = Mock()
        provider = RecordingProvider(["短", "市场基础设施监管政策清算结算跨境资本市场改革持续推进"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True, logger=logger)
        title_translator.cache = {}
        with patch.object(
            TranslationSanityValidator,
            "validate_with_reason",
            side_effect=[translator.ValidationResult(False, "length_ratio_low"), translator.ValidationResult(True)],
        ):
            title_translator._translate_text(" ".join(["market"] * 50), "Source", "summary")
        warning_args = " ".join(str(arg) for call in logger.warning.call_args_list for arg in call.args)
        self.assertIn("length-ratio recovery diagnostics", warning_args)
        self.assertIn("original_length", warning_args)
        self.assertIn("initial_chunk_count", warning_args)
        self.assertIn("recovery_chunk_count", warning_args)

    def test_empty_chunk_output_still_fails_without_cache_poisoning(self):
        provider = fake_provider(FailingSecondChunkModel())
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=False)
        title_translator.cache = {}
        item = {"title_original": "短标题", "summary": "alpha beta gamma delta epsilon zeta", "source": "Source"}
        with patch.object(translator, "SOURCE_CHUNK_TOKEN_LIMIT", 3):
            output = title_translator.translate([item])
        self.assertEqual(output[0]["summary_cn"], "")
        self.assertEqual(title_translator.cache, {})

    def test_short_collapsed_fake_translation_recovers_with_smaller_chunking(self):
        class CollapsingModel(EchoModel):
            def generate(self, **inputs):
                tokens = inputs["input_ids"][0]
                if len(tokens) >= 4:
                    return [["短"]]
                return [[f"译:{'_'.join(tokens)}"]]

        provider = fake_provider(CollapsingModel())
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        item = {"title_original": "短标题", "summary": "alpha beta gamma delta epsilon zeta eta theta", "source": "Source"}
        with patch.object(translator, "SOURCE_CHUNK_TOKEN_LIMIT", 4), patch.object(
            translator, "RECOVERY_SOURCE_CHUNK_TOKEN_LIMIT", 2
        ), patch.object(TranslationSanityValidator, "validate_with_reason") as validate:
            validate.side_effect = [
                translator.ValidationResult(False, "length_ratio_low"),
                translator.ValidationResult(True),
            ]
            output = title_translator.translate([item])
        self.assertEqual(output[0]["summary_cn"], "译:alpha_beta 译:gamma_delta 译:epsilon_zeta 译:eta_theta")

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
