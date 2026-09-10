import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_FILE = BASE_DIR / "cache" / "translation_cache.json"
GLOSSARY_FILE = BASE_DIR / "config" / "glossary.json"

NLLB_MODEL_NAME = "facebook/nllb-200-distilled-600M"
GENERATION_CONFIG_VERSION = "nllb-v1-norepeat-terminology-chunked-recovery-quality-v11"
SOURCE_CHUNK_TOKEN_LIMIT = 256
RECOVERY_SOURCE_CHUNK_TOKEN_LIMIT = 128
MIN_RECOVERY_SOURCE_CHUNK_TOKEN_LIMIT = 16
MODEL_SOURCE_TOKEN_LIMIT = 512
DEFAULT_GENERATION_CONFIG = {
    "max_new_tokens": 240,
    "num_beams": 4,
    "do_sample": False,
    "no_repeat_ngram_size": 3,
    "repetition_penalty": 1.1,
}


class TranslationUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reason: str = "ok"


def looks_chinese(text):
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def looks_english(text):
    if not (text or "").strip():
        return False
    ascii_letters = sum(1 for c in text if "a" <= c.lower() <= "z")
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return ascii_letters >= 4 and ascii_letters >= cjk


def detect_language(text):
    if looks_chinese(text):
        return "zh"
    if looks_english(text):
        return "en"
    return "unknown"


def _load_glossary():
    if not GLOSSARY_FILE.exists():
        return {"version": 0, "term_translations": {}, "source_aware_post_edits": {}}
    try:
        with GLOSSARY_FILE.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"version": 0, "term_translations": {}, "source_aware_post_edits": {}}


def _cache_key(model_name, source_lang, target_lang, text, glossary_version):
    payload = {
        "model": model_name,
        "generation_config_version": GENERATION_CONFIG_VERSION,
        "generation_config": DEFAULT_GENERATION_CONFIG,
        "glossary_version": glossary_version,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "text": text,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_cache(logger=None):
    if not CACHE_FILE.exists():
        return {}
    try:
        with CACHE_FILE.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        if logger:
            logger.warning("Translation cache ignored because it could not be read: %s", exc)
        return {}


def _save_cache(cache, logger=None):
    try:
        CACHE_FILE.parent.mkdir(exist_ok=True)
        with CACHE_FILE.open("w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception as exc:
        if logger:
            logger.warning("Translation cache could not be saved: %s", exc)


class TranslationSanityValidator:
    BAD_GARBAGE_TERMS = ("买彩", "倍投")
    BAD_CONTROL_RATIO = 0.04
    BAD_TERMS = (
        "清流",
        "希克克斯",
        "希克斯",
        "欧莱克斯",
        "欧雷克斯",
        "欧元交易所",
        "外汇清算",
        "回复交易",
        "商品库运营商",
        "欧盟货币交易委员会",
        "欧盟CFTC",
        "欧盟贸易交易委员会",
        "美国央行",
        "金融交易委员会",
        "联邦书商管理局",
        "联邦银行局",
        "联邦金融监管局",
    )

    @staticmethod
    def _content_length(text):
        cleaned = re.sub(r"https?://\S+", "", text or "", flags=re.I)
        cleaned = re.sub(r"&[A-Za-z0-9#]+;", "", cleaned)
        cleaned = re.sub(r"[\s\W_]+", "", cleaned, flags=re.UNICODE)
        return len(cleaned)

    @classmethod
    def validate_with_reason(cls, original, translated, source="", field="text"):
        if not (translated or "").strip():
            return ValidationResult(False, "empty_translation")
        for term in cls.BAD_GARBAGE_TERMS:
            if term in translated:
                return ValidationResult(False, f"garbage_term:{term}")
        if re.search(r"([\u4e00-\u9fff])\1{2,}", translated):
            return ValidationResult(False, "repeated_character")
        if re.search(r"(.{2,12})\1{4,}", translated):
            return ValidationResult(False, "repeated_phrase")
        if "JPX (JPX)" in translated:
            return ValidationResult(False, "duplicate_term:JPX")
        if "\ufffd" in translated:
            return ValidationResult(False, "replacement_character")

        checked = 0
        controls = 0
        for char in translated:
            if char in "\n\r\t":
                continue
            checked += 1
            if unicodedata.category(char).startswith("C"):
                controls += 1
        if checked and controls / checked > cls.BAD_CONTROL_RATIO:
            return ValidationResult(False, "control_ratio")

        original_len = max(len(original or ""), 1)
        translated_len = len(translated or "")
        if original_len >= 20:
            ratio = translated_len / original_len
            if ratio > 3.0:
                return ValidationResult(False, "length_ratio_high")
            if ratio < 0.08:
                return ValidationResult(False, "length_ratio_low")

        original_content_len = cls._content_length(original)
        translated_content_len = cls._content_length(translated)
        if original_content_len >= 180:
            content_ratio = translated_content_len / max(original_content_len, 1)
            min_ratio = 0.16 if field == "summary" else 0.10
            if content_ratio < min_ratio:
                return ValidationResult(False, "content_ratio_low")

        original_lower = (original or "").lower()
        original_text = original or ""
        context_bad_terms = [
            ("ICE", ("冰岛", "欧元交易所")),
            ("Intercontinental Exchange", ("冰岛", "欧元交易所")),
            ("ISS STOXX", ("国际空间站", "国际航天局")),
            ("ISS-Corporate", ("国际空间站", "国际航天局")),
            ("SIX", ("六个交易所", "六个")),
            ("FTSE", ("FTC",)),
            ("FINRA", ("国际金融基金会",)),
            ("open interest", ("开放利率",)),
            ("interest rate swap", ("利率交换",)),
            ("trading volume", ("月份卷", "报告卷")),
            ("trading volumes", ("月份卷", "报告卷")),
            ("intraday margin", ("日内利标准",)),
            ("stablecoin", ("稳定coin",)),
        ]
        for trigger, bad_terms in context_bad_terms:
            if trigger.lower() in original_lower:
                for bad in bad_terms:
                    if bad in translated:
                        return ValidationResult(False, f"context_bad_term:{trigger}:{bad}")

        if "dematerialized" in original_lower and ("物质化" in translated or "非物质化" in translated):
            return ValidationResult(False, "dematerialized_mistranslation")

        critical_terms = (
            "Clearstream",
            "Eurex",
            "EEX",
            "HKEX",
            "CFTC",
            "SEC",
            "ECB",
            "FOMC",
            "JPX",
            "ICE",
            "ISS STOXX",
            "STOXX",
            "SIX",
            "Nasdaq",
            "Cboe",
            "LSEG",
            "FTSE",
            "DTCC",
            "FINRA",
            "MAS",
            "FSC",
        )
        for term in critical_terms:
            term_pattern = r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])"
            if re.search(term_pattern, original_text, flags=re.I) and term not in translated:
                return ValidationResult(False, f"critical_term_missing:{term}")

        for term in cls.BAD_TERMS:
            if term in translated:
                return ValidationResult(False, f"bad_term:{term}")
        return ValidationResult(True)

    @classmethod
    def is_valid(cls, original, translated, source=""):
        return cls.validate_with_reason(original, translated, source).valid


class LocalNLLBProvider:
    def __init__(self, logger=None, local_files_only=None):
        self.logger = logger
        self.model_name = NLLB_MODEL_NAME
        self.source_lang = "eng_Latn"
        self.target_lang = "zho_Hans"
        self.local_files_only = (
            os.environ.get("WEEKLY_REPORT_TRANSLATION_ALLOW_DOWNLOAD") != "1"
            if local_files_only is None
            else local_files_only
        )
        self.tokenizer = None
        self.model = None
        self.forced_bos_token_id = None
        self.load_failed = False
        self.load_error = ""
        self.load_warning_logged = False
        self.last_error = ""
        self.translation_call_count = 0
        self.chunked_text_count = 0
        self.translated_chunk_count = 0
        self.last_translation_metadata = {}

    def _load(self):
        if self.model is not None and self.tokenizer is not None:
            return True
        if self.load_failed:
            return False
        try:
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name, local_files_only=self.local_files_only)
            self.tokenizer.src_lang = self.source_lang
            self.model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name, local_files_only=self.local_files_only)
            self.model.eval()
            self.forced_bos_token_id = self.tokenizer.convert_tokens_to_ids(self.target_lang)
            return True
        except Exception as exc:
            self.load_failed = True
            self.load_error = str(exc)
            if self.logger and not self.load_warning_logged:
                self.logger.warning("Local NLLB provider unavailable; translation disabled: %s", exc)
                self.load_warning_logged = True
            self.tokenizer = None
            self.model = None
            return False

    def _token_ids(self, text):
        if hasattr(self.tokenizer, "encode"):
            try:
                return list(self.tokenizer.encode(text, add_special_tokens=False))
            except TypeError:
                return list(self.tokenizer.encode(text))
        encoded = self.tokenizer(text, add_special_tokens=False)
        ids = encoded.get("input_ids", []) if isinstance(encoded, dict) else []
        if ids and isinstance(ids[0], list):
            ids = ids[0]
        return list(ids)

    def _token_count(self, text):
        return len(self._token_ids(text))

    def _decode_token_ids(self, token_ids):
        if hasattr(self.tokenizer, "decode"):
            return self.tokenizer.decode(token_ids, skip_special_tokens=True).strip()
        return " ".join(str(token) for token in token_ids).strip()

    def _split_oversized_segment(self, segment, chunk_token_limit):
        words = re.findall(r"\S+\s*", segment)
        chunks = []
        current = ""
        for word in words:
            candidate = current + word
            if current and self._token_count(candidate) > chunk_token_limit:
                chunks.append(current.strip())
                current = word
            else:
                current = candidate

            if self._token_count(current) > chunk_token_limit:
                ids = self._token_ids(current)
                for start in range(0, len(ids), chunk_token_limit):
                    piece = self._decode_token_ids(ids[start : start + chunk_token_limit])
                    if piece:
                        chunks.append(piece)
                current = ""

        if current.strip():
            chunks.append(current.strip())
        return chunks

    def _candidate_segments(self, text):
        normalized = re.sub(r"\s+", " ", text or "").strip()
        if not normalized:
            return []
        paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
        if len(paragraphs) <= 1:
            paragraphs = [normalized]

        segments = []
        for paragraph in paragraphs:
            parts = re.split(r"(?<=[.!?。！？])\s+", re.sub(r"\s+", " ", paragraph).strip())
            segments.extend([part.strip() for part in parts if part.strip()])
        return segments

    def _split_text_into_chunks(self, text, chunk_token_limit=None):
        chunk_token_limit = chunk_token_limit or SOURCE_CHUNK_TOKEN_LIMIT
        if self._token_count(text) <= chunk_token_limit:
            return [text.strip()]

        chunks = []
        current = ""
        for segment in self._candidate_segments(text):
            if self._token_count(segment) > chunk_token_limit:
                if current:
                    chunks.append(current.strip())
                    current = ""
                chunks.extend(self._split_oversized_segment(segment, chunk_token_limit))
                continue

            candidate = f"{current} {segment}".strip() if current else segment
            if current and self._token_count(candidate) > chunk_token_limit:
                chunks.append(current.strip())
                current = segment
            else:
                current = candidate

        if current:
            chunks.append(current.strip())
        return [chunk for chunk in chunks if chunk]

    def _translate_chunk(self, chunk, chunk_index, total_chunks, chunk_token_limit):
        token_count = self._token_count(chunk)
        if token_count > chunk_token_limit:
            self.last_error = f"chunk {chunk_index}/{total_chunks} exceeds token budget: {token_count}"
            return ""
        inputs = self.tokenizer(chunk, return_tensors="pt", truncation=True, max_length=MODEL_SOURCE_TOKEN_LIMIT)
        output = self.model.generate(
            **inputs,
            forced_bos_token_id=self.forced_bos_token_id,
            **DEFAULT_GENERATION_CONFIG,
        )
        self.translation_call_count += 1
        self.translated_chunk_count += 1
        return self.tokenizer.decode(output[0], skip_special_tokens=True).strip()

    def translate(self, text, source_lang="en", target_lang="zh", chunk_token_limit=None):
        if source_lang != "en" or target_lang != "zh" or not (text or "").strip():
            return ""
        chunk_token_limit = chunk_token_limit or SOURCE_CHUNK_TOKEN_LIMIT
        self.last_error = ""
        self.last_translation_metadata = {}
        if not self._load():
            self.last_error = self.load_error or "model unavailable"
            return ""
        try:
            chunks = self._split_text_into_chunks(text, chunk_token_limit=chunk_token_limit)
            token_counts = [self._token_count(chunk) for chunk in chunks]
            output_lengths = []
            self.last_translation_metadata = {
                "chunk_token_limit": chunk_token_limit,
                "chunk_count": len(chunks),
                "chunk_token_counts": token_counts,
                "chunk_output_lengths": output_lengths,
            }
            if not chunks:
                self.last_error = "empty text after chunking"
                return ""
            if len(chunks) > 1:
                self.chunked_text_count += 1
            translated_chunks = []
            total = len(chunks)
            for index, chunk in enumerate(chunks, start=1):
                translated = self._translate_chunk(chunk, index, total, chunk_token_limit)
                if not translated:
                    self.last_error = self.last_error or f"chunk {index}/{total} produced empty output"
                    return ""
                output_lengths.append(len(translated))
                translated_chunks.append(translated)
            return " ".join(translated_chunks).strip()
        except Exception as exc:
            if self.logger:
                self.logger.warning("Local NLLB translation failed: %s", exc)
            self.last_error = str(exc)
            return ""


class TerminologyNormalizer:
    CANONICAL_ENTITIES = {
        "Deutsche Börse": {
            "aliases": ["Deutsche Börse Group"],
            "bad": ["德意志交易所"],
        },
        "Eurex": {"aliases": [], "bad": ["欧莱克斯", "欧雷克斯", "欧元交易所"]},
        "EEX": {"aliases": ["EEX Group"], "bad": []},
        "360T": {"aliases": [], "bad": []},
        "Crypto Finance": {"aliases": [], "bad": []},
        "Clearstream": {"aliases": [], "bad": ["清流"]},
        "SimCorp": {"aliases": [], "bad": []},
        "ISS STOXX": {
            "aliases": ["ISS-Corporate"],
            "bad": ["国际空间站STOXX", "国际航天局公司", "国际航天局", "国际空间站", "伊斯斯斯托克斯", "伊斯斯托克斯"],
        },
        "STOXX": {"aliases": [], "bad": []},
        "ICE": {"aliases": ["Intercontinental Exchange"], "bad": ["冰岛", "欧元交易所"]},
        "SIX": {"aliases": ["SIX Exchanges"], "bad": ["六个交易所", "六个", "六"]},
        "Nasdaq": {"aliases": [], "bad": ["纳斯达克"]},
        "Cboe": {"aliases": [], "bad": []},
        "LSEG": {"aliases": ["London Stock Exchange Group"], "bad": []},
        "FTSE": {"aliases": ["FTSE Russell"], "bad": ["FTC"]},
        "S&P Dow Jones Indices": {"aliases": ["S&P DJI"], "bad": []},
        "DTCC": {"aliases": [], "bad": []},
        "FINRA": {"aliases": [], "bad": ["国际金融基金会"]},
        "SEC": {"aliases": ["Securities and Exchange Commission"], "bad": ["美国证券交易委员会", "证券交易委员会"]},
        "CFTC": {
            "aliases": ["Commodity Futures Trading Commission"],
            "bad": ["欧盟货币交易委员会", "欧盟CFTC", "欧盟贸易交易委员会", "美国央行", "金融交易委员会", "商品期货交易委员会"],
        },
        "MAS": {"aliases": ["Monetary Authority of Singapore"], "bad": []},
        "HKEX": {"aliases": ["Hong Kong Exchanges and Clearing"], "bad": ["希克克斯", "希克斯"]},
        "JPX": {"aliases": ["Japan Exchange Group"], "bad": ["日本交流集团", "日本交易所集团"]},
        "FSC": {"aliases": ["Financial Services Commission"], "bad": ["联邦书商管理局", "国际SEC"]},
        "ECB": {"aliases": ["European Central Bank"], "bad": ["欧洲央行"]},
        "FOMC": {"aliases": ["Federal Open Market Committee"], "bad": ["联邦开放市场委员会"]},
    }
    FALLBACK_SOURCE_EDITS = {
        "Clearstream": {"清流": "Clearstream"},
        "Deutsche Börse": {"德意志交易所": "Deutsche Börse"},
        "ISS STOXX": {"伊斯斯斯托克斯": "ISS STOXX", "伊斯斯托克斯": "ISS STOXX"},
        "HashKey": {"哈希基": "HashKey", "HachKey": "HashKey"},
        "HKEX": {"希克克斯": "HKEX", "希克斯": "HKEX"},
        "Eurex": {"欧莱克斯": "Eurex", "欧雷克斯": "Eurex", "欧元交易所": "Eurex"},
        "CFTC": {
            "欧盟货币交易委员会": "CFTC",
            "欧盟贸易交易委员会": "CFTC",
            "欧盟CFTC": "CFTC",
            "美国央行": "CFTC",
            "金融交易委员会": "CFTC",
            "商品期货交易委员会": "CFTC",
        },
        "SEC": {"美国证券交易委员会": "SEC", "证券交易委员会": "SEC"},
        "ECB": {"欧洲央行": "ECB"},
        "FOMC": {"联邦开放市场委员会": "FOMC"},
        "HKMA": {"香港货币管理局": "HKMA", "香港金融管理局": "HKMA"},
        "JPX": {"日本交流集团": "JPX", "日本交易所集团": "JPX"},
        "SIX": {"六个交易所": "SIX Exchanges", "六个": "SIX", "六": "SIX"},
        "ICE": {"冰岛": "ICE", "欧元交易所": "ICE"},
        "FINRA": {"国际金融基金会": "FINRA"},
        "FTSE": {"FTC": "FTSE"},
        "FSC": {"国际SEC": "FSC", "联邦书商管理局": "FSC"},
    }
    CONTEXT_ALIASES = {
        "Clearstream": ["明讯银行"],
        "Deutsche Börse": ["德意志交易所集团官网"],
        "ISS STOXX": ["iss stoxx"],
        "HashKey": ["hashkey"],
        "HKEX": ["hong kong exchanges and clearing", "香港交易所"],
        "Eurex": ["欧洲期交所"],
        "CFTC": ["commodity futures trading commission", "商品期货交易委员会"],
        "FDIC": ["fdic", "federal deposit insurance corporation", "联邦存款保险公司"],
        "FSC": ["fsc", "fscma", "financial services commission", "韩国金融监督委员会"],
        "SEC": ["securities and exchange commission", "证券交易委员会"],
        "HKMA": ["hong kong monetary authority", "香港金融管理局", "香港货币管理局"],
        "ECB": ["european central bank", "欧洲中央银行"],
        "FOMC": ["federal open market committee", "联邦储备系统"],
        "JPX": ["japan exchange group", "日本交易所集团"],
        "Euronext": ["euronext", "泛欧交易所"],
        "ICE": ["intercontinental exchange", "洲际交易所"],
        "SIX": ["six exchanges", "six group"],
        "FINRA": ["financial industry regulatory authority"],
        "FTSE": ["ftse russell"],
        "Nasdaq": ["nasdaq"],
        "FSC": ["financial services commission"],
    }
    TERM_RULES = [
        ("Commodity Pool Operator", r"商品库运营商", "商品基金运营商"),
        ("CFTC", r"欧盟CFTC|欧盟贸易交易委员会", "CFTC"),
        ("dematerialized Eurobond issuance", r"Clearstream的先驱将欧元债券发行物质化", "Clearstream率先完成无纸化欧洲债券发行"),
        ("dematerialized Eurobond issuance", r"Clearstream的先驱将无纸化欧洲债券发行", "Clearstream率先完成无纸化欧洲债券发行"),
        ("dematerialized Eurobond", r"非物质化欧元债券(?:试点)?发行", "无纸化欧洲债券发行"),
        ("dematerialized Eurobond", r"欧元债券发行物质化", "无纸化欧洲债券发行"),
        ("OTC Clearing", r"外汇清算", "OTC清算"),
        ("Repo", r"回复交易|回购交易", "Repo交易"),
        ("interest rate swaps", r"利率交换", "利率互换"),
        ("outstanding notional", r"额外额度", "未清名义本金"),
        ("exchange-traded fund", r"交易所基金", "交易所交易基金"),
        ("ETF", r"ETFs", "ETF"),
        ("EBA, EIOPA and ESMA", r"欧洲央行,欧盟人工智能署和欧盟证券监管局", "EBA、EIOPA和ESMA"),
        ("EBA, EIOPA and ESMA", r"欧洲央行,欧盟人工智能署和欧盟证券管理局", "EBA、EIOPA和ESMA"),
        ("Euronext", r"欧元联网", "Euronext"),
        ("Euronext", r"欧元集团", "Euronext"),
        ("FDIC", r"联邦银行局|联邦金融监管局", "FDIC"),
        ("FSC", r"联邦书商管理局", "FSC"),
        ("Intercontinental Exchange", r"欧元交易所", "ICE"),
        ("open interest", r"开放利率", "未平仓量"),
        ("interest rate swap", r"利率交换", "利率互换"),
        ("interest rate swaps", r"利率交换", "利率互换"),
        ("intraday margin", r"日内利标准|日内利润标准", "日内保证金标准"),
        ("stablecoin", r"稳定coin", "稳定币"),
    ]

    VOLUME_CONTEXT_RE = re.compile(r"\b(?:trading\s+)?volumes?\b|\bmonthly\s+volumes?\b|\bexchange\s+volumes?\b", re.I)
    INDEX_CONTEXT_RE = re.compile(r"\b(?:market\s+index|index\s+series|benchmark\s+index|indices|indexes|ftse)\b", re.I)

    @staticmethod
    def _contains_entity(text, entity):
        flags = 0 if entity.isupper() and len(entity) <= 5 else re.I
        return bool(re.search(r"(?<![A-Za-z0-9])" + re.escape(entity) + r"(?![A-Za-z0-9])", text or "", flags=flags))

    def _original_has_entity_evidence(self, original, canonical, aliases):
        original_lower = (original or "").lower()
        return self._contains_entity(original, canonical) or any(alias.lower() in original_lower for alias in aliases)

    def __init__(self):
        glossary = _load_glossary()
        self.version = glossary.get("version", 0)
        source_edits = dict(self.FALLBACK_SOURCE_EDITS)
        for source, replacements in (glossary.get("source_aware_post_edits") or {}).items():
            merged = dict(source_edits.get(source, {}))
            merged.update(replacements or {})
            source_edits[source] = merged
        self.source_edits = source_edits

    def normalize(self, translated, original, source):
        out = translated or ""
        changes = []
        original_lower = (original or "").lower()
        source_lower = (source or "").lower()

        def replace(pattern, repl, label):
            nonlocal out
            new = re.sub(pattern, repl, out)
            if new != out:
                out = new
                changes.append(label)

        for canonical, spec in self.CANONICAL_ENTITIES.items():
            aliases = spec.get("aliases", [])
            has_context = self._original_has_entity_evidence(original, canonical, aliases)
            if has_context:
                for bad in spec.get("bad", []):
                    if canonical == "ICE" and bad == "冰岛" and re.search(r"\bIceland(?:ic)?\b", original or "", flags=re.I):
                        continue
                    if canonical == "SIX" and bad in ("六", "六个") and re.search(r"\bsix\b", original or ""):
                        continue
                    replace(re.escape(bad), canonical, canonical)

        for brand, replacements in self.source_edits.items():
            aliases = self.CONTEXT_ALIASES.get(brand, [])
            has_context = self._original_has_entity_evidence(original, brand, aliases)
            if has_context:
                for bad, good in replacements.items():
                    if brand == "ICE" and bad == "冰岛" and re.search(r"\bIceland(?:ic)?\b", original or "", flags=re.I):
                        continue
                    if brand == "SIX" and bad in ("六", "六个") and re.search(r"\bsix\b", original or ""):
                        continue
                    replace(re.escape(bad), good, good)

        for source_term, bad_pattern, good in self.TERM_RULES:
            if source_term.lower() in original_lower:
                replace(bad_pattern, good, source_term)

        if self.VOLUME_CONTEXT_RE.search(original or ""):
            replace(r"月份卷|月份数量|报告卷|(?<![一-龥])卷(?![一-龥])", "交易量", "trading volume")

        if self.INDEX_CONTEXT_RE.search(original or ""):
            replace(r"索引", "指数", "financial index")

        for brand in self.source_edits:
            brand_pattern = r"^\s*" + re.escape(brand) + r"(?:['’]s)?\b"
            if re.search(brand_pattern, original or "", flags=re.I) and brand not in out:
                out = f"{brand} {out}".strip()
                changes.append(f"{brand}:restore_leading_brand")

        return out.strip(), changes


class TitleTranslator:
    def __init__(self, enabled=True, logger=None, provider=None, strict=False):
        self.enabled = enabled
        self.logger = logger
        self.provider = provider
        self.strict = strict
        self.normalizer = TerminologyNormalizer()
        self.cache = {}
        self.cache_dirty = False
        if self.enabled:
            self.cache = _load_cache(logger)

    @staticmethod
    def _length_ratio(original, translated):
        original_len = len((original or "").strip())
        translated_len = len((translated or "").strip())
        if original_len <= 0:
            return 0.0
        return translated_len / original_len

    @staticmethod
    def _content_length(text):
        return TranslationSanityValidator._content_length(text)

    def _content_ratio(self, original, translated):
        original_len = self._content_length(original)
        if original_len <= 0:
            return 0.0
        return self._content_length(translated) / original_len

    @staticmethod
    def _provider_translate(provider, text, chunk_token_limit):
        try:
            return provider.translate(text, source_lang="en", target_lang="zh", chunk_token_limit=chunk_token_limit)
        except TypeError as exc:
            if "chunk_token_limit" not in str(exc):
                raise
            return provider.translate(text, source_lang="en", target_lang="zh")

    @staticmethod
    def _provider_metadata(provider):
        metadata = getattr(provider, "last_translation_metadata", {}) or {}
        return {
            "chunk_token_limit": metadata.get("chunk_token_limit"),
            "chunk_count": metadata.get("chunk_count"),
            "chunk_token_counts": metadata.get("chunk_token_counts", []),
            "chunk_output_lengths": metadata.get("chunk_output_lengths", []),
        }

    @staticmethod
    def _effective_recovery_chunk_limit(initial_metadata):
        token_counts = [
            count
            for count in (initial_metadata.get("chunk_token_counts") or [])
            if isinstance(count, int) and count > 0
        ]
        if not token_counts:
            return RECOVERY_SOURCE_CHUNK_TOKEN_LIMIT

        largest_failed_chunk = max(token_counts)
        if largest_failed_chunk <= 1:
            return 1

        effective = min(
            RECOVERY_SOURCE_CHUNK_TOKEN_LIMIT,
            max(MIN_RECOVERY_SOURCE_CHUNK_TOKEN_LIMIT, (largest_failed_chunk + 1) // 2),
        )
        if effective >= largest_failed_chunk:
            effective = largest_failed_chunk - 1
        return max(1, effective)

    def _log_recovery_diagnostics(
        self,
        source,
        field,
        text,
        initial_translation,
        initial_validation,
        initial_metadata,
        recovery_attempted,
        recovery_translation="",
        recovery_validation=None,
        recovery_metadata=None,
    ):
        if not self.logger:
            return
        final_validation = recovery_validation or initial_validation
        self.logger.warning(
            "Translation length-ratio recovery diagnostics: "
            "source=%s field=%s text_prefix=%r original_raw_length=%s original_content_length=%s "
            "translated_raw_length=%s translated_content_length=%s raw_ratio=%.3f normalized_content_ratio=%.3f "
            "initial_reason=%s initial_chunk_limit=%s initial_chunk_count=%s "
            "initial_chunk_token_counts=%s initial_chunk_output_lengths=%s "
            "recovery_attempted=%s configured_recovery_chunk_limit=%s effective_recovery_chunk_limit=%s "
            "recovery_chunk_count=%s recovery_chunk_token_counts=%s initial_output_length=%s "
            "recovery_output_length=%s initial_ratio=%.3f final_normalized_content_ratio=%.3f final_reason=%s",
            source,
            field,
            (text or "")[:120],
            len(text or ""),
            self._content_length(text),
            len(initial_translation or ""),
            self._content_length(initial_translation),
            self._length_ratio(text, initial_translation),
            self._content_ratio(text, initial_translation),
            initial_validation.reason,
            initial_metadata.get("chunk_token_limit"),
            initial_metadata.get("chunk_count"),
            initial_metadata.get("chunk_token_counts"),
            initial_metadata.get("chunk_output_lengths"),
            recovery_attempted,
            RECOVERY_SOURCE_CHUNK_TOKEN_LIMIT,
            (recovery_metadata or {}).get("chunk_token_limit"),
            (recovery_metadata or {}).get("chunk_count"),
            (recovery_metadata or {}).get("chunk_token_counts"),
            len(initial_translation or ""),
            len(recovery_translation or ""),
            self._length_ratio(text, initial_translation),
            self._content_ratio(text, recovery_translation or initial_translation),
            final_validation.reason,
        )

    def _translate_text(self, text, source, field="text"):
        if not self.enabled or not text or detect_language(text) != "en":
            return ""
        provider = self.provider
        if provider is None:
            provider = LocalNLLBProvider(logger=self.logger)
            self.provider = provider

        key = _cache_key(provider.model_name, "en", "zh", text, self.normalizer.version)
        cached = self.cache.get(key)
        if isinstance(cached, dict) and "translation" in cached:
            value = cached.get("translation", "")
            if value:
                return value
            if cached.get("invalid") and self.logger:
                self.logger.info("Ignoring invalid cached translation for source=%s field=%s", source, field)

        raw = self._provider_translate(provider, text, SOURCE_CHUNK_TOKEN_LIMIT)
        if not raw:
            if self.strict:
                reason = getattr(provider, "last_error", "") or getattr(provider, "load_error", "") or "empty provider output"
                raise TranslationUnavailableError(
                    f"translation unavailable for source={source!r} field={field} text={text[:120]!r}: {reason}"
                )
            return ""
        initial_metadata = self._provider_metadata(provider)
        normalized, changes = self.normalizer.normalize(raw, text, source)
        validation = TranslationSanityValidator.validate_with_reason(text, normalized, source, field=field)
        if not validation.valid:
            if validation.reason in ("length_ratio_low", "content_ratio_low"):
                recovery_chunk_limit = self._effective_recovery_chunk_limit(initial_metadata)
                recovered_raw = self._provider_translate(provider, text, recovery_chunk_limit)
                recovery_metadata = self._provider_metadata(provider)
                recovered_normalized, recovered_changes = self.normalizer.normalize(recovered_raw, text, source)
                recovered_validation = TranslationSanityValidator.validate_with_reason(
                    text, recovered_normalized, source, field=field
                )
                self._log_recovery_diagnostics(
                    source,
                    field,
                    text,
                    normalized,
                    validation,
                    initial_metadata,
                    True,
                    recovered_normalized,
                    recovered_validation,
                    recovery_metadata,
                )
                if recovered_raw and recovered_validation.valid:
                    self.cache[key] = {
                        "translation": recovered_normalized,
                        "raw_translation": recovered_raw,
                        "terminology_changes": recovered_changes,
                        "model": provider.model_name,
                        "generation_config_version": GENERATION_CONFIG_VERSION,
                        "glossary_version": self.normalizer.version,
                        "recovered_from": validation.reason,
                    }
                    self.cache_dirty = True
                    return recovered_normalized
                validation = recovered_validation
                normalized = recovered_normalized

            if self.logger:
                self.logger.warning(
                    "Translation rejected by sanity validator: reason=%s source=%s text=%r",
                    validation.reason,
                    source,
                    text[:120],
                )
            if self.strict:
                raise TranslationUnavailableError(
                    f"translation rejected by sanity validator: reason={validation.reason} "
                    f"source={source!r} field={field} text={text[:120]!r}"
                )
            return ""

        self.cache[key] = {
            "translation": normalized,
            "raw_translation": raw,
            "terminology_changes": changes,
            "model": provider.model_name,
            "generation_config_version": GENERATION_CONFIG_VERSION,
            "glossary_version": self.normalizer.version,
        }
        self.cache_dirty = True
        return normalized

    def translate(self, items):
        translated = []
        if not self.enabled and self.logger:
            self.logger.info("Translation skipped by --no-translate")

        for item in items:
            clean = dict(item)
            title_original = clean.get("title_original", "")
            summary_original = clean.get("summary_original", clean.get("summary", ""))
            source = clean.get("source", "")

            title_lang = detect_language(title_original)
            summary_lang = detect_language(summary_original)
            clean["title_original_lang"] = title_lang
            clean["summary_original"] = summary_original
            clean["summary_original_lang"] = summary_lang

            if title_lang == "zh":
                clean["title_cn"] = title_original
                clean["title_en"] = clean.get("title_en", "")
            elif title_lang == "en":
                clean["title_en"] = title_original
                clean["title_cn"] = self._translate_text(title_original, source, field="title")
                if self.strict and not clean["title_cn"]:
                    raise TranslationUnavailableError(f"required title translation missing for source={source!r}")
            else:
                clean["title_en"] = clean.get("title_en", title_original)
                clean["title_cn"] = clean.get("title_cn", "")

            if summary_lang == "zh":
                clean["summary_cn"] = summary_original
                clean["summary_en"] = clean.get("summary_en", "")
            elif summary_lang == "en":
                clean["summary_en"] = summary_original
                clean["summary_cn"] = self._translate_text(summary_original, source, field="summary")
                if self.strict and summary_original.strip() and not clean["summary_cn"]:
                    raise TranslationUnavailableError(f"required summary translation missing for source={source!r}")
            else:
                clean["summary_en"] = ""
                clean["summary_cn"] = ""

            translated.append(clean)

        if self.enabled and self.cache_dirty:
            _save_cache(self.cache, self.logger)
        return translated
