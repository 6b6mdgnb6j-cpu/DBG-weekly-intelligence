import re
from datetime import date

from crawler.translator import TerminologyNormalizer, TranslationSanityValidator


FAIL = "FAIL"
WARNING = "WARNING"


PROPER_NOUN_RULES = [
    ("Singapore", ("新加坡",), ("新加拿大",)),
    ("Indonesia", ("印度尼西亚", "印尼"), ("新加拿大",)),
    ("United States", ("美国",), ("美国国",)),
    ("U.S.", ("美国",), ("美国国",)),
    ("Switzerland", ("瑞士",), ("瑞士兰",)),
    ("Canadian Dollar", ("加拿大元",), ("加拿大美元",)),
    ("Canadian dollar", ("加拿大元",), ("加拿大美元",)),
    ("Mexican Peso", ("墨西哥比索",), ("墨西哥指",)),
    ("Mexican peso", ("墨西哥比索",), ("墨西哥指",)),
]

SUBSTANTIVE_TITLE_ANCHORS = [
    ("inflow", (r"\binflows?\b", r"\boutflows?\b"), ("流入", "流出", "资金流")),
    ("launch", (r"\blaunch(?:es|ed|ing)?\b", r"\bintroduc(?:e|es|ed|ing)\b"), ("推出", "正式推出", "启动", "上线", "开始提供", "发布", "引入", "发起")),
    ("acquire", (r"\bacquir(?:e|es|ed|ing)\b", r"\bacquisition\b"), ("收购", "并购")),
    ("propose", (r"\bpropos(?:e|es|ed|al)\b",), ("提议", "拟", "建议", "提出")),
    ("rescind", (r"\brescind(?:s|ed|ing)?\b", r"\brescission\b", r"\brepeal(?:s|ed|ing)?\b", r"\brevok(?:e|es|ed|ing)\b", r"\brevocation\b"), ("取消", "撤销", "废除", "撤回")),
    ("approve", (r"\bapprov(?:e|es|ed|ing|al)\b",), ("批准", "核准", "获批", "被批准", "认可")),
    ("suspend", (r"\bsuspend(?:s|ed|ing)?\b",), ("暂停", "中止")),
    ("extend", (r"\bextend(?:s|ed|ing)?\b",), ("延长", "延期", "扩大", "扩展")),
    (
        "increase",
        (r"\bincreas(?:e|es|ed|ing)\b", r"\bgrowth\b", r"\brise\b", r"\brais(?:e|es|ed|ing)\b", r"\brecord\b"),
        ("增长", "增加", "上升", "提升", "提高", "创纪录"),
    ),
    (
        "decrease",
        (r"\breduc(?:e|es|ed|ing|tion)\b", r"\bdecreas(?:e|es|ed|ing)\b", r"\bdeclin(?:e|es|ed|ing)\b", r"\bfall\b", r"\bcut(?:s|ting)?\b"),
        ("下降", "减少", "下滑", "降低", "下调"),
    ),
    ("partner", (r"\bpartner(?:s|ed|ing|ship)?\b",), ("合作", "伙伴")),
    ("clear", (r"\bclear(?:s|ed|ing)?\b", r"\bclearing\b"), ("清算",)),
    ("settle", (r"\bsettle(?:s|d|ment)?\b", r"\bsettlement\b"), ("结算",)),
]

ACTION_DIRECTION_RULES = [
    ("rescind", (r"\brescind(?:s|ed|ing)?\b", r"\brescission\b", r"\brepeal(?:s|ed|ing)?\b", r"\brevok(?:e|es|ed|ing)\b"), ("取消", "撤销", "废除", "撤回")),
    ("propose", (r"\bpropos(?:e|es|ed|al)\b",), ("提议", "拟", "建议", "提出")),
    ("extend", (r"\bextend(?:s|ed|ing)?\b",), ("延长", "延期", "扩大", "扩展")),
    ("approve", (r"\bapprov(?:e|es|ed|ing|al)\b",), ("批准", "核准", "获批", "被批准", "认可")),
    ("ban", (r"\bban(?:s|ned|ning)?\b", r"\bprohibit(?:s|ed|ing)?\b"), ("禁止",)),
    (
        "allow",
        (
            r"\ballow(?:s|ed|ing)?\b",
            r"\bpermit(?:s|ted|ting)?\b",
            r"\blicen[cs](?:e|es|ed|ing)?\b",
            r"\bauthoriz(?:e|es|ed|ing|ation)\b",
        ),
        ("允许", "许可", "经许可", "获准", "准许", "授权", "经授权", "持牌"),
    ),
    ("increase", (r"\bincreas(?:e|es|ed|ing)\b", r"\brais(?:e|es|ed|ing)\b"), ("增长", "增加", "上升", "提升", "提高")),
    ("decrease", (r"\bdecreas(?:e|es|ed|ing)\b", r"\breduc(?:e|es|ed|ing|tion)\b", r"\bcut(?:s|ting)?\b"), ("下降", "减少", "下滑", "降低", "下调")),
]

TREND_PROPOSITION_RULES = (
    (
        "increase",
        (r"\b(?:notable\s+)?(?:increase|growth|rise)\s+in\b",),
        ("增长", "增加", "上升", "提升", "提高"),
    ),
    (
        "decrease",
        (r"\b(?:notable\s+)?(?:decrease|decline|fall|reduction)\s+in\b",),
        ("下降", "减少", "下滑", "降低"),
    ),
)

DESCRIPTIVE_TREND_CONTEXT = (
    r"\bhighlight(?:s|ed|ing)?\b",
    r"\bshow(?:s|ed|ing)?\b",
    r"\breport(?:s|ed|ing)?\b",
    r"\bstatistics?\b",
    r"\bdata\b",
    r"\bindicat(?:e|es|ed|ing)\b",
    r"\breveal(?:s|ed|ing)?\b",
    r"\bobserv(?:e|es|ed|ing|ation)\b",
)

AGENTIVE_TREND_CONTEXT = (
    r"\bannounc(?:e|es|ed|ing|ement)\b",
    r"\bapprov(?:e|es|ed|ing|al)\b",
    r"\bimpos(?:e|es|ed|ing)\b",
    r"\badopt(?:s|ed|ing|ion)?\b",
    r"\bset(?:s|ting)?\b",
    r"\bmandat(?:e|es|ed|ing|ory)\b",
    r"\brequir(?:e|es|ed|ing|ement)\b",
)

CRITICAL_ACTION_FALLBACK_FAMILIES = {
    "rescind": {
        "patterns": (
            r"\brescind(?:s|ed|ing)?\b",
            r"\brescission\b",
            r"\brepeal(?:s|ed|ing)?\b",
            r"\brevok(?:e|es|ed|ing)\b",
            r"\brevocation\b",
        ),
        "signals": ("取消", "撤销", "废除", "撤回"),
    }
}

DANGEROUS_ENTITY_VARIANTS = {
    "ISS STOXX": ("国际空间站STOXX", "国际航天站STOXX", "国际航天局公司", "国际航天局", "国际空间站", "国际航天站"),
    "STOXX": ("STTOXX", "STOX", "斯托克斯"),
    "ICE": ("冰岛", "欧元交易所", "国际大陆交易所", "跨大陆交易"),
    "SIX": ("六个交易所",),
    "Euronext": ("欧联网", "欧元联网", "欧元集团"),
    "FTSE": ("FTC",),
    "FINRA": ("国际金融基金会", "FINA"),
    "FSC": ("联邦书商管理局", "国际SEC", "国际证券交易委员会"),
    "CFTC": ("欧盟货币交易委员会", "欧盟CFTC", "欧盟贸易交易委员会", "美国央行", "金融交易委员会"),
    "IOSCO": ("国际证券委员会组织", "国际证券交易委员会组织"),
    "OCC": ("欧盟委员会", "欧盟银行"),
    "RepoClear": ("雷波克莱尔",),
    "FTSE Russell": ("瑞士证券交易所",),
    "ISS": ("国际空间站", "国际航天站"),
    "OSC": ("欧安组织",),
    "Gold-i": ("黄金-i", "黄金－i"),
}

ACCEPTABLE_ENTITY_RENDERINGS = {
    "SEC": ("SEC", "美国证券交易委员会", "证券交易委员会"),
    "Nasdaq": ("Nasdaq", "纳斯达克", "纳思达克"),
    "JPX": ("JPX", "日本交易所集团"),
    "Crypto Finance": ("Crypto Finance", "加密金融"),
    "S&P Dow Jones Indices": ("S&P Dow Jones Indices", "S&P", "标普道琼斯指数"),
    "MAS": ("MAS", "新加坡金融管理局", "新加坡货币管理局", "马斯"),
    "ECB": ("ECB", "欧洲央行", "欧洲中央银行"),
    "FOMC": ("FOMC", "联邦公开市场委员会", "联邦开放市场委员会"),
    "Euronext": ("Euronext", "泛欧交易所"),
    "IOSCO": ("IOSCO", "国际证监会组织"),
    "OCC": ("OCC", "货币监理署"),
    "OSC": ("OSC", "安大略省证券委员会"),
}

MATERIAL_TERM_RULES = [
    {
        "issue_id": "translation_material_term_conflict",
        "trigger_patterns": (r"\bfiat\b",),
        "bad_terms": ("菲亚特",),
        "expected_terms": ("法定货币",),
        "term": "fiat",
        "reason": "Fiat currency was translated as an unrelated proper noun.",
    },
    {
        "issue_id": "translation_material_term_conflict",
        "trigger_patterns": (r"\bspot market\b",),
        "bad_terms": ("零点市场",),
        "expected_terms": ("现货市场",),
        "term": "spot market",
        "reason": "Spot market was translated as an unrelated time/point concept.",
    },
    {
        "issue_id": "translation_material_term_conflict",
        "trigger_patterns": (r"\bdigital asset custody\b", r"\bcustody support\b"),
        "bad_terms": ("数字资产监管", "监管支持"),
        "expected_terms": ("数字资产托管", "托管支持"),
        "term": "digital asset custody",
        "reason": "Custody was translated as regulatory supervision.",
    },
    {
        "issue_id": "translation_material_term_conflict",
        "trigger_patterns": (r"\bDefault Fund Contribution\b",),
        "bad_terms": ("默认基金贡献",),
        "expected_terms": ("违约基金出资", "违约基金缴款"),
        "term": "Default Fund Contribution",
        "reason": "CCP Default Fund Contribution was translated literally and lost its financial meaning.",
    },
    {
        "issue_id": "translation_material_term_conflict",
        "trigger_patterns": (r"\bFMIs?\b", r"\bFinancial Market Infrastructures?\b"),
        "bad_terms": ("国际货币基金组织",),
        "expected_terms": ("金融市场基础设施", "FMI", "FMIs"),
        "term": "Financial Market Infrastructures",
        "reason": "Financial Market Infrastructures/FMI was translated as IMF.",
    },
    {
        "issue_id": "translation_material_term_conflict",
        "trigger_patterns": (r"\bportfolio margining\b",),
        "bad_terms": ("投资组合的利率", "投资组合利率"),
        "expected_terms": ("投资组合保证金", "组合保证金"),
        "term": "portfolio margining",
        "reason": "Portfolio margining was translated as an interest-rate concept.",
    },
]


def _contains_english(text, patterns):
    return any(re.search(pattern, text or "", flags=re.I) for pattern in patterns)


def _contains_any(text, terms):
    return any(term in (text or "") for term in terms)


def _contains_bad_variant(text, variant):
    if re.fullmatch(r"[A-Za-z0-9 &.-]+", variant or ""):
        return bool(re.search(r"(?<![A-Za-z0-9])" + re.escape(variant) + r"(?![A-Za-z0-9])", text or "", flags=re.I))
    return variant in (text or "")


def _issue(index, item, field, issue_id, severity, evidence, reason):
    return {
        "type": issue_id,
        "issue_id": issue_id,
        "severity": severity,
        "index": index,
        "source": item.get("source", ""),
        "date": item.get("date", ""),
        "field": field,
        "title_original": item.get("title_original") or item.get("title") or "",
        "evidence": evidence,
        "reason": reason,
    }


def _critical_action_family(original):
    for family, spec in CRITICAL_ACTION_FALLBACK_FAMILIES.items():
        if _contains_english(original, spec["patterns"]):
            return family
    return ""


def _translated_fields(item):
    return [
        ("title", item.get("title_original") or item.get("title") or "", item.get("title_cn") or ""),
        ("summary", item.get("summary_original") or item.get("summary") or "", item.get("summary_cn") or ""),
    ]


def _meaningful_text(text):
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return False
    return bool(re.search(r"[A-Za-z\u4e00-\u9fff]{8,}", normalized))


def _entity_issues(index, item, normalizer):
    issues = []
    for field, original, translated in _translated_fields(item):
        if not original or not translated:
            continue
        checked_hard_entities = set()
        for canonical, _preserved, evidence in normalizer.protected_entity_occurrences(original):
            if canonical in checked_hard_entities:
                continue
            checked_hard_entities.add(canonical)
            acceptable_renderings = ACCEPTABLE_ENTITY_RENDERINGS.get(canonical, (canonical,))
            if _contains_any(translated, acceptable_renderings):
                continue
            spec = normalizer.CANONICAL_ENTITIES.get(canonical, {})
            candidate_forms = [canonical, *spec.get("aliases", []), *spec.get("bad", [])]
            candidate_forms.extend(normalizer.ENTITY_TRANSPORT_VARIANTS.get(canonical, ()))
            issues.append(
                _issue(
                    index,
                    item,
                    field,
                    "translation_entity_alignment_failure",
                    FAIL,
                    {
                        "source": item.get("source") or "",
                        "field": field,
                        "entity": canonical,
                        "occurrence": 1,
                        "stage": "finalization",
                        "original_excerpt": original[:240],
                        "model_output_excerpt": translated[:240],
                        "candidate_forms": candidate_forms,
                        "evidence": evidence,
                    },
                    "A hard-protected business entity could not be confidently aligned in the translation.",
                )
            )
        for canonical, spec in normalizer.CANONICAL_ENTITIES.items():
            if not normalizer._original_has_entity_evidence(original, canonical, spec.get("aliases", [])):
                continue
            dangerous_variants = DANGEROUS_ENTITY_VARIANTS.get(canonical, ())
            has_dangerous_variant = any(_contains_bad_variant(translated, bad) for bad in dangerous_variants)
            acceptable_renderings = ACCEPTABLE_ENTITY_RENDERINGS.get(canonical, (canonical,))
            has_acceptable_rendering = _contains_any(translated, acceptable_renderings)
            original_has_canonical = normalizer._contains_entity(original, canonical)
            if (
                original_has_canonical
                and canonical not in checked_hard_entities
                and not normalizer._contains_entity(translated, canonical)
                and not has_acceptable_rendering
            ):
                issues.append(
                    _issue(
                        index,
                        item,
                        field,
                        "translation_entity_missing",
                        FAIL,
                        {"entity": canonical, "translated_prefix": translated[:160]},
                        "Protected financial entity present in original is missing from translation.",
                    )
                )
            for bad in dangerous_variants:
                if canonical == "ICE" and bad == "冰岛" and re.search(r"\bIceland(?:ic)?\b", original, flags=re.I):
                    continue
                if _contains_bad_variant(translated, bad):
                    issues.append(
                        _issue(
                            index,
                            item,
                            field,
                            "translation_entity_conflict",
                            FAIL,
                            {"entity": canonical, "bad_variant": bad, "translated_prefix": translated[:160]},
                            "Translation contains a conflicting hallucinated variant of a protected entity.",
                        )
                    )
            pattern = normalizer._entity_pattern(canonical)
            if re.search(pattern + r"\s*\(\s*" + pattern + r"\s*\)", translated, flags=normalizer._entity_flags(canonical)):
                issues.append(
                    _issue(
                        index,
                        item,
                        field,
                        "translation_entity_duplicate",
                        WARNING,
                        {"entity": canonical, "translated_prefix": translated[:160]},
                        "Translation contains duplicated canonical entity text.",
                    )
                )
    return issues


def _sanity_quality_issues(index, item):
    issues = []
    for diagnostic in item.get("translation_quality_issues") or []:
        if diagnostic.get("issue_id") != "translation_sanity_quality_failure":
            continue
        evidence = diagnostic.get("evidence") or {}
        reason = evidence.get("reason") or "unknown"
        field = evidence.get("field") or "text"
        issues.append(
            _issue(
                index,
                item,
                field,
                "translation_sanity_quality_failure",
                FAIL,
                {"sanity_reason": reason},
                f"Translation sanity quality check failed: {reason}",
            )
        )
    return issues


def _standalone_sanity_quality_issues(index, item):
    issues = []
    for field, original, translated in _translated_fields(item):
        if not original or not translated:
            continue
        validation = TranslationSanityValidator.validate_with_reason(
            original,
            translated,
            item.get("source") or "",
            field=field,
        )
        if validation.valid or TranslationSanityValidator.is_fatal_reason(validation.reason):
            continue
        issues.append(
            _issue(
                index,
                item,
                field,
                "translation_sanity_quality_failure",
                FAIL,
                {"sanity_reason": validation.reason},
                f"Translation sanity quality check failed: {validation.reason}",
            )
        )
    return issues


def _material_term_issues(index, item):
    issues = []
    source = item.get("source") or ""
    for field, original, translated in _translated_fields(item):
        if not original or not translated:
            continue
        for rule in MATERIAL_TERM_RULES:
            if not _contains_english(original, rule["trigger_patterns"]):
                continue
            if not _contains_any(translated, rule["bad_terms"]):
                continue
            issues.append(
                _issue(
                    index,
                    item,
                    field,
                    rule["issue_id"],
                    FAIL,
                    {
                        "term": rule["term"],
                        "bad_terms": list(rule["bad_terms"]),
                        "expected_terms": list(rule["expected_terms"]),
                        "translated_prefix": translated[:160],
                    },
                    rule["reason"],
                )
            )
        occ_context = (
            re.search(r"\bOCC\b|\bOffice of the Comptroller of the Currency\b", original or "", flags=re.I)
            or "货币监理署" in source
        )
        if occ_context and _contains_any(translated, ("欧盟委员会", "欧盟银行")):
            issues.append(
                _issue(
                    index,
                    item,
                    field,
                    "translation_entity_conflict",
                    FAIL,
                    {"entity": "OCC", "bad_terms": ["欧盟委员会", "欧盟银行"], "translated_prefix": translated[:160]},
                    "OCC context was translated as an unrelated European institution.",
                )
            )
    return issues


def _bilingual_completeness_issues(index, item, translation_mode):
    if translation_mode != "bilingual":
        return []
    summary_original = item.get("summary_original")
    if summary_original is None:
        summary_original = item.get("summary") or ""
    if not _meaningful_text(summary_original):
        return []
    if (item.get("summary_cn") or "").strip():
        return []
    return [
        _issue(
            index,
            item,
            "summary",
            "translation_summary_missing",
            FAIL,
            {"summary_original_prefix": str(summary_original)[:160]},
            "Bilingual artifact has a meaningful original summary but an empty Chinese summary.",
        )
    ]


def _proper_noun_issues(index, item):
    issues = []
    for field, original, translated in _translated_fields(item):
        if not original or not translated:
            continue
        for original_term, expected_terms, bad_terms in PROPER_NOUN_RULES:
            if not re.search(r"(?<![A-Za-z0-9])" + re.escape(original_term) + r"(?![A-Za-z0-9])", original, flags=re.I):
                continue
            if _contains_any(translated, bad_terms):
                issues.append(
                    _issue(
                        index,
                        item,
                        field,
                        "translation_proper_noun_mismatch",
                        FAIL,
                        {"proper_noun": original_term, "bad_terms": list(bad_terms), "translated_prefix": translated[:160]},
                        "Translation appears to replace an original proper noun with an unrelated place/name.",
                    )
                )
    return issues


def _title_proposition_issues(index, item):
    original = item.get("title_original") or item.get("title") or ""
    translated = item.get("title_cn") or ""
    if not original or not translated:
        return []
    issues = []
    for anchor_id, original_patterns, translated_signals in SUBSTANTIVE_TITLE_ANCHORS:
        if _contains_english(original, original_patterns) and not _contains_any(translated, translated_signals):
            issues.append(
                _issue(
                    index,
                    item,
                    "title",
                    "translation_title_proposition_missing",
                    FAIL,
                    {"anchor": anchor_id, "translated_prefix": translated[:160]},
                    "Translated title appears to omit a main action/content proposition from the original title.",
                )
            )
            break
    return issues


def _consultation_on_proposed_modifier_is_preserved(original, translated):
    if not re.search(
        r"\bconsultation\s+(?:paper|document)\b.{0,80}\b(?:on|about)\b.{0,80}\bproposed\b.{0,80}\bamendments?\b",
        original or "",
        flags=re.I | re.S,
    ):
        return False
    return _contains_any(translated, ("咨询",)) and _contains_any(translated, ("修正案", "修订", "修订案", "修法"))


def _descriptive_trend_family(original, action_id):
    for family, patterns, _signals in TREND_PROPOSITION_RULES:
        if family != action_id or not _contains_english(original, patterns):
            continue
        if _contains_english(original, AGENTIVE_TREND_CONTEXT):
            return False
        return _contains_english(original, DESCRIPTIVE_TREND_CONTEXT)
    return False


def _trend_proposition_issues(index, item):
    original = item.get("summary_original") or item.get("summary") or ""
    translated = item.get("summary_cn") or ""
    if not original or not translated:
        return []
    issues = []
    for family, patterns, translated_signals in TREND_PROPOSITION_RULES:
        if _contains_english(original, patterns) and not _contains_any(translated, translated_signals):
            issues.append(
                _issue(
                    index,
                    item,
                    "summary",
                    "translation_trend_proposition_missing",
                    WARNING,
                    {"trend": family, "translated_prefix": translated[:160]},
                    "Translated summary appears to omit a descriptive statistical trend from the original.",
                )
            )
    return issues


def _action_direction_issues(index, item):
    issues = []
    for field, original, translated in _translated_fields(item):
        if not original or not translated:
            continue
        for action_id, original_patterns, translated_signals in ACTION_DIRECTION_RULES:
            if action_id == "ban" and _contains_english(
                original,
                (r"\brescind(?:s|ed|ing)?\b", r"\brescission\b", r"\brepeal(?:s|ed|ing)?\b", r"\brevok(?:e|es|ed|ing)\b", r"\brevocation\b"),
            ):
                continue
            if not _contains_english(original, original_patterns):
                continue
            if action_id in {"increase", "decrease"} and _descriptive_trend_family(original, action_id):
                continue
            if action_id == "propose" and _consultation_on_proposed_modifier_is_preserved(original, translated):
                continue
            if not _contains_any(translated, translated_signals):
                severity = FAIL if action_id in {"rescind", "ban", "allow"} else WARNING
                issues.append(
                    _issue(
                        index,
                        item,
                        field,
                        "translation_action_direction_missing",
                        severity,
                        {"action": action_id, "translated_prefix": translated[:160]},
                        "Translation is missing the original policy/legal action direction.",
                    )
                )
            elif action_id == "rescind" and "禁止" in translated and not _contains_any(translated, translated_signals):
                issues.append(
                    _issue(
                        index,
                        item,
                        field,
                        "translation_action_direction_missing",
                        FAIL,
                        {"action": action_id, "translated_prefix": translated[:160]},
                        "Translation may reverse the policy direction by retaining prohibition language without rescission signals.",
                    )
                )
    return issues


def _relationship_issues(index, item):
    issues = []
    for field, original, translated in _translated_fields(item):
        if field != "summary" or not original or not translated:
            continue
        if re.search(
            r"\bISS\b.{0,240}\bsubmitted\s+a\s+brief\b.{0,320}\bchalleng(?:e|es|ed|ing)\b.{0,320}(?:\bSEC\b|\bSecurities\s*&\s*Exchange\s+Commission\b)",
            original,
            flags=re.I | re.S,
        ):
            iss_index = translated.find("ISS")
            sec_index = translated.find("SEC")
            submit_indices = [translated.find(term) for term in ("提交", "递交") if term in translated]
            challenge_present = _contains_any(translated, ("挑战", "质疑", "反对", "抗辩"))
            relationship_preserved = (
                iss_index >= 0
                and sec_index >= 0
                and submit_indices
                and iss_index < min(submit_indices)
                and sec_index > min(submit_indices)
                and challenge_present
            )
            if not relationship_preserved:
                issues.append(
                    _issue(
                        index,
                        item,
                        field,
                        "translation_relationship_missing",
                        FAIL,
                        {"relationship": "ISS_challenges_SEC_demand", "translated_prefix": translated[:200]},
                        "Translation does not preserve ISS as the party submitting a brief challenging an SEC demand.",
                    )
                )
        if not re.search(r"\b(?:partner(?:s|ed|ing|ship)?|collaborat(?:e|es|ed|ing|ion))\b", original, flags=re.I):
            continue
        if _contains_any(translated, ("合作", "伙伴", "协作", "携手")):
            continue
        issues.append(
            _issue(
                index,
                item,
                field,
                "translation_relationship_missing",
                FAIL,
                {"relationship": "partnership", "translated_prefix": translated[:160]},
                "Translated summary omits a material partnership or collaboration relationship.",
            )
        )
    return issues


def _corruption_issues(index, item):
    issues = []
    for field, original, translated in _translated_fields(item):
        if not original or not translated:
            continue
        for match in re.finditer(r"(?<!\d)(20\d{2})\s*(?:[-/.]|年)\s*(\d{1,2})\s*(?:[-/.]|月)\s*(\d{1,2})(?:日)?(?!\d)", translated):
            year, month, day = (int(value) for value in match.groups())
            try:
                date(year, month, day)
            except ValueError:
                issues.append(
                    _issue(
                        index,
                        item,
                        field,
                        "translation_date_corruption",
                        FAIL,
                        {"invalid_date": match.group(0), "translated_prefix": translated[:160]},
                        "Translation contains an impossible calendar date.",
                    )
                )
                break
    return issues


COMPRESSION_CONNECTORS = (
    r"\s+—\s+",
    r"\s+-\s+",
    r";\s+",
    r"\band what\b",
    r"\bwith (?:a |an |the )?",
)

COMPRESSION_ANCHORS = [
    (r"\brisk[- ]based\b|\brisk\b", ("风险",)),
    (r"\bintraday\b", ("日内",)),
    (r"\bmargin\b", ("保证金",)),
    (r"\bstandard\b", ("标准",)),
    (r"\binvestors?\b", ("投资者",)),
    (r"\bmember firms?\b", ("成员公司", "会员公司", "成员", "会员")),
    (r"\breplac(?:e|es|ed|ing)\b", ("取代", "替换", "更换")),
    (r"\bmeans?\b|\bimplications?\b", ("意味", "影响", "含义")),
]


def _late_segments(original):
    parts = [original or ""]
    for connector in COMPRESSION_CONNECTORS:
        next_parts = []
        for part in parts:
            next_parts.extend(re.split(connector, part, flags=re.I))
        parts = next_parts
    return [part.strip(" .,—-") for part in parts[1:] if len(part.strip(" .,—-")) >= 24]


def _segment_anchor_count(segment, translated):
    expected = []
    found = 0
    for original_pattern, translated_terms in COMPRESSION_ANCHORS:
        if re.search(original_pattern, segment or "", flags=re.I):
            expected.append(list(translated_terms))
            if _contains_any(translated, translated_terms):
                found += 1
    return len(expected), found, expected


def _suspicious_compression_issues(index, item):
    issues = []
    for field, original, translated in _translated_fields(item):
        if field != "summary" or not original or not translated or len(original) < 140:
            continue
        for segment in _late_segments(original):
            expected_count, found_count, expected_terms = _segment_anchor_count(segment, translated)
            if expected_count >= 3 and found_count <= 1:
                issues.append(
                    _issue(
                        index,
                        item,
                        field,
                        "translation_suspicious_compression",
                        FAIL,
                        {
                            "omitted_segment_prefix": segment[:160],
                            "expected_signal_groups": expected_terms,
                            "matched_signal_groups": found_count,
                            "translated_prefix": translated[:160],
                        },
                        "Translated summary appears to preserve an early clause while omitting a later substantive clause.",
                    )
                )
                break
    return issues


def audit_translation_quality(items, translation_mode=""):
    normalizer = TerminologyNormalizer()
    issues = []
    for index, item in enumerate(items or []):
        issues.extend(_bilingual_completeness_issues(index, item, translation_mode))
        issues.extend(_sanity_quality_issues(index, item))
        issues.extend(_entity_issues(index, item, normalizer))
        issues.extend(_material_term_issues(index, item))
        issues.extend(_proper_noun_issues(index, item))
        issues.extend(_title_proposition_issues(index, item))
        issues.extend(_trend_proposition_issues(index, item))
        issues.extend(_action_direction_issues(index, item))
        issues.extend(_relationship_issues(index, item))
        issues.extend(_suspicious_compression_issues(index, item))
        issues.extend(_corruption_issues(index, item))
        fallback_warning = safe_fallback_warning(item, index)
        if fallback_warning:
            issues.append(fallback_warning)
    return issues


def validate_translation_field(
    original,
    translated,
    field_type="text",
    source="",
    title_original="",
    include_sanity=True,
):
    item = {
        "source": source or "",
        "title_original": title_original or (original if field_type == "title" else ""),
        "summary_original": original if field_type == "summary" else "",
        "title_cn": translated if field_type == "title" else "",
        "summary_cn": translated if field_type == "summary" else "",
    }
    if field_type == "title":
        return (
            (_standalone_sanity_quality_issues(0, item) if include_sanity else [])
            + _entity_issues(0, item, TerminologyNormalizer())
            + _proper_noun_issues(0, item)
            + _title_proposition_issues(0, item)
            + _trend_proposition_issues(0, item)
            + _action_direction_issues(0, item)
            + _relationship_issues(0, item)
            + _corruption_issues(0, item)
        )
    if field_type == "summary":
        return (
            (_standalone_sanity_quality_issues(0, item) if include_sanity else [])
            + _entity_issues(0, item, TerminologyNormalizer())
            + _proper_noun_issues(0, item)
            + _trend_proposition_issues(0, item)
            + _action_direction_issues(0, item)
            + _relationship_issues(0, item)
            + _suspicious_compression_issues(0, item)
            + _corruption_issues(0, item)
        )
    return []


def _summary_has_high_risk_action_failure(item):
    issues = validate_translation_field(
        original=item.get("summary_original") or item.get("summary") or "",
        translated=item.get("summary_cn") or "",
        field_type="summary",
        source=item.get("source") or "",
        title_original=item.get("title_original") or item.get("title") or "",
        include_sanity=False,
    )
    for issue in issues:
        if (
            issue.get("severity") == FAIL
            and issue.get("issue_id") == "translation_action_direction_missing"
            and issue.get("evidence", {}).get("action") in CRITICAL_ACTION_FALLBACK_FAMILIES
        ):
            return issue.get("evidence", {}).get("action")
    return ""


def _title_provides_safe_action_fallback(item, family):
    if family not in CRITICAL_ACTION_FALLBACK_FAMILIES:
        return False
    title_original = item.get("title_original") or item.get("title") or ""
    title_cn = item.get("title_cn") or ""
    if not title_original or not title_cn:
        return False
    if _critical_action_family(title_original) != family:
        return False
    if not _contains_any(title_cn, CRITICAL_ACTION_FALLBACK_FAMILIES[family]["signals"]):
        return False
    title_issues = validate_translation_field(
        original=title_original,
        translated=title_cn,
        field_type="title",
        source=item.get("source") or "",
        title_original=title_original,
        include_sanity=False,
    )
    return not any(issue.get("severity") == FAIL for issue in title_issues)


def safe_fallback_warning(item, index=0):
    family = _critical_action_family(item.get("summary_original") or item.get("summary") or "")
    if not family:
        return None
    if (item.get("summary_cn") or "").strip() != (item.get("title_cn") or "").strip():
        return None
    if not _title_provides_safe_action_fallback(item, family):
        return None
    return _issue(
        index,
        item,
        "summary",
        "translation_safe_fallback_used",
        WARNING,
        {
            "action_family": family,
            "title_original": item.get("title_original") or item.get("title") or "",
            "reason": "validated title used because summary remained semantically unsafe",
        },
        "A validated title was used as a safe fallback for a semantically unsafe translated summary.",
    )


def apply_critical_action_safe_fallback(item):
    clean = dict(item)
    family = _summary_has_high_risk_action_failure(clean)
    if not family:
        return clean, None
    if not _title_provides_safe_action_fallback(clean, family):
        return clean, None
    clean["summary_cn"] = clean.get("title_cn") or ""
    return clean, safe_fallback_warning(clean, 0)
