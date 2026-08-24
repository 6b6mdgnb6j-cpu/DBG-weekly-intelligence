import re


def looks_chinese(text):
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


class TitleTranslator:
    def __init__(self, enabled=True, logger=None):
        self.enabled = enabled
        self.logger = logger

    def translate(self, items):
        translated = []
        if not self.enabled and self.logger:
            self.logger.info("Title translation skipped by --no-translate")

        for item in items:
            clean = dict(item)
            original = clean.get("title_original", "")

            if looks_chinese(original):
                clean["title_cn"] = original
                clean["title_en"] = original
            else:
                clean["title_en"] = original
                clean["title_cn"] = original

            if self.enabled and self.logger:
                self.logger.info(
                    "Title translation fallback used for %s; no credential-free translator configured",
                    clean.get("source", ""),
                )

            translated.append(clean)

        return translated
