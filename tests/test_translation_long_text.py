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
        chunk_token_limit = chunk_token_limit or SOURCE_CHUNK_TOKEN_LIMIT
        self.calls.append(
            {
                "text": text,
                "source_lang": source_lang,
                "target_lang": target_lang,
                "chunk_token_limit": chunk_token_limit,
            }
        )
        output = self.outputs.pop(0) if self.outputs else ""
        token_count = len([token for token in str(text).split() if token])
        token_counts = []
        while token_count > 0:
            token_counts.append(min(chunk_token_limit, token_count))
            token_count -= chunk_token_limit
        self.last_translation_metadata = {
            "chunk_token_limit": chunk_token_limit,
            "chunk_count": len(token_counts),
            "chunk_token_counts": token_counts,
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

        def fake_validate(original, translated, source="", field="text"):
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
        self.assertIn("v13", GENERATION_CONFIG_VERSION)
        self.assertEqual(len(key), 64)

    def test_old_invalid_cached_entry_cannot_poison_new_recovery_key(self):
        old_version = "nllb-v1-norepeat-terminology-chunked-recovery-v9"
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
        self.assertEqual([call["chunk_token_limit"] for call in provider.calls], [SOURCE_CHUNK_TOKEN_LIMIT, 30])

    def test_adaptive_recovery_splits_49_token_single_chunk(self):
        original = " ".join(f"token{i}" for i in range(49))
        provider = RecordingProvider(["短", "完整中文翻译覆盖全部原文信息并保持顺序"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        with patch.object(
            TranslationSanityValidator,
            "validate_with_reason",
            side_effect=[translator.ValidationResult(False, "length_ratio_low"), translator.ValidationResult(True)],
        ):
            title_translator._translate_text(original, "Source", "summary")
        initial_call, recovery_call = provider.calls
        self.assertEqual(initial_call["chunk_token_limit"], SOURCE_CHUNK_TOKEN_LIMIT)
        self.assertLess(recovery_call["chunk_token_limit"], 49)
        self.assertEqual(recovery_call["chunk_token_limit"], 25)
        self.assertGreater(provider.last_translation_metadata["chunk_count"], 1)
        self.assertEqual(provider.last_translation_metadata["chunk_token_counts"], [25, 24])

    def test_recovery_cannot_repeat_identical_chunk_plan_when_smaller_plan_possible(self):
        original = " ".join(f"token{i}" for i in range(49))
        provider = RecordingProvider(["短", "完整中文翻译覆盖全部原文信息并保持顺序"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        with patch.object(
            TranslationSanityValidator,
            "validate_with_reason",
            side_effect=[translator.ValidationResult(False, "length_ratio_low"), translator.ValidationResult(True)],
        ):
            title_translator._translate_text(original, "Source", "summary")
        self.assertEqual(len(provider.calls), 2)
        self.assertNotEqual(provider.calls[0]["chunk_token_limit"], provider.calls[1]["chunk_token_limit"])
        self.assertNotEqual([49], provider.last_translation_metadata["chunk_token_counts"])

    def test_adaptive_recovery_respects_configured_maximum_for_large_failed_chunk(self):
        metadata = {"chunk_token_counts": [300]}
        self.assertEqual(TitleTranslator._effective_recovery_chunk_limit(metadata), RECOVERY_SOURCE_CHUNK_TOKEN_LIMIT)

    def test_adaptive_recovery_handles_small_failed_chunk_without_minimum_blocking_split(self):
        metadata = {"chunk_token_counts": [10]}
        self.assertEqual(TitleTranslator._effective_recovery_chunk_limit(metadata), 9)

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
        provider = RecordingProvider(["短", "市场基础设施监管政策清算结算跨境资本市场改革持续推进", "不应调用"])
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
        self.assertIn("original_raw_length", warning_args)
        self.assertIn("original_content_length", warning_args)
        self.assertIn("initial_chunk_count", warning_args)
        self.assertIn("configured_recovery_chunk_limit", warning_args)
        self.assertIn("effective_recovery_chunk_limit", warning_args)
        self.assertIn("recovery_chunk_count", warning_args)
        self.assertIn("tier1_effective_chunk_limit", warning_args)
        self.assertIn("tier2_attempted", warning_args)

    def test_tier2_recovery_diagnostics_include_microchunk_metadata(self):
        logger = Mock()
        provider = RecordingProvider(["短", "仍然不完整", "完整中文翻译覆盖全部原文信息包括备忘录条款"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True, logger=logger)
        title_translator.cache = {}
        with patch.object(
            TranslationSanityValidator,
            "validate_with_reason",
            side_effect=[
                translator.ValidationResult(False, "length_ratio_low"),
                translator.ValidationResult(False, "content_ratio_low"),
                translator.ValidationResult(True),
            ],
        ):
            title_translator._translate_text(" ".join(f"token{i}" for i in range(49)), "SEC", "summary")
        warning_args = " ".join(str(arg) for call in logger.warning.call_args_list for arg in call.args)
        self.assertIn("tier2_attempted", warning_args)
        self.assertIn("tier2_effective_chunk_limit", warning_args)
        self.assertIn("tier2_chunk_count", warning_args)
        self.assertIn("tier2_chunk_token_counts", warning_args)
        self.assertIn("tier2_content_ratio", warning_args)

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
        with patch.object(translator, "SOURCE_CHUNK_TOKEN_LIMIT", 4), patch.object(TranslationSanityValidator, "validate_with_reason") as validate:
            validate.side_effect = [
                translator.ValidationResult(False, "length_ratio_low"),
                translator.ValidationResult(True),
            ]
            output = title_translator.translate([item])
        self.assertEqual(output[0]["summary_cn"], "译:alpha_beta_gamma 译:delta_epsilon_zeta 译:eta_theta")

    def test_ice_entity_normalizes_iceland_interpretation(self):
        normalizer = translator.TerminologyNormalizer()
        normalized, changes = normalizer.normalize(
            "冰岛利率期货市场创下创纪录的开放利率",
            "ICE's Interest Rate Futures Markets Hit Record Open Interest",
            "洲际交易所",
        )
        self.assertIn("ICE", normalized)
        self.assertIn("未平仓量", normalized)
        self.assertNotIn("冰岛", normalized)
        self.assertNotIn("开放利率", normalized)
        self.assertIn("ICE", changes)

    def test_intercontinental_exchange_entity_normalizes_to_ice(self):
        normalizer = translator.TerminologyNormalizer()
        normalized, _ = normalizer.normalize(
            "欧元交易所报告月度交易量",
            "Intercontinental Exchange Reports August 2026 Statistics",
            "洲际交易所",
        )
        self.assertIn("ICE", normalized)
        self.assertNotIn("欧元交易所", normalized)

    def test_iss_stoxx_entity_does_not_become_space_station(self):
        normalizer = translator.TerminologyNormalizer()
        normalized, _ = normalizer.normalize(
            "国际空间站STOXX可持续发展报告发布",
            "ISS STOXX Sustainability Solutions launches report",
            "ISS STOXX",
        )
        self.assertIn("ISS STOXX", normalized)
        self.assertNotIn("国际空间站", normalized)

    def test_iss_corporate_entity_does_not_become_space_agency(self):
        normalizer = translator.TerminologyNormalizer()
        normalized, _ = normalizer.normalize(
            "国际航天局公司报告治理风险",
            "ISS-Corporate Report shows governance risk",
            "ISS STOXX",
        )
        self.assertIn("ISS STOXX", normalized)
        self.assertNotIn("国际航天局", normalized)

    def test_six_financial_brand_does_not_become_number(self):
        normalizer = translator.TerminologyNormalizer()
        normalized, _ = normalizer.normalize(
            "六个交易所数据:2026年8月",
            "SIX Exchanges Figures: August 2026",
            "SIX",
        )
        self.assertIn("SIX", normalized)
        self.assertNotIn("六个交易所", normalized)

    def test_ftse_entity_does_not_mutate_to_ftc(self):
        normalizer = translator.TerminologyNormalizer()
        normalized, _ = normalizer.normalize(
            "FTC100和FTC中国指数调整",
            "FTSE 100 and FTSE China Index Series quarterly review",
            "LSEG",
        )
        self.assertIn("FTSE100", normalized)
        self.assertIn("FTSE中国指数", normalized)
        self.assertNotIn("FTC", normalized)

    def test_finra_entity_does_not_invent_unrelated_institution(self):
        normalizer = translator.TerminologyNormalizer()
        normalized, _ = normalizer.normalize(
            "国际金融基金会 (FINRA) 的日内利标准更新",
            "FINRA's Intraday Margin Standard",
            "FINRA",
        )
        self.assertIn("FINRA", normalized)
        self.assertIn("日内保证金标准", normalized)
        self.assertNotIn("国际金融基金会", normalized)

    def test_unrelated_chinese_text_is_not_globally_rewritten_without_original_context(self):
        normalizer = translator.TerminologyNormalizer()
        original = "Tourism update from Iceland"
        translated = "冰岛旅游更新"
        normalized, changes = normalizer.normalize(translated, original, "Source")
        self.assertEqual(normalized, translated)
        self.assertEqual(changes, [])

    def test_ice_source_alone_does_not_rewrite_genuine_iceland_reference(self):
        normalizer = translator.TerminologyNormalizer()
        normalized, changes = normalizer.normalize(
            "冰岛能源市场活动增加",
            "Icelandic energy market activity increased",
            "ICE",
        )
        self.assertEqual(normalized, "冰岛能源市场活动增加")
        self.assertEqual(changes, [])

    def test_six_source_alone_does_not_rewrite_ordinary_number(self):
        normalizer = translator.TerminologyNormalizer()
        normalized, changes = normalizer.normalize(
            "六个市场的交易量上升",
            "Trading volumes increased across six markets",
            "SIX",
        )
        self.assertEqual(normalized, "六个市场的交易量上升")
        self.assertEqual(changes, [])

    def test_iss_stoxx_source_alone_does_not_rewrite_space_station_reference(self):
        normalizer = translator.TerminologyNormalizer()
        normalized, changes = normalizer.normalize(
            "国际空间站相关研究更新",
            "International Space Station research update",
            "ISS STOXX",
        )
        self.assertEqual(normalized, "国际空间站相关研究更新")
        self.assertEqual(changes, [])

    def test_protected_entity_and_ordinary_ambiguous_words_can_coexist(self):
        normalizer = translator.TerminologyNormalizer()
        normalized, _ = normalizer.normalize(
            "ICE报告六个市场的活动,包括冰岛",
            "ICE reported activity across six markets, including Iceland.",
            "ICE",
        )
        self.assertIn("ICE", normalized)
        self.assertIn("六个市场", normalized)
        self.assertIn("冰岛", normalized)
        self.assertNotIn("SIX", normalized)

    def test_cboe_original_entity_survives_when_model_omits_it(self):
        provider = RecordingProvider(["全球市场报告2026年8月交易量"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        output = title_translator._translate_text(
            "Cboe Global Markets Reports Trading Volume for August 2026",
            "芝加哥期权交易所",
            "title",
        )
        self.assertIn("Cboe", output)
        self.assertEqual(output.count("Cboe"), 1)

    def test_cboe_original_entity_is_not_duplicated_when_model_keeps_it(self):
        provider = RecordingProvider(["Cboe全球市场报告2026年8月交易量"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        output = title_translator._translate_text(
            "Cboe Global Markets Reports Trading Volume for August 2026",
            "芝加哥期权交易所",
            "title",
        )
        self.assertEqual(output.count("Cboe"), 1)

    def test_ice_original_entity_survives_when_model_omits_it(self):
        provider = RecordingProvider(["利率期货市场创纪录未平仓量"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        output = title_translator._translate_text(
            "ICE Interest Rate Futures Markets Hit Record Open Interest",
            "洲际交易所",
            "title",
        )
        self.assertIn("ICE", output)
        self.assertEqual(output.count("ICE"), 1)

    def test_six_brand_original_entity_survives_when_model_omits_it(self):
        provider = RecordingProvider(["交易所数据:2026年8月"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        output = title_translator._translate_text("SIX Exchanges Figures: August 2026", "SIX", "title")
        self.assertIn("SIX", output)
        self.assertEqual(output.count("SIX"), 1)

    def test_source_metadata_alone_does_not_insert_cboe(self):
        provider = RecordingProvider(["全球市场报告2026年8月交易量"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        output = title_translator._translate_text(
            "Global Markets Reports Trading Volume for August 2026",
            "Cboe",
            "title",
        )
        self.assertNotIn("Cboe", output)

    def test_ice_source_with_iceland_original_does_not_insert_ice(self):
        provider = RecordingProvider(["冰岛能源市场活动增加"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        output = title_translator._translate_text("Icelandic energy market activity increased", "ICE", "title")
        self.assertEqual(output, "冰岛能源市场活动增加")
        self.assertNotIn("ICE", output)

    def test_ice_entity_survives_while_six_and_iceland_remain_ordinary(self):
        provider = RecordingProvider(["报告六个市场的活动,包括冰岛"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        output = title_translator._translate_text(
            "ICE reported activity across six markets, including Iceland.",
            "ICE",
            "title",
        )
        self.assertIn("ICE", output)
        self.assertIn("六个市场", output)
        self.assertIn("冰岛", output)
        self.assertNotIn("SIX", output)

    def test_multiple_original_entities_survive_in_original_order(self):
        provider = RecordingProvider(["宣布新的期权市场数据合作"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        output = title_translator._translate_text(
            "ICE and Cboe announce new options market data partnership",
            "Source",
            "title",
        )
        self.assertIn("ICE", output)
        self.assertIn("Cboe", output)
        self.assertLess(output.index("ICE"), output.index("Cboe"))
        self.assertEqual(output.count("ICE"), 1)
        self.assertEqual(output.count("Cboe"), 1)

    def test_critical_term_validator_ignores_lowercase_ordinary_six(self):
        result = TranslationSanityValidator.validate_with_reason(
            "Trading volumes increased across six markets",
            "六个市场的交易量上升",
            "SIX",
            field="title",
        )
        self.assertTrue(result.valid)

    def test_lowercase_leading_six_does_not_restore_six_brand(self):
        normalizer = translator.TerminologyNormalizer()
        normalized, changes = normalizer.normalize("六个市场上涨", "six markets rose", "SIX")
        self.assertEqual(normalized, "六个市场上涨")
        self.assertEqual(changes, [])

    def test_normal_text_without_protected_entity_is_unchanged_by_survival(self):
        normalizer = translator.TerminologyNormalizer()
        normalized, changes = normalizer.normalize(
            "市场基础设施更新",
            "Market infrastructure update",
            "Cboe",
        )
        self.assertEqual(normalized, "市场基础设施更新")
        self.assertEqual(changes, [])

    def test_open_interest_financial_term_normalizes(self):
        normalizer = translator.TerminologyNormalizer()
        normalized, _ = normalizer.normalize("开放利率创纪录", "Record open interest in futures", "ICE")
        self.assertIn("未平仓量", normalized)
        self.assertNotIn("开放利率", normalized)

    def test_interest_rate_swap_financial_term_normalizes(self):
        normalizer = translator.TerminologyNormalizer()
        normalized, _ = normalizer.normalize(
            "利率交换清算规则",
            "Interest rate swap clearing requirement",
            "CFTC",
        )
        self.assertIn("利率互换", normalized)
        self.assertNotIn("利率交换", normalized)

    def test_trading_volumes_do_not_translate_as_rolls(self):
        normalizer = translator.TerminologyNormalizer()
        normalized, _ = normalizer.normalize(
            "EEX集团月份卷 2026年8月",
            "EEX Group Monthly Volumes - August 2026",
            "EEX",
        )
        self.assertIn("交易量", normalized)
        self.assertNotIn("月份卷", normalized)

    def test_intraday_margin_keeps_financial_margin_meaning(self):
        normalizer = translator.TerminologyNormalizer()
        normalized, _ = normalizer.normalize(
            "FINRA的日内利标准更新",
            "FINRA's Intraday Margin Standard",
            "FINRA",
        )
        self.assertIn("日内保证金标准", normalized)
        self.assertNotIn("日内利标准", normalized)

    def test_financial_index_uses_index_not_software_index(self):
        normalizer = translator.TerminologyNormalizer()
        normalized, _ = normalizer.normalize(
            "FTSE英国索引系列季度审查",
            "FTSE UK Index Series Quarterly Review",
            "LSEG",
        )
        self.assertIn("指数系列", normalized)
        self.assertNotIn("索引", normalized)

    def test_stablecoin_uses_standard_chinese_term(self):
        normalizer = translator.TerminologyNormalizer()
        normalized, _ = normalizer.normalize(
            "HKD稳定coin合作",
            "HKD stablecoin partnership",
            "HashKey",
        )
        self.assertIn("稳定币", normalized)
        self.assertNotIn("稳定coin", normalized)

    def test_collapsed_summary_content_ratio_fails_initial_validation(self):
        original = (
            "The Securities and Exchange Commission today proposed to update the rules and forms "
            "that apply to registered transfer agents. Transfer agents are a key component of the "
            "national clearance and settlement system. Transfer agents now perform a more diverse "
            "set of services for issuers and investors across capital markets."
        )
        translated = "SEC今天提出更新适用于注册转让代理人的规则和表格。"
        result = TranslationSanityValidator.validate_with_reason(original, translated, "SEC", field="summary")
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "content_ratio_low")

    def test_content_ratio_failure_triggers_one_adaptive_recovery(self):
        original = " ".join(["market"] * 60)
        provider = RecordingProvider(["短译文仍然过短", "市场基础设施监管政策清算结算跨境资本市场改革持续推进并保持交易后服务稳定运行"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        with patch.object(
            TranslationSanityValidator,
            "validate_with_reason",
            side_effect=[translator.ValidationResult(False, "content_ratio_low"), translator.ValidationResult(True)],
        ):
            output = title_translator._translate_text(original, "Source", "summary")
        self.assertIn("市场基础设施", output)
        self.assertEqual(len(provider.calls), 2)

    def test_good_recovered_multi_chunk_translation_passes(self):
        original = " ".join(f"token{i}" for i in range(49))
        provider = RecordingProvider(["短", "完整中文翻译覆盖全部原文信息并保持顺序"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        with patch.object(
            TranslationSanityValidator,
            "validate_with_reason",
            side_effect=[translator.ValidationResult(False, "content_ratio_low"), translator.ValidationResult(True)],
        ):
            output = title_translator._translate_text(original, "Source", "summary")
        self.assertEqual(output, "完整中文翻译覆盖全部原文信息并保持顺序")
        self.assertEqual(len(provider.calls), 2)

    def test_tier2_microchunk_recovery_succeeds_after_tier1_content_ratio_low(self):
        original = " ".join(f"token{i}" for i in range(49))
        provider = RecordingProvider(["短", "仍然不完整", "完整中文翻译覆盖全部原文信息包括备忘录条款并保持顺序"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        with patch.object(
            TranslationSanityValidator,
            "validate_with_reason",
            side_effect=[
                translator.ValidationResult(False, "length_ratio_low"),
                translator.ValidationResult(False, "content_ratio_low"),
                translator.ValidationResult(True),
            ],
        ):
            output = title_translator._translate_text(original, "SEC", "summary")
        self.assertIn("备忘录条款", output)
        self.assertEqual([call["chunk_token_limit"] for call in provider.calls], [SOURCE_CHUNK_TOKEN_LIMIT, 25, 13])
        self.assertEqual(provider.last_translation_metadata["chunk_token_counts"], [13, 13, 13, 10])

    def test_tier2_chunk_plan_differs_from_tier1(self):
        original = " ".join(f"token{i}" for i in range(49))
        provider = RecordingProvider(["短", "仍然不完整", "完整中文翻译覆盖全部原文信息"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        with patch.object(
            TranslationSanityValidator,
            "validate_with_reason",
            side_effect=[
                translator.ValidationResult(False, "length_ratio_low"),
                translator.ValidationResult(False, "content_ratio_low"),
                translator.ValidationResult(True),
            ],
        ):
            title_translator._translate_text(original, "Source", "summary")
        self.assertEqual(provider.calls[1]["chunk_token_limit"], 25)
        self.assertEqual(provider.calls[2]["chunk_token_limit"], 13)
        self.assertNotEqual(provider.calls[1]["chunk_token_limit"], provider.calls[2]["chunk_token_limit"])

    def test_tier2_retranslates_entire_original_and_preserves_source_order(self):
        original = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
        provider = RecordingProvider(["短", "甲 乙", "甲 乙 丙 丁 戊 己 庚 辛 壬 癸"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        with patch.object(
            TranslationSanityValidator,
            "validate_with_reason",
            side_effect=[
                translator.ValidationResult(False, "length_ratio_low"),
                translator.ValidationResult(False, "content_ratio_low"),
                translator.ValidationResult(True),
            ],
        ):
            output = title_translator._translate_text(original, "Source", "summary")
        self.assertEqual(output, "甲 乙 丙 丁 戊 己 庚 辛 壬 癸")
        self.assertEqual([call["text"] for call in provider.calls], [original, original, original])

    def test_tier2_runs_at_most_once(self):
        provider = RecordingProvider(["短", "仍短", "依然短", "不应调用"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        with patch.object(
            TranslationSanityValidator,
            "validate_with_reason",
            side_effect=[
                translator.ValidationResult(False, "length_ratio_low"),
                translator.ValidationResult(False, "content_ratio_low"),
                translator.ValidationResult(False, "content_ratio_low"),
            ],
        ):
            with self.assertRaises(TranslationUnavailableError):
                title_translator._translate_text(" ".join(["market"] * 49), "Source", "summary")
        self.assertEqual(len(provider.calls), 3)

    def test_tier2_does_not_run_for_bad_term_after_tier1(self):
        provider = RecordingProvider(["短", "外汇清算更新", "不应调用"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=False)
        title_translator.cache = {}
        with patch.object(
            TranslationSanityValidator,
            "validate_with_reason",
            side_effect=[
                translator.ValidationResult(False, "length_ratio_low"),
                translator.ValidationResult(False, "bad_term:外汇清算"),
            ],
        ):
            output = title_translator._translate_text(" ".join(["market"] * 49), "Source", "summary")
        self.assertEqual(output, "")
        self.assertEqual(len(provider.calls), 2)

    def test_tier2_does_not_run_for_critical_term_missing_after_tier1(self):
        provider = RecordingProvider(["短", "市场规则", "不应调用"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=False)
        title_translator.cache = {}
        with patch.object(
            TranslationSanityValidator,
            "validate_with_reason",
            side_effect=[
                translator.ValidationResult(False, "length_ratio_low"),
                translator.ValidationResult(False, "critical_term_missing:CFTC"),
            ],
        ):
            output = title_translator._translate_text(" ".join(["CFTC"] + ["market"] * 48), "Source", "summary")
        self.assertEqual(output, "")
        self.assertEqual(len(provider.calls), 2)

    def test_initial_success_never_runs_recovery(self):
        provider = RecordingProvider(["完整中文翻译"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        with patch.object(TranslationSanityValidator, "validate_with_reason", return_value=translator.ValidationResult(True)):
            output = title_translator._translate_text("Market infrastructure update", "Source", "title")
        self.assertEqual(output, "完整中文翻译")
        self.assertEqual(len(provider.calls), 1)

    def test_tier1_success_never_runs_tier2(self):
        provider = RecordingProvider(["短", "完整中文翻译", "不应调用"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        with patch.object(
            TranslationSanityValidator,
            "validate_with_reason",
            side_effect=[translator.ValidationResult(False, "length_ratio_low"), translator.ValidationResult(True)],
        ):
            output = title_translator._translate_text(" ".join(["market"] * 49), "Source", "summary")
        self.assertEqual(output, "完整中文翻译")
        self.assertEqual(len(provider.calls), 2)

    def test_still_collapsed_recovery_fails_strict_mode(self):
        provider = RecordingProvider(["短", "仍短", "依然很短"])
        title_translator = TitleTranslator(enabled=True, provider=provider, strict=True)
        title_translator.cache = {}
        with patch.object(
            TranslationSanityValidator,
            "validate_with_reason",
            side_effect=[
                translator.ValidationResult(False, "content_ratio_low"),
                translator.ValidationResult(False, "content_ratio_low"),
                translator.ValidationResult(False, "content_ratio_low"),
            ],
        ):
            with self.assertRaises(TranslationUnavailableError):
                title_translator._translate_text(" ".join(["market"] * 60), "Source", "summary")
        self.assertEqual(len(provider.calls), 3)

    def test_legitimate_shorter_chinese_summary_passes(self):
        original = (
            "The central bank announced a final rule updating capital market settlement safeguards, "
            "with new operational risk controls, clearer reporting requirements, and implementation "
            "timelines for regulated financial institutions and market infrastructure operators."
        )
        translated = "央行发布最终规则，更新资本市场结算保障，明确操作风险控制、报告要求和实施时间表。"
        result = TranslationSanityValidator.validate_with_reason(original, translated, "Source", field="summary")
        self.assertTrue(result.valid)

    def test_canonical_entity_shortening_alone_does_not_fail_completeness(self):
        original = (
            "The Securities and Exchange Commission today entered into a Memorandum of Understanding "
            "designed to assist the agencies in carrying out their respective missions to ensure "
            "efficient oversight and resilient market infrastructure for investors."
        )
        translated = "SEC今天签署谅解备忘录,旨在协助各机构履行各自使命,确保对投资者和市场基础设施进行有效监督。"
        result = TranslationSanityValidator.validate_with_reason(original, translated, "SEC", field="summary")
        self.assertTrue(result.valid)

    def test_incomplete_translation_missing_substantive_clause_still_fails_completeness(self):
        original = (
            "The Securities and Exchange Commission today entered into a Memorandum of Understanding "
            "designed to assist the agencies in carrying out their respective missions to ensure "
            "efficient oversight and resilient market infrastructure for investors."
        )
        translated = "SEC和食品和药物管理局今天宣布,旨在协助各机构履行各自的任务,以确保"
        result = TranslationSanityValidator.validate_with_reason(original, translated, "SEC", field="summary")
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "content_ratio_low")

    def test_very_short_titles_are_not_falsely_rejected(self):
        result = TranslationSanityValidator.validate_with_reason("Market update", "市场更新", "Source", field="title")
        self.assertTrue(result.valid)

    def test_empty_original_summary_still_has_empty_translation_behavior(self):
        title_translator = TitleTranslator(enabled=True, provider=RecordingProvider(["unused"]), strict=True)
        self.assertEqual(title_translator._translate_text("", "Source", "summary"), "")

    def test_intercontinental_exchange_bad_translation_normalizes_to_ice(self):
        normalizer = translator.TerminologyNormalizer()
        normalized, changes = normalizer.normalize(
            "欧元交易所公布市场数据增长",
            "Intercontinental Exchange reports market data growth",
            "洲际交易所",
        )
        self.assertIn("ICE", normalized)
        self.assertNotIn("欧元交易所", normalized)
        self.assertIn("ICE", changes)
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
