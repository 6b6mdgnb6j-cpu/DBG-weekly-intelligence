import re

from crawler.translator import TerminologyNormalizer


FAIL = "FAIL"
WARNING = "WARNING"


PROPER_NOUN_RULES = [
    ("Singapore", ("新加坡",), ("新加拿大",)),
    ("Indonesia", ("印度尼西亚", "印尼"), ("新加拿大",)),
    ("United States", ("美国",), ("美国国",)),
    ("U.S.", ("美国",), ("美国国",)),
    ("Switzerland", ("瑞士",), ("瑞士兰",)),
]

TITLE_ANCHORS = [
    ("inflow", (r"\binflows?\b", r"\boutflows?\b"), ("流入", "流出", "资金流")),
    ("launch", (r"\blaunch(?:es|ed|ing)?\b", r"\bintroduc(?:e|es|ed|ing)\b"), ("推出", "发布", "引入", "发起")),
    ("acquire", (r"\bacquir(?:e|es|ed|ing)\b", r"\bacquisition\b"), ("收购", "并购")),
    ("propose", (r"\bpropos(?:e|es|ed|al)\b",), ("提议", "拟", "建议", "提出")),
    ("rescind", (r"\brescind(?:s|ed|ing)?\b", r"\brescission\b", r"\brepeal(?:s|ed|ing)?\b", r"\brevok(?:e|es|ed|ing)\b"), ("取消", "撤销", "废除", "撤回")),
    ("approve", (r"\bapprov(?:e|es|ed|ing|al)\b",), ("批准", "核准")),
    ("suspend", (r"\bsuspend(?:s|ed|ing)?\b",), ("暂停", "中止")),
    ("extend", (r"\bextend(?:s|ed|ing)?\b",), ("延长", "延期", "扩大", "扩展")),
    ("increase", (r"\bincreas(?:e|es|ed|ing)\b", r"\brecord\b"), ("增加", "上升", "提高", "创纪录")),
    ("decrease", (r"\breduc(?:e|es|ed|ing)\b", r"\bdecreas(?:e|es|ed|ing)\b"), ("减少", "下降", "降低")),
    ("report", (r"\breport(?:s|ed|ing)?\b",), ("报告", "公布")),
    ("partner", (r"\bpartner(?:s|ed|ing|ship)?\b",), ("合作", "伙伴")),
    ("clear", (r"\bclear(?:s|ed|ing)?\b", r"\bclearing\b"), ("清算",)),
    ("settle", (r"\bsettle(?:s|d|ment)?\b", r"\bsettlement\b"), ("结算",)),
]

ACTION_DIRECTION_RULES = [
    ("rescind", (r"\brescind(?:s|ed|ing)?\b", r"\brescission\b", r"\brepeal(?:s|ed|ing)?\b", r"\brevok(?:e|es|ed|ing)\b"), ("取消", "撤销", "废除", "撤回")),
    ("propose", (r"\bpropos(?:e|es|ed|al)\b",), ("提议", "拟", "建议", "提出")),
    ("extend", (r"\bextend(?:s|ed|ing)?\b",), ("延长", "延期", "扩大", "扩展")),
    ("approve", (r"\bapprov(?:e|es|ed|ing|al)\b",), ("批准", "核准")),
    ("ban", (r"\bban(?:s|ned|ning)?\b", r"\bprohibit(?:s|ed|ing)?\b"), ("禁止",)),
    ("allow", (r"\ballow(?:s|ed|ing)?\b", r"\bpermit(?:s|ted|ting)?\b"), ("允许",)),
    ("increase", (r"\bincreas(?:e|es|ed|ing)\b",), ("增加", "上升", "提高")),
    ("decrease", (r"\bdecreas(?:e|es|ed|ing)\b", r"\breduc(?:e|es|ed|ing)\b"), ("减少", "下降", "降低")),
]

DANGEROUS_ENTITY_VARIANTS = {
    "ISS STOXX": ("国际空间站STOXX", "国际航天站STOXX", "国际航天局公司", "国际航天局", "国际空间站", "国际航天站"),
    "STOXX": ("STTOXX", "STOX", "斯托克斯"),
    "ICE": ("冰岛", "欧元交易所", "国际大陆交易所", "跨大陆交易"),
    "SIX": ("六个交易所",),
    "FTSE": ("FTC",),
    "FINRA": ("国际金融基金会", "FINA"),
    "FSC": ("联邦书商管理局", "国际SEC", "国际证券交易委员会"),
    "CFTC": ("欧盟货币交易委员会", "欧盟CFTC", "欧盟贸易交易委员会", "美国央行", "金融交易委员会"),
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
}


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


def _translated_fields(item):
    return [
        ("title", item.get("title_original") or item.get("title") or "", item.get("title_cn") or ""),
        ("summary", item.get("summary_original") or item.get("summary") or "", item.get("summary_cn") or ""),
    ]


def _entity_issues(index, item, normalizer):
    issues = []
    for field, original, translated in _translated_fields(item):
        if not original or not translated:
            continue
        for canonical, spec in normalizer.CANONICAL_ENTITIES.items():
            if not normalizer._original_has_entity_evidence(original, canonical, spec.get("aliases", [])):
                continue
            dangerous_variants = DANGEROUS_ENTITY_VARIANTS.get(canonical, ())
            has_dangerous_variant = any(_contains_bad_variant(translated, bad) for bad in dangerous_variants)
            acceptable_renderings = ACCEPTABLE_ENTITY_RENDERINGS.get(canonical, (canonical,))
            has_acceptable_rendering = _contains_any(translated, acceptable_renderings)
            original_has_canonical = normalizer._contains_entity(original, canonical)
            if original_has_canonical and not normalizer._contains_entity(translated, canonical) and not has_acceptable_rendering:
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
    for anchor_id, original_patterns, translated_signals in TITLE_ANCHORS:
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


def _action_direction_issues(index, item):
    issues = []
    for field, original, translated in _translated_fields(item):
        if not original or not translated:
            continue
        for action_id, original_patterns, translated_signals in ACTION_DIRECTION_RULES:
            if action_id == "ban" and _contains_english(
                original,
                (r"\brescind(?:s|ed|ing)?\b", r"\brescission\b", r"\brepeal(?:s|ed|ing)?\b", r"\brevok(?:e|es|ed|ing)\b"),
            ):
                continue
            if not _contains_english(original, original_patterns):
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


def audit_translation_quality(items):
    normalizer = TerminologyNormalizer()
    issues = []
    for index, item in enumerate(items or []):
        issues.extend(_entity_issues(index, item, normalizer))
        issues.extend(_proper_noun_issues(index, item))
        issues.extend(_title_proposition_issues(index, item))
        issues.extend(_action_direction_issues(index, item))
    return issues
