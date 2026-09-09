import re


# Constants / term lists

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
    "proposes to modernize rules",
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
    "intermediários estrangeiros",
    "mercados admitidos",
    "contratos futuros",
    "asset management hub",
    "proposes new regulation",
    "proposed regulation",
    "requests comment",
    "request for comment",
    "foreign-listed etf",
    "foreign-listed etfs",
    "merger value",
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
    "new futures",
    "new options",
    "new market",
    "new index",
    "index series",
    "data products",
    "freight data products",
    "product launch",
    "market expansion",
    "platform migration",
    "stablecoin partnership",
    "market data portfolio",
]


ACQUISITION_EVENT_TERMS = [
    "acquires",
    "acquired",
    "acquisition of",
    "to acquire",
    "completes acquisition",
    "completed acquisition",
    "announces acquisition",
    "agrees to acquire",
    "agreement to acquire",
    "purchase of",
    "sale of",
    "divestment",
    "divestiture",
    "disposal",
]


REGULATORY_SOURCES = [
    "德国联邦金融监管局",
    "商品期货交易委员会",
    "证券交易委员会",
    "联邦存款保险公司",
    "货币监理署",
    "联邦储备系统",
    "金融行为监管局",
    "欧洲中央银行",
    "欧洲保险和职业养老金管理局",
    "加拿大安大略省证券委员会",
    "加拿大金融机构监管署",
    "澳大利亚证券和投资委员会",
    "澳大利亚审慎监管局",
    "韩国金融监督委员会",
    "香港金融管理局",
]


MATERIAL_DEVELOPMENT_TERMS = [
    "launch", "launches", "introduction of", "new product", "new futures",
    "new options", "new market", "new data product", "data products",
    "new index", "index series", "expansion", "extended expiries",
    "harmonisation", "acquisition", "partnership", "strategic",
    "market access", "foreign market access", "regulatory approval",
    "financial results", "quarterly results", "annual results", "earnings",
    "clearing expansion", "settlement infrastructure", "technology migration",
    "stablecoin partnership", "public consultation", "proposed rulemaking",
    "notice of proposed rulemaking", "proposed regulation", "fomc statement",
    "fomc minutes", "monetary policy", "capital markets rules change",
]


ROUTINE_OPERATIONAL_OVERRIDE_TERMS = [
    "launch", "launches", "introduction of", "new product", "new futures",
    "new options", "new market", "new index", "index series", "expansion",
    "extended expiries", "harmonisation", "acquisition", "partnership",
    "strategic", "market access", "foreign market access",
    "regulatory approval", "financial results", "quarterly results",
    "annual results", "earnings", "clearing expansion",
    "settlement infrastructure", "major technology migration",
    "public consultation", "proposed rulemaking",
    "notice of proposed rulemaking", "proposed regulation",
    "fomc statement", "fomc minutes", "monetary policy",
    "capital markets rules change",
]


ROUTINE_OPERATIONAL_TERMS = [
    "final settlement price",
    "final settlement prices",
    "routine settlement notice",
    "missing trades",
    "missing price",
    "missing index",
    "data alert",
    "submission window closes",
    "mandatory reporting reminder",
    "mandatory reporting",
    "annual usage reporting",
    "usage reporting",
    "action required reminder",
    "service interruption",
    "routine customer notice",
    "routine migration reminder",
    "migration mandatory",
    "sftp discontinuation",
    "no eod data",
]


RECURRING_COMMENTARY_TERMS = [
    "ta tuesday",
    "market deep dive",
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
    "podcast", "podcasts", "hall of fame", "nomination", "nominations",
]


NON_FINANCIAL_POLICY_TERMS = [
    "narcotics", "cartel", "cartels", "cocaine", "violent gangs",
    "terrorist networks", "terrorist network", "terrorist", "violent far-left",
    "illegal aliens", "refundable tax credits", "tax credits from abuse",
    "venezuela's economic recovery", "venezuela’s economic recovery",
    "earthquake relief",
]


NON_FINANCIAL_POLICY_CONTEXT_TERMS = [
    "education", "school", "schools", "racial discrimination",
    "discriminatory practices", "tax-exempt status", "tax exempt status",
    "nonprofit", "non-profit", "charity", "charitable organization",
    "charitable organizations", "social policy", "individual taxpayer",
    "individual taxpayers",
]


FINANCIAL_POLICY_CONTEXT_TERMS = [
    "securities", "capital market", "capital markets", "stock market",
    "stock markets", "equity market", "equity markets", "bond", "bonds",
    "municipal bond", "municipal bonds", "municipal securities",
    "tax-exempt bond", "tax-exempt bonds", "tax exempt bond",
    "tax exempt bonds", "treasury securities", "debt market",
    "debt markets", "financial institution", "financial institutions",
    "bank", "banks", "banking", "derivatives", "swap", "swaps",
    "futures", "clearing", "ccp", "settlement", "custody",
    "collateral", "payment", "payments", "financial stability",
    "systemic risk", "market structure", "broker", "dealer",
    "broker-dealer", "investment fund", "investment funds",
    "asset management", "exchange", "exchanges", "cross-border finance",
]


FINANCIAL_MARKET_SETTLEMENT_CONTEXT_TERMS = [
    "securities settlement",
    "trade settlement",
    "clearance and settlement",
    "national clearance and settlement",
    "clearing and settlement",
    "post-trade",
    "post trade",
    "csd",
    "central securities depository",
    "t+1",
    "t+2",
    "delivery-versus-payment",
    "delivery versus payment",
    "payment-system settlement",
    "payment system settlement",
    "collateral settlement",
    "digital-asset settlement",
    "digital asset settlement",
    "institutional digital-asset settlement",
    "institutional digital asset settlement",
    "transaction settlement",
    "local-currency transaction settlement",
    "local currency transaction settlement",
    "settlement infrastructure",
]


NON_FINANCIAL_SETTLEMENT_CONTEXT_TERMS = [
    "insurance claim",
    "insurance claims",
    "home-insurance",
    "home insurance",
    "homeowners",
    "cash settlements",
    "claim settlement",
    "claims settlement",
    "legal settlement",
    "employment settlement",
    "consumer compensation settlement",
]


FINANCIAL_MARKET_OBJECT_TERMS = [
    "exchange", "exchanges", "trading", "clearing", "settlement",
    "securities", "derivatives", "asset management", "banking",
    "payment", "payments", "collateral", "benchmark", "index",
    "indices", "market data", "financial infrastructure", "fund",
    "funds", "capital market", "capital markets", "market structure",
    "bank", "banks", "broker", "dealer", "swap", "swaps", "futures",
    "options", "etf", "etfs", "bond", "bonds", "repo", "custody",
]


GENERIC_ACTION_TERMS = [
    "consultation", "public consultation", "proposed rule",
    "proposed regulation", "proposed regulations", "final rule",
    "interim final rule", "sanctions", "enforcement", "announcement",
    "partnership",
]


STANDALONE_STRONG_CONTEXT_TERMS = [
    "monetary policy", "financial stability", "fomc", "federal open market committee",
    "systemic risk", "inflation", "interest rate", "interest rates",
]


LOW_VALUE_EVENT_TERMS = [
    "save the date", "call for nominations", "hall of fame nominations",
    "award nomination", "awards nomination", "conference participation",
    "conference agenda", "webinar", "podcast", "podcasts", "diversity speech",
    "diversity at the european central bank",
]


ROUTINE_ENFORCEMENT_TERMINATION_TERMS = [
    "termination of enforcement action",
    "termination of enforcement actions",
    "terminates enforcement action",
    "terminates enforcement actions",
    "terminated enforcement action",
    "terminated enforcement actions",
]


CONSUMER_SCAM_ALERT_TERMS = [
    "phishing scam",
    "phishing scams",
    "scam alert",
    "scam alerts",
    "fraudulent website",
    "fraudulent document",
    "impersonating",
    "consumer alert",
    "stay alert",
]


CONSUMER_SCAM_CONTEXT_TERMS = [
    "payment card",
    "payment cards",
    "contactless mobile payments",
    "mobile payments",
    "card binding",
    "binding of payment cards",
    "retail customer",
    "retail customers",
    "public to stay alert",
]


SCAM_MATERIAL_OVERRIDE_TERMS = [
    "systemic",
    "systemic payment infrastructure",
    "payment infrastructure disruption",
    "banking-system impact",
    "banking system impact",
    "new regulation",
    "market-infrastructure change",
    "market infrastructure change",
    "large-scale operational incident",
    "large scale operational incident",
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


# Lexical matching helpers

def normalize_text(*values):
    text = " ".join(value or "" for value in values).lower()
    return re.sub(r"\s+", " ", text)


def contains_term(text, term):
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def contains_any_phrase(text, terms):
    return any(term in text for term in terms)


def contains_all_phrases(text, terms):
    return all(term in text for term in terms)


def contains_individual_enforcement_term(text, term):
    if term == "fine":
        return re.search(r"(?<![\w-])fine(?![\w-])", text) is not None
    if term == "fines":
        return re.search(r"(?<![\w-])fines(?![\w-])", text) is not None
    if term == "fraud":
        return contains_fraud_family(text)
    return contains_term(text, term)


def contains_fraud_family(text):
    return re.search(r"(?<!\w)fraud(?:s|ulent|sters?)?(?!\w)", text) is not None


def is_fraud_prevention_technology_context(text):
    if not contains_fraud_family(text):
        return False
    enforcement_context = (
        "alert",
        "warning",
        "warns",
        "warned",
        "scam",
        "fraudulent website",
        "fraudulent document",
        "fraudsters impersonat",
        "charged with fraud",
        "securities fraud",
        "enforcement",
        "false filings",
        "lure retail investors",
    )
    if any(term in text for term in enforcement_context):
        return False
    prevention_context = (
        "fraud prevention",
        "fraud detection",
        "anti-fraud technology",
        "technology platform",
        "software",
        "product launch",
        "partnership",
        "cyber",
        "unique intelligence",
        "proactive fraud prevention",
    )
    return any(term in text for term in prevention_context)


def is_individual_enforcement(text):
    matched = any(
        contains_individual_enforcement_term(text, term)
        for term in INDIVIDUAL_ENFORCEMENT_TERMS
    )
    if matched and is_fraud_prevention_technology_context(text):
        matched = any(
            contains_individual_enforcement_term(text, term)
            for term in INDIVIDUAL_ENFORCEMENT_TERMS
            if term != "fraud"
        )
    return matched


# Text builders

def build_relevance_text(item):
    return normalize_text(
        item.get("title_original"),
        item.get("title_cn"),
        item.get("title_en"),
        item.get("summary"),
        item.get("relevance_context"),
        item.get("source"),
        item.get("subcategory"),
        item.get("brand"),
    )


# Global signal helpers

def has_material_development_signal(text):
    return contains_any_phrase(text, MATERIAL_DEVELOPMENT_TERMS)


def has_acquisition_event_signal(text):
    return contains_any_phrase(text, ACQUISITION_EVENT_TERMS)


def has_high_value_business_signal(text):
    for term in HIGH_VALUE_BUSINESS_TERMS:
        if term == "acquisition":
            if has_acquisition_event_signal(text):
                return True
            continue
        if term in text:
            return True
    return False


def has_routine_operational_signal(text):
    return contains_any_phrase(text, ROUTINE_OPERATIONAL_TERMS)


def routine_operational_is_overridden(text):
    return contains_any_phrase(text, ROUTINE_OPERATIONAL_OVERRIDE_TERMS)


def is_recurring_market_commentary(item, text):
    source = (item.get("source") or "").lower()
    brand = (item.get("brand") or "").lower()
    if "crypto finance" not in source and "crypto finance" not in brand:
        return False
    return contains_any_phrase(text, RECURRING_COMMENTARY_TERMS)


# Source-specific signal helpers

def is_ice_commodity_market_signal(item, text):
    source = (item.get("source") or "").lower()
    original = normalize_text(item.get("title_original"), item.get("summary_original"), item.get("summary"))
    if "洲际交易所" not in source and "intercontinental exchange" not in original and " ice " not in f" {original} ":
        return False
    commodity_terms = ("sugar", "commodity", "commodities", "energy", "power", "gas", "oil")
    market_terms = ("open interest", "hedging", "futures", "options", "liquidity", "volume")
    return contains_any_phrase(text, commodity_terms) and contains_any_phrase(text, market_terms)


def is_bafin_ai_market_surveillance_signal(item, text):
    source = (item.get("source") or "").lower()
    if "德国联邦金融监管局" not in source and "bafin" not in text:
        return False
    has_surveillance = "market surveillance" in text
    has_ai = contains_term(text, "ai") or "artificial intelligence" in text
    has_powers = contains_any_phrase(text, ("new powers", "granted new powers", "supervisory powers"))
    return has_surveillance and has_ai and has_powers


def is_clearstream_dlt_settlement_signal(item, text):
    source = (item.get("source") or "").lower()
    original = normalize_text(item.get("title_original"), item.get("summary_original"), item.get("summary"))
    if "明讯银行" not in source and "clearstream" not in original:
        return False
    has_central_bank = "ecb" in text or "central bank" in text
    has_dlt = contains_any_phrase(text, ("dlt", "distributed ledger", "tokenised settlement", "tokenized settlement"))
    has_infra = contains_any_phrase(text, ("settlement", "infrastructure", "solution", "launch", "test"))
    return has_central_bank and has_dlt and has_infra


def is_clearstream_monthly_figures_signal(item, text):
    source = (item.get("source") or "").lower()
    brand = (item.get("brand") or "").lower()
    original = normalize_text(item.get("title_original"), item.get("summary_original"), item.get("summary"))
    if "明讯银行" not in source and "clearstream" not in brand and "clearstream" not in original:
        return False
    return "clearstream" in text and "figures" in text


def is_lch_ois_clearing_signal(item, text):
    source = (item.get("source") or "").lower()
    original = normalize_text(item.get("title_original"), item.get("summary_original"), item.get("summary"))
    if "伦敦证券交易所集团" not in source and "lseg" not in original and "lch" not in original:
        return False
    has_lch = "lch" in text
    has_clearing = contains_any_phrase(text, ("clears", "cleared", "clearing"))
    has_ois = "ois" in text or "overnight index swap" in text or "overnight index swaps" in text
    has_new = contains_any_phrase(text, ("first", "launch", "new currency", "new index"))
    return has_lch and has_clearing and has_ois and has_new


def is_regulatory_final_rule_signal(item, text):
    if (item.get("category") or "").lower() != "macro":
        return False
    source = item.get("source") or ""
    source_context = source in REGULATORY_SOURCES or contains_any_phrase(text, ("regulator", "agency", "agencies"))
    if not source_context:
        return False
    if "final settlement" in text or "final results" in text or "final dividend" in text:
        return False
    return "final rule" in text or "interim final rule" in text


def is_competitor_interim_results_signal(item, text):
    if (item.get("category") or "").lower() not in {"competitor", "dbg"}:
        return False
    result_terms = (
        "interim results",
        "half-year results",
        "half year results",
        "h1 results",
        "first-half results",
        "first half results",
    )
    if not contains_any_phrase(text, result_terms):
        return False
    return contains_any_phrase(text, ("results", "financial", "earnings", "h1", "half-year", "half year"))


def is_nasdaq_routine_short_interest(item, text):
    source = (item.get("source") or "").lower()
    original = normalize_text(item.get("title_original"), item.get("summary_original"), item.get("summary"))
    if "纳斯达克公司" not in source and "nasdaq" not in original:
        return False
    routine_pattern = contains_any_phrase(
        text,
        (
            "mid-month open short interest positions",
            "end-of-month open short interest positions",
            "open short interest positions in nasdaq stocks",
        ),
    )
    material_override = contains_any_phrase(
        text,
        ("methodology change", "regulatory change", "market structure", "exceptional", "rule"),
    )
    return routine_pattern and not material_override


def is_non_financial_policy_context(text):
    if not contains_any_phrase(text, NON_FINANCIAL_POLICY_CONTEXT_TERMS):
        return False
    return not contains_any_phrase(text, FINANCIAL_POLICY_CONTEXT_TERMS)


def lacks_financial_market_object_for_generic_action(text):
    if contains_any_phrase(text, STANDALONE_STRONG_CONTEXT_TERMS):
        return False
    if not contains_any_phrase(text, GENERIC_ACTION_TERMS):
        return False
    if contains_any_phrase(text, FINANCIAL_MARKET_OBJECT_TERMS):
        return False
    return True


def has_low_value_event_signal(text):
    return contains_any_phrase(text, LOW_VALUE_EVENT_TERMS)


def is_routine_enforcement_termination(text):
    return contains_any_phrase(text, ROUTINE_ENFORCEMENT_TERMINATION_TERMS)


def is_financial_market_settlement_signal(text):
    if not contains_term(text, "settlement") and "settlements" not in text:
        return False
    if contains_any_phrase(text, FINANCIAL_MARKET_SETTLEMENT_CONTEXT_TERMS):
        return True
    if contains_any_phrase(text, NON_FINANCIAL_SETTLEMENT_CONTEXT_TERMS):
        return False
    return contains_any_phrase(
        text,
        (
            "securities",
            "trades",
            "clearing",
            "post-trade",
            "post trade",
            "central securities depository",
            "collateral",
            "repo",
            "digital asset",
            "institutional",
            "local currency transaction",
            "payment system",
        ),
    )


def is_consumer_scam_alert_without_material_impact(text):
    if not contains_any_phrase(text, CONSUMER_SCAM_ALERT_TERMS):
        return False
    if contains_any_phrase(text, SCAM_MATERIAL_OVERRIDE_TERMS):
        return False
    return contains_any_phrase(text, CONSUMER_SCAM_CONTEXT_TERMS)


# Scoring

def score_item(item):
    category = (item.get("category") or "").lower()
    bucket = "macro"
    if category == "dbg":
        bucket = "dbg"
    elif category == "competitor":
        bucket = "competitor"

    text = build_relevance_text(item)

    score = 0
    reasons = []

    for term in POSITIVE_TERMS[bucket]:
        if term == "settlement" and not is_financial_market_settlement_signal(text):
            continue
        if term == "acquisition" and not has_acquisition_event_signal(text):
            continue
        if term in text:
            score += 2
            reasons.append(term)

    for term in HIGH_IMPORTANCE_TERMS:
        if term == "settlement" and not is_financial_market_settlement_signal(text):
            continue
        if term == "acquisition" and not has_acquisition_event_signal(text):
            continue
        if term in text:
            score += 2
            reasons.append(f"important:{term}")

    for term in HIGH_VALUE_MACRO_TERMS:
        if term in text:
            score += 6
            reasons.append(f"hard_signal:{term}")

    if bucket in ("dbg", "competitor"):
        for term in HIGH_VALUE_BUSINESS_TERMS:
            if term == "acquisition" and not has_acquisition_event_signal(text):
                continue
            if term in text:
                score += 6
                reasons.append(f"hard_signal:{term}")
    elif has_high_value_business_signal(text):
        score += 4
        reasons.append("hard_signal:business_development")

    for term in NEGATIVE_TERMS:
        if contains_term(text, term):
            score -= 5
            reasons.append(f"downrank:{term}")

    if has_routine_operational_signal(text) and not routine_operational_is_overridden(text):
        score -= 14
        reasons.append("downrank:routine_operational")

    if is_recurring_market_commentary(item, text) and not has_material_development_signal(text):
        score -= 4
        reasons.append("downrank:recurring_market_commentary")

    if bucket == "competitor" and is_ice_commodity_market_signal(item, text):
        score += 6
        reasons.append("source_signal:ice_commodity_market")

    if is_bafin_ai_market_surveillance_signal(item, text):
        score += 6
        reasons.append("source_signal:bafin_ai_market_surveillance")

    if is_clearstream_dlt_settlement_signal(item, text):
        score += 8
        reasons.append("source_signal:clearstream_dlt_settlement")

    if is_clearstream_monthly_figures_signal(item, text):
        score += 6
        reasons.append("source_signal:clearstream_monthly_figures")

    if is_lch_ois_clearing_signal(item, text):
        score += 8
        reasons.append("source_signal:lch_ois_clearing")

    if is_regulatory_final_rule_signal(item, text):
        score += 8
        reasons.append("hard_signal:regulatory_final_rule")

    if is_competitor_interim_results_signal(item, text):
        score += 6
        reasons.append("hard_signal:interim_results")

    if is_nasdaq_routine_short_interest(item, text):
        score -= 8
        reasons.append("downrank:nasdaq_routine_short_interest")

    if is_routine_enforcement_termination(text):
        score -= 6
        reasons.append("downrank:routine_enforcement_termination")

    if is_consumer_scam_alert_without_material_impact(text):
        score -= 8
        reasons.append("downrank:consumer_scam_alert")

    if has_low_value_event_signal(text):
        score -= 8
        reasons.append("downrank:low_value_event")

    individual_enforcement = is_individual_enforcement(text)
    market_wide = contains_any_phrase(text, MARKET_WIDE_TERMS)
    if individual_enforcement and not market_wide:
        score -= 6
        reasons.append("downrank:individual_enforcement")

    if contains_any_phrase(text, NON_FINANCIAL_POLICY_TERMS) or is_non_financial_policy_context(text):
        score -= 8
        reasons.append("downrank:non_financial_policy")

    if bucket == "macro" and lacks_financial_market_object_for_generic_action(text):
        score -= 6
        reasons.append("downrank:no_financial_market_object")

    personnel_change = contains_any_phrase(
        text,
        ("appoints", "appointment", "appointed", "elects", "elected", "management board", "board member"),
    )
    top_leadership = contains_any_phrase(text, ("chair", "chairman", "president", "chief executive", "ceo"))
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


# Diagnostics / rejection audit

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
        if contains_any_phrase(text, terms):
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
