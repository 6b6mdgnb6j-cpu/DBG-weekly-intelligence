#!/usr/bin/env python3
import json

from crawler.translation_quality import FAIL, validate_translation_field
from crawler.translator import TitleTranslator, TranslationUnavailableError


FIXTURES = (
    {
        "name": "tocom_abn_amro",
        "source": "JPX",
        "field": "title",
        "text": (
            "Tokyo Commodity Exchange Welcomes ABN AMRO Clearing Tokyo Co., Ltd. as a "
            "Broker Member for Trading TOCOM Electricity (Power) and Other Energy Futures | "
            "Japan Exchange Group"
        ),
    },
    {
        "name": "hashkey_obita",
        "source": "HashKey",
        "field": "summary",
        "text": (
            "Hong Kong, Sep. 15, 2026 — HashKey Exchange, a licensed trading platform under "
            "HashKey Holdings Limited (3887.HK), an Asian comprehensive digital asset company, "
            "announced that it has reached a partnership with Obita, a global payment service provider. "
            "Within the scope of its licensed and permitted business, HashKey Exchange will provide "
            "institutional-grade digital asset custody support […]"
        ),
    },
    {
        "name": "hashkey_exchange_obita_title",
        "source": "HashKey",
        "field": "title",
        "text": (
            "HashKey Exchange Partners with Obita to Provide Institutional-Grade Digital "
            "Asset Custody Support"
        ),
        "must_contain": ("HashKey Exchange", "Obita", "数字资产托管"),
        "must_not_contain": ("哈希基交换", "奥比塔", "数字资产监管"),
    },
    {
        "name": "partior_two_occurrences",
        "source": "Partior",
        "field": "title",
        "text": (
            "Partior and LSEG DiSH Collaborate to Bring Always-On Settlement Bank Liquidity "
            "to Partior’s Cross-Border Payments Network"
        ),
    },
    {
        "name": "ftse_russell",
        "source": "LSEG",
        "field": "title",
        "text": "FTSE Russell announces benchmark methodology changes for global equity indices",
    },
    {
        "name": "iss_financial_context",
        "source": "ISS STOXX",
        "field": "title",
        "text": "ISS publishes its latest institutional shareholder governance review",
    },
    {
        "name": "euro_exchange_securities",
        "source": "FCA",
        "field": "title",
        "text": "FCA opens investigation into Euro Exchange Securities UK Ltd",
    },
    {
        "name": "prometheum_finra_critical_term",
        "source": "HashKey",
        "field": "summary",
        "text": (
            "Agreement establishes a pathway built on SEC-registered broker-dealer "
            "infrastructure to distribute U.S. equities to eligible international investors "
            "through HashKey’s licensed exchange network. New York, Sep. 16, 2026 – "
            "Prometheum Inc. (“Prometheum”), a market infrastructure provider for crypto "
            "assets, today announced that its subsidiary Prometheum Capital LLC "
            "(“Prometheum Capital”), an SEC-registered, FINRA member crypto asset custodian […]"
        ),
        "must_contain": ("SEC", "Prometheum", "Prometheum Capital", "FINRA", "HashKey"),
    },
    {
        "name": "iss_sec_client_voting_summary",
        "source": "ISS STOXX",
        "field": "summary",
        "text": (
            "ROCKVILLE, Md. (September 18, 2026) – Institutional Shareholder Services (ISS) "
            "today submitted a brief in the U.S. District Court for the Eastern District of "
            "Pennsylvania challenging an unconstitutional demand in a U.S. Securities & Exchange "
            "Commission subpoena that would require the company to hand over millions of lines of "
            "data reflecting its clients’ votes on […]"
        ),
        "must_contain": ("ISS", "SEC"),
        "relationship": "iss_challenges_sec",
    },
    {
        "name": "sec_ipo_increase_title",
        "source": "SEC",
        "field": "title",
        "text": "SEC Publishes Updated Market Statistics, Highlighting Increase in IPOs and Proceeds Raised",
    },
    {
        "name": "finra_restitution_fines",
        "source": "FINRA",
        "field": "title",
        "text": "FINRA Orders American Portfolios to Pay $1.2 Million in Restitution and $400,000 in Fines for UIT Supervision Failures",
    },
    {
        "name": "finra_otc_high_price_list",
        "source": "FINRA",
        "field": "title",
        "text": "FINRA Updates the OTC Equities High Price Dissemination List",
        "must_contain": ("FINRA", "场外股票"),
        "must_not_contain": ("超市股票", "国际金融局", "芬拉"),
    },
    {
        "name": "ccp_global_chile_comment_letter",
        "source": "CCP Global",
        "field": "title",
        "text": "CCP Global submits a comment letter to the Ministry of Finance of Chile on central clearing of government bond and repo market",
    },
    {
        "name": "topix_banks_leveraged_inverse",
        "source": "JPX",
        "field": "title",
        "text": "TOPIX Banks Leveraged and Inverse Index Series to be Launched",
    },
    {
        "name": "corporate_treasurers_secured_investing",
        "source": "Clearstream",
        "field": "title",
        "text": "Why Secured Short-Term Investing Is Gaining Relevance for Corporate Treasurers",
        "must_contain": ("企业财资负责人",),
        "must_not_contain": ("企业财务员", "企业财政部长"),
    },
)


def classify_quality_issues(issues):
    return "PASS" if not issues else "QA_FAIL"


def fixture_constraint_issues(fixture, output):
    issues = []
    for value in fixture.get("must_contain", ()):
        if value not in output:
            issues.append({"issue_id": "smoke_required_text_missing", "evidence": value})
    for value in fixture.get("must_not_contain", ()):
        if value in output:
            issues.append({"issue_id": "smoke_forbidden_text_present", "evidence": value})
    if fixture.get("relationship") == "iss_challenges_sec":
        iss_index = output.find("ISS")
        sec_index = output.find("SEC")
        submit_indices = [output.find(term) for term in ("提交", "递交") if term in output]
        if not (
            iss_index >= 0
            and sec_index >= 0
            and submit_indices
            and iss_index < min(submit_indices)
            and sec_index > min(submit_indices)
            and any(term in output for term in ("挑战", "质疑", "反对", "抗辩"))
        ):
            issues.append({"issue_id": "smoke_relationship_failure", "evidence": "ISS_challenges_SEC"})
    return issues


def main():
    translator = TitleTranslator(enabled=True, strict=True)
    translator.cache = {}
    failures = 0
    for fixture in FIXTURES:
        try:
            output = translator._translate_text(
                fixture["text"], fixture["source"], field=fixture["field"]
            )
            issues = [
                issue
                for issue in validate_translation_field(
                    fixture["text"],
                    output,
                    fixture["field"],
                    fixture["source"],
                )
                if issue.get("severity") == FAIL
            ]
            issues.extend(fixture_constraint_issues(fixture, output))
            status = classify_quality_issues(issues)
            failures += bool(issues)
            print(json.dumps({
                "fixture": fixture["name"],
                "status": status,
                "translation": output,
                "issues": issues,
            }, ensure_ascii=False))
        except TranslationUnavailableError as exc:
            failures += 1
            print(json.dumps({
                "fixture": fixture["name"],
                "status": "FATAL",
                "error": str(exc),
            }, ensure_ascii=False))
        except Exception as exc:
            failures += 1
            print(json.dumps({
                "fixture": fixture["name"],
                "status": "FATAL",
                "error": f"{type(exc).__name__}: {exc}",
            }, ensure_ascii=False))

    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
