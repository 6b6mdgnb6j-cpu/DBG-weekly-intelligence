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
    ("approve", (r"\bapprov(?:e|es|ed|ing|al)\b",), ("批准", "核准")),
    ("suspend", (r"\bsuspend(?:s|ed|ing)?\b",), ("暂停", "中止")),
    ("extend", (r"\bextend(?:s|ed|ing)?\b",), ("延长", "延期", "扩大", "扩展")),
    ("increase", (r"\bincreas(?:e|es|ed|ing)\b", r"\brecord\b"), ("增加", "上升", "提高", "创纪录")),
    ("decrease", (r"\breduc(?:e|es|ed|ing)\b", r"\bdecreas(?:e|es|ed|ing)\b"), ("减少", "下降", "降低")),
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


def audit_translation_quality(items):
    normalizer = TerminologyNormalizer()
    issues = []
    for index, item in enumerate(items or []):
        issues.extend(_entity_issues(index, item, normalizer))
        issues.extend(_proper_noun_issues(index, item))
        issues.extend(_title_proposition_issues(index, item))
        issues.extend(_action_direction_issues(index, item))
        issues.extend(_suspicious_compression_issues(index, item))
        fallback_warning = safe_fallback_warning(item, index)
        if fallback_warning:
            issues.append(fallback_warning)
    return issues


def validate_translation_field(original, translated, field_type="text", source="", title_original=""):
    item = {
        "source": source or "",
        "title_original": title_original or (original if field_type == "title" else ""),
        "summary_original": original if field_type == "summary" else "",
        "title_cn": translated if field_type == "title" else "",
        "summary_cn": translated if field_type == "summary" else "",
    }
    if field_type == "title":
        return (
            _entity_issues(0, item, TerminologyNormalizer())
            + _proper_noun_issues(0, item)
            + _title_proposition_issues(0, item)
            + _action_direction_issues(0, item)
        )
    if field_type == "summary":
        return (
            _entity_issues(0, item, TerminologyNormalizer())
            + _proper_noun_issues(0, item)
            + _action_direction_issues(0, item)
            + _suspicious_compression_issues(0, item)
        )
    return []


def _summary_has_high_risk_action_failure(item):
    issues = validate_translation_field(
        original=item.get("summary_original") or item.get("summary") or "",
        translated=item.get("summary_cn") or "",
        field_type="summary",
        source=item.get("source") or "",
        title_original=item.get("title_original") or item.get("title") or "",
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
