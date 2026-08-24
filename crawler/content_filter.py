import re


POSITIVE_TERMS = {
    "macro": [
        "monetary policy", "interest rate", "interest rates", "inflation",
        "central bank", "financial stability", "banking supervision",
        "banking regulation", "capital market", "capital markets",
        "securities", "derivatives", "clearing", "settlement", "custody",
        "market infrastructure", "foreign exchange", "fx", "cross-border",
        "sanction", "legislation", "payment", "digital euro", "digital finance",
        "crypto", "sustainable finance", "esg", "macroprudential",
        "supervision", "enforcement", "fraud", "investor", "market abuse",
        "market stability", "prediction market", "prediction markets",
        "self-certification", "emergency authority",
    ],
    "dbg": [
        "product", "launch", "volume", "clearing", "trading", "market share",
        "partnership", "acquisition", "strategy", "financial result",
        "infrastructure", "client", "cooperation", "expansion", "index",
        "derivatives", "settlement", "custody", "collateral", "repo",
    ],
    "competitor": [
        "product", "launch", "volume", "clearing", "trading", "market share",
        "acquisition", "partnership", "pricing", "approval", "expansion",
        "technology", "strategy", "derivatives", "settlement", "custody",
    ],
}


HIGH_IMPORTANCE_TERMS = [
    "monetary policy", "interest rate", "inflation", "financial stability",
    "regulation", "supervision", "clearing", "settlement",
    "market infrastructure", "derivatives", "payment", "crypto", "sanction",
    "trading volume", "market share", "acquisition", "partnership",
]


HIGH_VALUE_MACRO_TERMS = [
    "fomc statement",
    "fomc minutes",
    "federal open market committee",
    "monetary policy decision",
    "notice of proposed rulemaking",
    "proposed rulemaking",
    "proposed rule",
    "nprm",
    "requests comment on proposal",
    "seeks public comment",
    "public consultation",
    "joint statement",
    "financial regulatory working group",
    "capital markets reform",
    "listing act",
    "market access",
    "cross-border investment",
    "renminbi sovereign bonds",
    "sovereign bonds through central moneymarkets unit",
    "clearing regulation",
    "settlement regulation",
    "derivatives regulation",
    "financial stability policy",
]


HIGH_VALUE_BUSINESS_TERMS = [
    "quarterly results",
    "annual results",
    "financial results",
    "earnings",
    "q1 fy",
    "q2 2026 results",
    "trading volumes",
    "trading volume",
    "clearing volumes",
    "clearing volume",
    "new product",
    "data product",
    "ownership datasets",
    "market data launch",
    "launches",
    "strategic partnership",
    "acquisition",
    "market-access expansion",
    "regulatory approval",
    "insurance funds",
    "invest in hong kong etfs",
]


INDIVIDUAL_ENFORCEMENT_TERMS = [
    "charges", "charged", "fraud", "penalty", "penalties", "settles charges",
    "individual", "scheme", "boiler room", "defrauding", "misconduct",
    "enforcement action", "fines", "fine", "bans", "ban", "former ceo",
    "former svs securities ceo",
]


MARKET_WIDE_TERMS = [
    "rule", "rules", "rulemaking", "advisory", "guidance", "market-wide",
    "self-certification", "market stability", "systemic", "framework",
    "regulation", "supervision", "policy", "proposal", "consultation",
]


NEGATIVE_TERMS = [
    "concert", "orchestra", "cultural", "culture", "art", "charity",
    "recruitment", "career", "employee", "holiday", "maintenance",
    "webinar invitation", "event invitation", "invite the public",
    "open air", "award", "sponsorship", "appoints", "appointment",
    "appointed", "elects", "elected", "management board", "board member",
    "investor warning", "investor warnings", "scam warning", "scam alert",
    "fraudsters impersonate", "agenda", "conference", "speaker", "meeting",
]


NON_FINANCIAL_POLICY_TERMS = [
    "narcotics", "cartel", "cartels", "cocaine", "violent gangs",
    "illegal aliens", "refundable tax credits", "tax credits from abuse",
]


FALSE_CANDIDATE_TITLES = {
    "media",
    "news",
    "newsroom",
    "market news",
    "press releases",
    "publications",
    "events",
    "statistics",
    "all",
}


REJECTION_CATEGORY_TERMS = {
    "routine enforcement": [
        "charges", "charged", "fraud", "penalty", "penalties", "settles charges",
        "investor warning", "investor warnings", "scam warning", "scam alert",
        "warning and alert", "warnings and alerts", "misconduct",
    ],
    "personnel": [
        "appoints", "appointment", "appointed", "elects", "elected",
        "management board", "board member", "chair appointed",
    ],
    "conference/event": [
        "agenda", "conference", "webinar", "speaker", "speaks", "event",
        "invitation", "meeting", "forum",
    ],
    "generic marketing": [
        "award", "sponsorship", "culture", "concert", "charity", "career",
        "recruitment", "holiday", "promotion", "campaign",
    ],
}


def normalize_text(*values):
    text = " ".join(value or "" for value in values).lower()
    return re.sub(r"\s+", " ", text)


def contains_term(text, term):
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def score_item(item):
    category = (item.get("category") or "").lower()
    bucket = "macro"
    if category == "dbg":
        bucket = "dbg"
    elif category == "competitor":
        bucket = "competitor"

    text = normalize_text(
        item.get("title_original"),
        item.get("title_cn"),
        item.get("title_en"),
        item.get("summary"),
        item.get("source"),
        item.get("subcategory"),
        item.get("brand"),
    )

    score = 0
    reasons = []

    for term in POSITIVE_TERMS[bucket]:
        if term in text:
            score += 2
            reasons.append(term)

    for term in HIGH_IMPORTANCE_TERMS:
        if term in text:
            score += 2
            reasons.append(f"important:{term}")

    for term in HIGH_VALUE_MACRO_TERMS:
        if term in text:
            score += 6
            reasons.append(f"hard_signal:{term}")

    if bucket in ("dbg", "competitor"):
        for term in HIGH_VALUE_BUSINESS_TERMS:
            if term in text:
                score += 6
                reasons.append(f"hard_signal:{term}")
    elif any(term in text for term in HIGH_VALUE_BUSINESS_TERMS):
        score += 4
        reasons.append("hard_signal:business_development")

    for term in NEGATIVE_TERMS:
        if contains_term(text, term):
            score -= 5
            reasons.append(f"downrank:{term}")

    individual_enforcement = any(term in text for term in INDIVIDUAL_ENFORCEMENT_TERMS)
    market_wide = any(term in text for term in MARKET_WIDE_TERMS)
    if individual_enforcement and not market_wide:
        score -= 6
        reasons.append("downrank:individual_enforcement")

    if any(term in text for term in NON_FINANCIAL_POLICY_TERMS):
        score -= 8
        reasons.append("downrank:non_financial_policy")

    personnel_change = any(
        term in text
        for term in ("appoints", "appointment", "appointed", "elects", "elected", "management board", "board member")
    )
    top_leadership = any(term in text for term in ("chair", "chairman", "president", "chief executive", "ceo"))
    if personnel_change and not top_leadership:
        score -= 6
        reasons.append("downrank:routine_personnel")

    if item.get("official"):
        score += 1
        reasons.append("official")

    if int(item.get("priority") or 99) == 1:
        score += 1
        reasons.append("priority=1")

    score = max(0, score)
    reason = ", ".join(reasons[:8]) if reasons else "no strong finance signal"
    return score, reason


def split_relevance_signals(reason):
    signals = [part.strip() for part in (reason or "").split(",") if part.strip()]
    positive = []
    negative = []
    for signal in signals:
        if signal.startswith("downrank:"):
            negative.append(signal.removeprefix("downrank:"))
        elif signal not in ("no strong finance signal", "official", "priority=1"):
            positive.append(signal.removeprefix("important:"))
    return positive, negative


def rejection_category(item):
    title = normalize_text(item.get("title_original"), item.get("title"))
    text = normalize_text(
        item.get("title_original"),
        item.get("title_cn"),
        item.get("title_en"),
        item.get("summary"),
        item.get("source"),
        item.get("subcategory"),
        item.get("brand"),
        item.get("relevance_reason"),
    )

    if title in FALSE_CANDIDATE_TITLES or title.startswith("page "):
        return "false candidate"

    for category, terms in REJECTION_CATEGORY_TERMS.items():
        if any(term in text for term in terms):
            return category

    positive, _ = split_relevance_signals(item.get("relevance_reason", ""))
    if not positive or int(item.get("relevance_score") or 0) <= 2:
        return "low business relevance"

    return "other"


def audit_rejection(item):
    positive, negative = split_relevance_signals(item.get("relevance_reason", ""))
    return {
        "positive_signals": positive,
        "negative_signals": negative,
        "rejection_category": rejection_category(item),
    }


def apply_relevance(items, min_score=3):
    kept = []
    reviewed = []
    for item in items:
        clean = dict(item)
        score, reason = score_item(clean)
        clean["relevance_score"] = score
        clean["relevance_reason"] = reason
        reviewed.append(clean)
        if score >= min_score:
            kept.append(clean)
    return kept, reviewed
