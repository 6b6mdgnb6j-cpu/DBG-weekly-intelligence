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
GENERATION_CONFIG_VERSION = "nllb-v1-norepeat-terminology-chunked-recovery-quality-v20"
SOURCE_CHUNK_TOKEN_LIMIT = 256
RECOVERY_SOURCE_CHUNK_TOKEN_LIMIT = 128
MIN_RECOVERY_SOURCE_CHUNK_TOKEN_LIMIT = 16
MIN_TIER2_SOURCE_CHUNK_TOKEN_LIMIT = 8
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

    @staticmethod
    def _entity_flags(entity):
        return 0 if re.search(r"\b[A-Z0-9]{2,}\b", entity or "") else re.I

    @classmethod
    def _contains_critical_entity(cls, text, entity):
        pattern = r"(?<![A-Za-z0-9])" + re.escape(entity) + r"(?![A-Za-z0-9])"
        return bool(re.search(pattern, text or "", flags=cls._entity_flags(entity)))

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
            if cls._contains_critical_entity(original_text, trigger):
                for bad in bad_terms:
                    if trigger in ("ICE", "Intercontinental Exchange") and bad == "冰岛" and re.search(
                        r"\bIceland(?:ic)?\b", original_text, flags=re.I
                    ):
                        continue
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
            if cls._contains_critical_entity(original_text, term) and term not in translated:
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
        # Preserve the complete legal name; never whitelist its mistranslated prefix.
        "Euro Exchange Securities UK Ltd": {
            "aliases": [],
            "bad": ["欧元交易所证券英国股份有限公司"],
        },
        "Deutsche Börse": {
            "aliases": ["Deutsche Börse Group"],
            "bad": ["德意志交易所", "德意志 Börse"],
        },
        "Eurex": {"aliases": [], "bad": ["欧莱克斯", "欧雷克斯", "欧元交易所"]},
        "EEX": {"aliases": ["EEX Group"], "bad": []},
        "360T": {"aliases": [], "bad": []},
        "Crypto Finance": {"aliases": [], "bad": ["加密金融"]},
        "Clearstream": {"aliases": [], "bad": ["清流"]},
        "SimCorp": {"aliases": [], "bad": []},
        "ISS STOXX": {
            "aliases": ["ISS-Corporate"],
            "bad": [
                "国际空间站STOXX",
                "国际航天站STOXX",
                "国际航天局公司",
                "国际航天局",
                "国际空间站",
                "国际航天站",
                "伊斯斯斯托克斯",
                "伊斯斯托克斯",
            ],
        },
        "STOXX": {"aliases": [], "bad": [r"STTOXX", r"(?<![A-Za-z0-9])STOX(?![A-Za-z0-9])", "斯托克斯"]},
        "ICE": {"aliases": ["Intercontinental Exchange"], "bad": ["冰岛", "欧元交易所", "国际大陆交易所", "跨大陆交易"]},
        "SIX": {"aliases": ["SIX Exchanges"], "bad": ["六个交易所", "六个", "六", "西克斯"]},
        "Nasdaq": {"aliases": [], "bad": ["纳斯达克"]},
        "Nasdaq eVestment": {"aliases": [], "bad": ["纳思达克电子投资", "纳斯达克电子投资"]},
        "Nasdaq Verafin": {"aliases": [], "bad": ["纳斯达克Verafin", "纳思达克Verafin", "NasdaqVerafin"]},
        "Alloy": {"aliases": [], "bad": ["合金"]},
        "Trever": {"aliases": [], "bad": ["特雷弗", "雷弗"]},
        "Cboe": {"aliases": [], "bad": []},
        "Euronext": {"aliases": [], "bad": ["欧联网", "欧元联网", "欧元集团"]},
        "LSEG": {"aliases": ["London Stock Exchange Group"], "bad": []},
        "RepoClear": {"aliases": [], "bad": ["雷波克莱尔"]},
        "FTSE Russell": {"aliases": [], "bad": []},
        "FTSE": {"aliases": ["FTSE Russell"], "bad": ["FTC"]},
        "ISS": {"aliases": [], "bad": ["国际空间站", "国际航天站"]},
        "OSC": {"aliases": [], "bad": ["欧安组织"]},
        "Partior": {"aliases": [], "bad": []},
        "Gold-i": {"aliases": [], "bad": ["黄金-i", "黄金－i"]},
        "HashKey": {"aliases": [], "bad": ["哈希基"]},
        "Obita": {"aliases": [], "bad": []},
        "S&P Dow Jones Indices": {"aliases": ["S&P DJI"], "bad": ["斯安普道斯指数"]},
        "Kaiko": {"aliases": [], "bad": ["凯科"]},
        "DTCC": {"aliases": [], "bad": []},
        "FINRA": {"aliases": [], "bad": ["国际金融基金会", "FINA"]},
        "SEC": {"aliases": ["Securities and Exchange Commission"], "bad": ["美国证券交易委员会", "证券交易委员会"]},
        "CFTC": {
            "aliases": ["Commodity Futures Trading Commission"],
            "bad": ["欧盟货币交易委员会", "欧盟CFTC", "欧盟贸易交易委员会", "美国央行", "金融交易委员会", "商品期货交易委员会"],
        },
        "MAS": {"aliases": ["Monetary Authority of Singapore"], "bad": ["马斯"]},
        "Euribor": {"aliases": [], "bad": []},
        "€STR": {"aliases": [], "bad": []},
        "HKEX": {"aliases": ["Hong Kong Exchanges and Clearing"], "bad": ["希克克斯", "希克斯"]},
        "JPX": {"aliases": ["Japan Exchange Group"], "bad": ["日本交流集团", "日本交易所集团"]},
        "FSC": {"aliases": ["Financial Services Commission"], "bad": ["联邦书商管理局", "国际SEC", "国际证券交易委员会"]},
        "IOSCO": {"aliases": ["International Organization of Securities Commissions"], "bad": ["国际证券委员会组织", "国际证券交易委员会组织"]},
        "OCC": {"aliases": ["Office of the Comptroller of the Currency"], "bad": ["欧盟委员会", "欧盟银行"]},
        "ECB": {"aliases": ["European Central Bank"], "bad": ["欧洲央行"]},
        "FOMC": {"aliases": ["Federal Open Market Committee"], "bad": ["联邦开放市场委员会"]},
    }
    FALLBACK_SOURCE_EDITS = {
        "Clearstream": {"清流": "Clearstream"},
        "Deutsche Börse": {"德意志交易所": "Deutsche Börse", "德意志 Börse": "Deutsche Börse"},
        "ISS STOXX": {"伊斯斯斯托克斯": "ISS STOXX", "伊斯斯托克斯": "ISS STOXX"},
        "HashKey": {"哈希基": "HashKey", "HachKey": "HashKey"},
        "HKEX": {"希克克斯": "HKEX", "希克斯": "HKEX"},
        "Eurex": {"欧莱克斯": "Eurex", "欧雷克斯": "Eurex", "欧元交易所": "Eurex"},
        "Crypto Finance": {"加密金融": "Crypto Finance"},
        "Trever": {"特雷弗": "Trever", "雷弗": "Trever"},
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
        "Euronext": {"欧联网": "Euronext", "欧元联网": "Euronext", "欧元集团": "Euronext"},
        "IOSCO": {"国际证券委员会组织": "国际证监会组织", "国际证券交易委员会组织": "国际证监会组织"},
        "OCC": {"欧盟委员会": "OCC", "欧盟银行": "OCC"},
        "SIX": {"六个交易所": "SIX Exchanges", "六个": "SIX", "六": "SIX", "西克斯": "SIX"},
        "ICE": {"冰岛": "ICE", "欧元交易所": "ICE", "国际大陆交易所": "ICE", "跨大陆交易": "ICE"},
        "FINRA": {"国际金融基金会": "FINRA"},
        "FTSE": {"FTC": "FTSE"},
        "MAS": {"马斯": "MAS"},
        "FSC": {"国际SEC": "FSC", "联邦书商管理局": "FSC", "国际证券交易委员会": "FSC"},
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
        "IOSCO": ["iosco", "international organization of securities commissions", "国际证监会组织"],
        "OCC": ["occ", "office of the comptroller of the currency", "货币监理署"],
        "ICE": ["intercontinental exchange", "洲际交易所"],
        "SIX": ["six exchanges", "six group"],
        "FINRA": ["financial industry regulatory authority"],
        "FTSE": ["ftse russell"],
        "Nasdaq": ["nasdaq"],
        "Nasdaq eVestment": ["nasdaq evestment"],
        "Nasdaq Verafin": ["nasdaq verafin"],
        "Alloy": ["alloy"],
        "Trever": ["trever"],
        "Kaiko": ["kaiko"],
        "Euribor": ["euribor"],
        "€STR": ["€str"],
        "FSC": ["financial services commission"],
    }
    TERM_RULES = [
        ("fiat", r"菲亚特", "法定货币"),
        ("spot market", r"零点市场", "现货市场"),
        ("digital asset custody", r"数字资产监管", "数字资产托管"),
        ("Chain of Custody", r"监管链", "托管链"),
        ("Default Fund Contribution", r"默认基金贡献", "违约基金出资"),
        ("FTSE Russell", r"^瑞士证券交易所(?=\s|[（(])", "FTSE Russell"),
        ("Partior", r"^企业(?=与|和|、)", "Partior"),
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
        ("Euronext", r"欧联网", "Euronext"),
        ("Euronext", r"欧元集团", "Euronext"),
        ("Financial Market Infrastructures", r"国际货币基金组织", "金融市场基础设施"),
        ("FMIs", r"国际货币基金组织", "金融市场基础设施"),
        ("IOSCO", r"国际证券委员会组织|国际证券交易委员会组织", "国际证监会组织"),
        ("Office of the Comptroller of the Currency", r"欧盟委员会|欧盟银行", "OCC"),
        ("OCC", r"欧盟委员会|欧盟银行", "OCC"),
        ("portfolio margining", r"投资组合的利率|投资组合利率", "投资组合保证金"),
        ("market maker", r"市场制造商", "做市商"),
        ("market makers", r"市场制造商", "做市商"),
        ("interest rate options", r"利率选项", "利率期权"),
        ("FDIC", r"联邦银行局|联邦金融监管局", "FDIC"),
        ("FSC", r"联邦书商管理局", "FSC"),
        ("Financial Services Commission", r"国际证券交易委员会", "金融服务委员会"),
        ("Intercontinental Exchange", r"欧元交易所", "ICE"),
        ("Deutsche Börse", r"Deutsche Börse\s*德国\s*Börse", "Deutsche Börse"),
        ("Trading Overview", r"贸易概况", "交易概况"),
        ("margin efficiency", r"利率效率", "保证金效率"),
        ("forward transaction", r"前期交易", "远期交易"),
        ("forward transactions", r"前期交易", "远期交易"),
        ("Multi-Dealer FX", r"多经销商外汇", "多交易商外汇"),
        ("Best Asia Multi-Dealer FX Trading Venue", r"亚洲最佳多交易商外汇交易场所", "亚洲最佳多交易商外汇交易平台"),
        ("Canadian Dollar", r"加拿大美元", "加拿大元"),
        ("Canadian dollar", r"加拿大美元", "加拿大元"),
        ("Mexican Peso", r"墨西哥指", "墨西哥比索"),
        ("Mexican peso", r"墨西哥指", "墨西哥比索"),
        ("million contracts", r"万合同", "万合约"),
        ("contracts", r"(?<=\d)合同", "合约"),
        ("€STR", r"ICESTR", "€STR"),
        ("overnight borrowing costs", r"借贷风险率|夜间借款成本|隔夜借贷成本", "隔夜借款成本"),
        ("global capital markets", r"全球资产市场", "全球资本市场"),
        (
            "The New York Stock Exchange, part of Intercontinental Exchange",
            r"(?:纽约证券交易所\s*\(NYSE\s*:\s*ICE\)|隶属于ICE的NYSE),是全球金融市场技术和数据驱动全球资本市场的全球领先供应商之一,以及韩国交易所",
            "纽约证券交易所（NYSE）隶属于ICE，NYSE与韩国交易所",
        ),
        (
            "global investors to some of the world's most innovative companies",
            r"(?:与全球一些最具创新性的投资者进行合作|将连接全球投资者与一些最具创新性的公司)",
            "连接全球投资者与一些最具创新性的公司",
        ),
        ("New York Stock Exchange, part of Intercontinental Exchange", r"纽约证券交易所\s*\(NYSE\s*:\s*ICE\)", "隶属于ICE的NYSE"),
        (
            "Nasdaq Verafin and Alloy Partner to Help",
            r"Nasdaq Verafin和Alloy合作伙伴将帮助",
            "Nasdaq Verafin与Alloy合作，帮助",
        ),
        (
            "ICE is home to Euribor",
            r"ICE是以欧元管理短期利率,以及与欧元区相连的隔夜借款成本的基准,这反映了欧元市场中面临的成本\.",
            "Euribor是管理欧元短期利率风险的基准，€STR反映欧元区银行的欧元无担保批发隔夜借款成本。",
        ),
        (
            "ICE is home to Euribor",
            r"ICE是以欧元管理短期利率,以及与欧元区相连的隔夜借款成本的基准,这反映了欧元市场中面临的成本,使欧元地区的银行对ICE的投资工具表现出这些成本的预期\.",
            "Euribor是管理欧元短期利率风险的基准，€STR反映欧元区银行的欧元无担保批发隔夜借款成本。",
        ),
        (
            "ICE is home to Euribor",
            r"€STR夜间创下330万合[約约]",
            "ICE €STR期货未平仓量达330万合约",
        ),
        ("securities exchange operator", r"证券交换运营商", "证券交易所运营商"),
        ("announced in April 2026", r"希腊股票将在2026年4月重新归类为发达市场", "希腊股票重新归类为发达市场的决定于2026年4月宣布"),
        ("CEO compensation", r"首席执行官补偿|CEO补偿", "CEO薪酬"),
        ("CEO pay", r"首席执行官薪水|CEO薪水", "CEO薪酬"),
        ("executive pay", r"执行官薪酬", "高管薪酬"),
        ("proxy season", r"代理季度", "委托投票季"),
        ("Regulated Market of Frankfurt Stock Exchange", r"法兰克福证券交易所监管机构|监管机构中最大的公司", "法兰克福证券交易所监管市场"),
        (
            "DAX, MDAX, SDAX and TecDAX represent the largest companies",
            r"监管机构中最大的公司",
            "法兰克福证券交易所监管市场中最大的公司",
        ),
        ("Regulated Market", r"监管机构", "监管市场"),
        ("Joint Final Rule with the SEC", r"SEC\s*\(CFTC\)\s*发布了与SEC的联合最终规则", "CFTC与SEC联合发布最终规则"),
        ("registered transfer agents", r"注册转账代理|注册转让代理人|注册转移代理", "注册过户代理机构"),
        ("transfer agents", r"转账代理|转让代理人|转移代理", "过户代理机构"),
        ("national clearance and settlement system", r"国家核准和结算系统|国家清算和结算系统", "全国性证券清算结算体系"),
        ("clearance and settlement", r"核准和结算", "清算与结算"),
        ("member firms", r"成员国公司|成员公司", "会员公司"),
        ("Members Need to Know", r"成员需要知道", "会员需要知道"),
        ("£278 million", r"2\.78亿英(?!镑)", "2.78亿英镑"),
        (
            "domestic political changes and conflict in the Middle East",
            r"中东(?:地区)?的国内政治变化和冲突",
            "国内政治变化和中东地区冲突",
        ),
        (
            "domestic political changes and conflict in the Middle East",
            r"7月出现资金流入\s*尽管国内政治变化和中东地区冲突",
            "尽管国内政治发生变化且中东地区存在冲突，7月基金仍录得资金流入",
        ),
        (
            "Tokenization of Securities Issuance and Circulation",
            r"证券发行与流通的标记化",
            "证券发行与流通的代币化",
        ),
        ("up 12%", r"下升12%", "上升12%"),
        ("S&P Kaiko", r"S&PKaiko", "S&P Kaiko"),
        ("blue-chip index", r"蓝芯片指数", "蓝筹指数"),
        ("asset manager", r"资产经理", "资产管理机构"),
        ("asset managers", r"资产经理", "资产管理机构"),
        ("digital asset firms", r"数字资本公司", "数字资产公司"),
        ("consultation paper", r"协商文件", "征求意见文件"),
        ("asset-level insights", r"资产级洞察|资产水平洞察", "资产层面的洞察"),
        ("open interest", r"开放利率", "未平仓量"),
        ("interest rate swap", r"利率交换", "利率互换"),
        ("interest rate swaps", r"利率交换", "利率互换"),
        ("intraday margin standard", r"日内利标准|日内利润标准|intraday\s*利标准", "日内保证金标准"),
        ("intraday margin", r"日内利(?=要求|规定|规则|安排|计算|管理|模型|框架|更新|适用|$)", "日内保证金"),
        ("intraday margin", r"日内利润(?=要求|规定|规则|安排|计算|管理|模型|框架|更新|适用|$)", "日内保证金"),
        ("stablecoin", r"稳定coin", "稳定币"),
    ]

    PROPER_NOUN_RULES = [
        # Exact incident sentence: the model also inverted investigator and target.
        (
            "FCA opens investigation into Euro Exchange Securities UK Ltd",
            r"^Euro Exchange Securities UK Ltd启动调查$",
            "FCA 对 Euro Exchange Securities UK Ltd 启动调查",
        ),
        ("Singapore", r"新加拿大", "新加坡"),
        ("Republic of Korea", r"韩国共和国", "韩国"),
        ("Korea", r"韩国共和国", "韩国"),
        ("United Kingdom", r"联合王国", "英国"),
        ("UK", r"联合王国", "英国"),
        ("United States", r"美国国", "美国"),
        ("U.S.", r"美国国", "美国"),
        ("Switzerland", r"瑞士兰", "瑞士"),
    ]

    VOLUME_CONTEXT_RE = re.compile(r"\b(?:trading\s+)?volumes?\b|\bmonthly\s+volumes?\b|\bexchange\s+volumes?\b", re.I)
    INDEX_CONTEXT_RE = re.compile(r"\b(?:market\s+index|index\s+series|benchmark\s+index|indices|indexes|ftse)\b", re.I)

    @staticmethod
    def _entity_flags(entity):
        return 0 if re.search(r"\b[A-Z0-9]{2,}\b", entity or "") else re.I

    @classmethod
    def _entity_pattern(cls, entity):
        return r"(?<![A-Za-z0-9])" + re.escape(entity) + r"(?![A-Za-z0-9])"

    @classmethod
    def _contains_entity(cls, text, entity):
        return bool(re.search(cls._entity_pattern(entity), text or "", flags=cls._entity_flags(entity)))

    @classmethod
    def _entity_matches(cls, text, entity):
        return list(re.finditer(cls._entity_pattern(entity), text or "", flags=cls._entity_flags(entity)))

    def _original_has_entity_evidence(self, original, canonical, aliases):
        return bool(self._original_entity_evidence_positions(original, canonical, aliases))

    def _original_entity_evidence_positions(self, original, canonical, aliases):
        matches = [(match.start(), canonical) for match in self._entity_matches(original, canonical)]
        for alias in aliases:
            matches.extend((match.start(), alias) for match in self._entity_matches(original, alias))
        return sorted(matches, key=lambda item: item[0])

    def _protected_entities_in_original_order(self, original):
        entities = []
        seen = set()
        for canonical, spec in self.CANONICAL_ENTITIES.items():
            evidence = self._original_entity_evidence_positions(original, canonical, spec.get("aliases", []))
            if evidence:
                entities.append((evidence[0][0], canonical))
        ordered = []
        for _, canonical in sorted(entities, key=lambda item: item[0]):
            if canonical not in seen:
                ordered.append(canonical)
                seen.add(canonical)
        return ordered

    def _dedupe_protected_entities(self, text, original):
        out = text or ""
        changes = []
        for canonical in self._protected_entities_in_original_order(original):
            pattern = self._entity_pattern(canonical)
            new = re.sub(pattern + r"\s*\(\s*" + pattern + r"\s*\)", canonical, out, flags=self._entity_flags(canonical))
            new = re.sub(pattern + r"\s*（\s*" + pattern + r"\s*）", canonical, new, flags=self._entity_flags(canonical))
            new = re.sub(pattern + r"\s+" + pattern, canonical, new, flags=self._entity_flags(canonical))
            if canonical in {"Nasdaq", "Cboe", "FINRA", "FTSE", "STOXX", "ICE", "SIX", "Eurex", "EEX"}:
                new = re.sub(pattern + r"\s+" + re.escape(canonical) + r"(?=[A-Za-z])", canonical + " ", new, flags=self._entity_flags(canonical))
            if new != out:
                out = new
                changes.append(f"{canonical}:dedupe_entity")
        return out, changes

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
                    if canonical == "ISS" and bad in ("国际空间站", "国际航天站") and re.search(
                        r"\bInternational Space Station\b", original or "", flags=re.I
                    ):
                        continue
                    if canonical == "FSC" and bad == "国际证券交易委员会" and re.search(
                        r"\bFinancial Services Commission\b", original or "", flags=re.I
                    ):
                        continue
                    replace(bad if bad.startswith("(?<") else re.escape(bad), canonical, canonical)

        for brand, replacements in self.source_edits.items():
            aliases = self.CONTEXT_ALIASES.get(brand, [])
            has_context = self._original_has_entity_evidence(original, brand, aliases)
            if has_context:
                for bad, good in replacements.items():
                    if brand == "ICE" and bad == "冰岛" and re.search(r"\bIceland(?:ic)?\b", original or "", flags=re.I):
                        continue
                    if brand == "SIX" and bad in ("六", "六个") and re.search(r"\bsix\b", original or ""):
                        continue
                    if brand == "FSC" and bad == "国际证券交易委员会" and re.search(
                        r"\bFinancial Services Commission\b", original or "", flags=re.I
                    ):
                        continue
                    replace(re.escape(bad), good, good)

        for source_term, bad_pattern, good in self.TERM_RULES:
            if source_term.lower() in original_lower:
                replace(bad_pattern, good, source_term)

        for source_term, bad_pattern, good in self.PROPER_NOUN_RULES:
            if self._contains_entity(original, source_term):
                replace(bad_pattern, good, source_term)

        if self.VOLUME_CONTEXT_RE.search(original or ""):
            replace(r"月份卷|月份数量|报告卷|(?<![一-龥])卷(?![一-龥])", "交易量", "trading volume")

        if self.INDEX_CONTEXT_RE.search(original or ""):
            replace(r"索引", "指数", "financial index")

        missing_entities = []
        for canonical in self._protected_entities_in_original_order(original):
            if not self._contains_entity(out, canonical):
                missing_entities.append(canonical)
                changes.append(f"{canonical}:restore_missing_entity")
        if missing_entities:
            out = " ".join(missing_entities + [out]).strip()

        out, dedupe_changes = self._dedupe_protected_entities(out, original)
        changes.extend(dedupe_changes)

        for brand in self.source_edits:
            brand_pattern = r"^\s*" + re.escape(brand) + r"(?:['’]s)?\b"
            if re.search(brand_pattern, original or "", flags=self._entity_flags(brand)) and brand not in out:
                out = f"{brand} {out}".strip()
                changes.append(f"{brand}:restore_leading_brand")

        out, dedupe_changes = self._dedupe_protected_entities(out, original)
        changes.extend(dedupe_changes)

        return out.strip(), changes


class TitleTranslator:
    RECOVERABLE_SEMANTIC_ISSUES = {
        "translation_title_proposition_missing",
        "translation_action_direction_missing",
        "translation_relationship_missing",
        "translation_suspicious_compression",
    }
    SEMANTIC_SEGMENT_CAP = 6

    def __init__(self, enabled=True, logger=None, provider=None, strict=False):
        self.enabled = enabled
        self.logger = logger
        self.provider = provider
        self.strict = strict
        self.normalizer = TerminologyNormalizer()
        self.cache = {}
        self.cache_dirty = False
        self.last_semantic_recovery_metadata = {}
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
    def _semantic_field_issues(text, translated, field, source):
        from crawler.translation_quality import FAIL, validate_translation_field

        return [
            issue
            for issue in validate_translation_field(
                original=text,
                translated=translated,
                field_type=field,
                source=source,
                title_original=text if field == "title" else "",
            )
            if issue.get("severity") == FAIL
        ]

    def _recoverable_semantic_issues(self, text, translated, field, source):
        issues = self._semantic_field_issues(text, translated, field, source)
        return [issue for issue in issues if issue.get("issue_id") in self.RECOVERABLE_SEMANTIC_ISSUES]

    @staticmethod
    def _safe_semantic_split(pattern, text):
        pieces = []
        for piece in re.split(pattern, text, flags=re.I):
            stripped = piece.strip()
            if stripped:
                pieces.append(stripped)
        return pieces

    def _merge_semantic_segments_to_cap(self, segments):
        merged = [segment for segment in segments if segment and segment.strip()]
        while len(merged) > self.SEMANTIC_SEGMENT_CAP:
            best_index = min(range(len(merged) - 1), key=lambda index: len(merged[index]) + len(merged[index + 1]))
            merged[best_index : best_index + 2] = [f"{merged[best_index]} {merged[best_index + 1]}".strip()]
        return merged

    def _semantic_segments(self, text):
        normalized = re.sub(r"\s+", " ", text or "").strip()
        if not normalized:
            return []
        boundaries = [
            r"\s+\|\s+",
            r"\s+[—–]\s+",
            r";\s+",
            r":\s+",
            r"\s+(?=\b(?:despite|while|although|whereas|but|which|that|including|as part of|and what)\b)",
            r"\s+(?=\bwith\s+(?:a|an|the)\b)",
            r"\s+(?=\bto\s+(?:rescind|repeal|revoke|suspend|approve|extend)\b)",
            r"\s+(?=\b(?:launch(?:es|ed|ing)?|introduc(?:es|ed|ing)?|offer(?:s|ed|ing)?)\b)",
            r"\s+(?=\bbased\s+on\b)",
        ]
        segments = [normalized]
        for boundary in boundaries:
            next_segments = []
            for segment in segments:
                next_segments.extend(self._safe_semantic_split(boundary, segment))
            segments = next_segments
        useful = []
        carry = ""
        for segment in segments:
            segment = segment.strip(" ,")
            if not segment:
                continue
            token_count = len(re.findall(r"\S+", segment))
            if token_count < 2 and useful:
                useful[-1] = f"{useful[-1]} {segment}".strip()
            elif token_count < 2:
                carry = f"{carry} {segment}".strip()
            elif carry:
                useful.append(f"{carry} {segment}".strip())
                carry = ""
            else:
                useful.append(segment)
        if carry:
            if useful:
                useful[-1] = f"{useful[-1]} {carry}".strip()
            else:
                useful.append(carry)
        useful = self._merge_semantic_segments_to_cap(useful)
        if len(useful) <= 1:
            return []
        return useful

    def _log_semantic_recovery_diagnostics(self):
        if not self.logger:
            return
        metadata = self.last_semantic_recovery_metadata or {}
        if not metadata.get("semantic_recovery_triggered"):
            return
        self.logger.warning(
            "Translation semantic recovery: field=%s triggering_issue_ids=%s segment_count=%s "
            "original_hash=%s recovery_result=%s selected=%s",
            metadata.get("field"),
            metadata.get("triggering_issue_ids"),
            metadata.get("segment_count"),
            metadata.get("original_hash"),
            metadata.get("recovery_validation_result"),
            metadata.get("recovered_output_selected"),
        )

    def _semantic_recovery(self, provider, text, source, field, initial_translation, initial_issues):
        segments = self._semantic_segments(text)
        issue_ids = sorted({issue.get("issue_id") for issue in initial_issues})
        self.last_semantic_recovery_metadata = {
            "semantic_recovery_triggered": bool(segments),
            "field": field,
            "original_hash": hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12],
            "triggering_issue_ids": issue_ids,
            "segment_count": len(segments),
            "initial_validation_result": "FAIL",
            "recovery_validation_result": "not_attempted",
            "recovered_output_selected": False,
        }
        if not segments:
            self._log_semantic_recovery_diagnostics()
            return initial_translation, False, []

        translated_segments = []
        try:
            for segment in segments:
                translated = self._provider_translate(provider, segment, SOURCE_CHUNK_TOKEN_LIMIT)
                if not translated:
                    self.last_semantic_recovery_metadata["recovery_validation_result"] = "provider_error"
                    self._log_semantic_recovery_diagnostics()
                    return initial_translation, False, initial_issues
                translated_segments.append(translated)
        except Exception:
            self.last_semantic_recovery_metadata["recovery_validation_result"] = "provider_error"
            self._log_semantic_recovery_diagnostics()
            return initial_translation, False, initial_issues

        recovered_raw = " ".join(translated_segments).strip()
        recovered_normalized, _ = self.normalizer.normalize(recovered_raw, text, source)
        recovered_issues = self._semantic_field_issues(text, recovered_normalized, field, source)
        self.last_semantic_recovery_metadata["recovery_validation_result"] = "PASS" if not recovered_issues else "FAIL"
        if not recovered_issues:
            self.last_semantic_recovery_metadata["recovered_output_selected"] = True
            self._log_semantic_recovery_diagnostics()
            return recovered_normalized, True, []
        self._log_semantic_recovery_diagnostics()
        return recovered_normalized, False, recovered_issues

    @staticmethod
    def _effective_recovery_chunk_limit(
        initial_metadata,
        configured_max=RECOVERY_SOURCE_CHUNK_TOKEN_LIMIT,
        min_limit=MIN_RECOVERY_SOURCE_CHUNK_TOKEN_LIMIT,
    ):
        token_counts = [
            count
            for count in (initial_metadata.get("chunk_token_counts") or [])
            if isinstance(count, int) and count > 0
        ]
        if not token_counts:
            return configured_max

        largest_failed_chunk = max(token_counts)
        if largest_failed_chunk <= 1:
            return 1

        effective = min(
            configured_max,
            max(min_limit, (largest_failed_chunk + 1) // 2),
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
        tier2_attempted=False,
        tier2_translation="",
        tier2_validation=None,
        tier2_metadata=None,
        initial_raw_translation="",
        recovery_raw_translation="",
        tier2_raw_translation="",
    ):
        if not self.logger:
            return
        final_validation = tier2_validation or recovery_validation or initial_validation
        final_raw_translation = tier2_raw_translation or recovery_raw_translation or initial_raw_translation
        final_normalized_translation = tier2_translation or recovery_translation or initial_translation
        self.logger.warning(
            "Translation length-ratio recovery diagnostics: "
            "source=%s field=%s text_prefix=%r original_raw_length=%s original_content_length=%s "
            "translated_raw_length=%s translated_content_length=%s raw_ratio=%.3f normalized_content_ratio=%.3f "
            "pre_normalization_content_length=%s post_normalization_content_length=%s "
            "initial_reason=%s initial_chunk_limit=%s initial_chunk_count=%s "
            "initial_chunk_token_counts=%s initial_chunk_output_lengths=%s "
            "recovery_attempted=%s configured_recovery_chunk_limit=%s effective_recovery_chunk_limit=%s "
            "recovery_chunk_count=%s recovery_chunk_token_counts=%s recovery_chunk_output_lengths=%s "
            "tier1_effective_chunk_limit=%s tier1_chunk_count=%s tier1_chunk_token_counts=%s "
            "tier1_chunk_output_lengths=%s tier1_output_length=%s tier1_content_ratio=%.3f tier1_reason=%s "
            "tier2_attempted=%s tier2_effective_chunk_limit=%s tier2_chunk_count=%s "
            "tier2_chunk_token_counts=%s tier2_chunk_output_lengths=%s tier2_output_length=%s "
            "tier2_content_ratio=%.3f tier2_reason=%s initial_output_length=%s "
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
            self._content_length(final_raw_translation),
            self._content_length(final_normalized_translation),
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
            (recovery_metadata or {}).get("chunk_output_lengths"),
            (recovery_metadata or {}).get("chunk_token_limit"),
            (recovery_metadata or {}).get("chunk_count"),
            (recovery_metadata or {}).get("chunk_token_counts"),
            (recovery_metadata or {}).get("chunk_output_lengths"),
            len(recovery_translation or ""),
            self._content_ratio(text, recovery_translation),
            (recovery_validation or initial_validation).reason,
            tier2_attempted,
            (tier2_metadata or {}).get("chunk_token_limit"),
            (tier2_metadata or {}).get("chunk_count"),
            (tier2_metadata or {}).get("chunk_token_counts"),
            (tier2_metadata or {}).get("chunk_output_lengths"),
            len(tier2_translation or ""),
            self._content_ratio(text, tier2_translation) if tier2_attempted else 0.0,
            (tier2_validation or ValidationResult(False, "not_attempted")).reason if tier2_attempted else "not_attempted",
            len(initial_translation or ""),
            len(recovery_translation or ""),
            self._length_ratio(text, initial_translation),
            self._content_ratio(text, final_normalized_translation),
            final_validation.reason,
        )

    def _log_rejection_diagnostics(self, source, field, text, raw, normalized, changes, validation):
        if not self.logger:
            return
        critical_term = ""
        if validation.reason.startswith("critical_term_missing:"):
            critical_term = validation.reason.split(":", 1)[1]
        original_entity_evidence = False
        restoration_attempted = False
        restoration_changed_output = False
        if critical_term:
            spec = self.normalizer.CANONICAL_ENTITIES.get(critical_term, {})
            original_entity_evidence = self.normalizer._original_has_entity_evidence(
                text,
                critical_term,
                spec.get("aliases", []),
            )
            restoration_labels = (
                f"{critical_term}:restore_missing_entity",
                f"{critical_term}:restore_leading_brand",
            )
            restoration_attempted = any(change in restoration_labels for change in changes)
            restoration_changed_output = restoration_attempted and raw != normalized
        self.logger.warning(
            "Translation rejected by sanity validator: reason=%s critical_term=%s source=%s field=%s "
            "original_entity_evidence=%s restoration_attempted=%s restoration_changed_output=%s "
            "original_prefix=%r raw_prefix=%r normalized_prefix=%r",
            validation.reason,
            critical_term,
            source,
            field,
            original_entity_evidence,
            restoration_attempted,
            restoration_changed_output,
            (text or "")[:120],
            (raw or "")[:120],
            (normalized or "")[:120],
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
                self.last_semantic_recovery_metadata = {"semantic_recovery_triggered": False, "cache_hit": True}
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
                tier2_raw = ""
                tier2_normalized = ""
                tier2_changes = []
                tier2_validation = None
                tier2_metadata = None
                if recovered_validation.reason == "content_ratio_low":
                    tier2_chunk_limit = self._effective_recovery_chunk_limit(
                        recovery_metadata,
                        configured_max=RECOVERY_SOURCE_CHUNK_TOKEN_LIMIT,
                        min_limit=MIN_TIER2_SOURCE_CHUNK_TOKEN_LIMIT,
                    )
                    tier2_raw = self._provider_translate(provider, text, tier2_chunk_limit)
                    tier2_metadata = self._provider_metadata(provider)
                    tier2_normalized, tier2_changes = self.normalizer.normalize(tier2_raw, text, source)
                    tier2_validation = TranslationSanityValidator.validate_with_reason(
                        text, tier2_normalized, source, field=field
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
                    tier2_validation is not None,
                    tier2_normalized,
                    tier2_validation,
                    tier2_metadata,
                    raw,
                    recovered_raw,
                    tier2_raw,
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
                if tier2_raw and tier2_validation and tier2_validation.valid:
                    self.cache[key] = {
                        "translation": tier2_normalized,
                        "raw_translation": tier2_raw,
                        "terminology_changes": tier2_changes,
                        "model": provider.model_name,
                        "generation_config_version": GENERATION_CONFIG_VERSION,
                        "glossary_version": self.normalizer.version,
                        "recovered_from": f"tier2:{recovered_validation.reason}",
                    }
                    self.cache_dirty = True
                    return tier2_normalized
                validation = recovered_validation
                raw = recovered_raw
                normalized = recovered_normalized
                changes = recovered_changes
                if tier2_validation is not None:
                    validation = tier2_validation
                    raw = tier2_raw
                    normalized = tier2_normalized
                    changes = tier2_changes

            self._log_rejection_diagnostics(source, field, text, raw, normalized, changes, validation)
            if self.strict:
                raise TranslationUnavailableError(
                    f"translation rejected by sanity validator: reason={validation.reason} "
                    f"source={source!r} field={field} text={text[:120]!r}"
                )
            return ""

        semantic_issues = self._recoverable_semantic_issues(text, normalized, field, source)
        if semantic_issues:
            semantic_recovered, selected, final_semantic_issues = self._semantic_recovery(
                provider,
                text,
                source,
                field,
                normalized,
                semantic_issues,
            )
            semantic_issue_ids = sorted({issue.get("issue_id") for issue in final_semantic_issues or semantic_issues})
            cache_value = {
                "translation": semantic_recovered,
                "raw_translation": raw,
                "terminology_changes": changes,
                "model": provider.model_name,
                "generation_config_version": GENERATION_CONFIG_VERSION,
                "glossary_version": self.normalizer.version,
                "semantic_recovery_triggered": self.last_semantic_recovery_metadata.get("semantic_recovery_triggered", False),
                "semantic_recovery_selected": selected,
                "semantic_issue_ids": semantic_issue_ids,
            }
            self.cache[key] = cache_value
            self.cache_dirty = True
            return semantic_recovered

        self.last_semantic_recovery_metadata = {
            "semantic_recovery_triggered": False,
            "field": field,
            "triggering_issue_ids": [],
            "segment_count": 0,
            "initial_validation_result": "PASS",
            "recovery_validation_result": "not_attempted",
            "recovered_output_selected": False,
        }
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

            if self.enabled:
                from crawler.translation_quality import apply_critical_action_safe_fallback

                clean, _ = apply_critical_action_safe_fallback(clean)
            translated.append(clean)

        if self.enabled and self.cache_dirty:
            _save_cache(self.cache, self.logger)
        return translated
