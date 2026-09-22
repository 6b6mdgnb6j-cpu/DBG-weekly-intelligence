#!/usr/bin/env python3
import json

from crawler.translation_quality import FAIL, validate_translation_field
from crawler.translator import ProtectedEntityError, TitleTranslator, TranslationUnavailableError


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
)


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
            status = "PASS" if not issues else "FAIL"
            failures += bool(issues)
            print(json.dumps({
                "fixture": fixture["name"],
                "status": status,
                "translation": output,
                "issues": issues,
            }, ensure_ascii=False))
        except ProtectedEntityError as exc:
            failures += 1
            print(json.dumps({
                "fixture": fixture["name"],
                "status": "FAIL",
                "entity_failure": exc.details,
            }, ensure_ascii=False))
        except TranslationUnavailableError as exc:
            failures += 1
            print(json.dumps({
                "fixture": fixture["name"],
                "status": "FAIL",
                "error": str(exc),
            }, ensure_ascii=False))
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
