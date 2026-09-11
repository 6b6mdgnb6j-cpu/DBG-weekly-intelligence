import json
import unittest

from generate_weekly import json_for_script


class GenerateWeeklyHtmlTests(unittest.TestCase):
    def test_report_data_json_preserves_ampersand_text(self):
        embedded = json_for_script({"title": "S&P Dow Jones Indices"})
        parsed = json.loads(embedded)
        self.assertEqual(parsed["title"], "S&P Dow Jones Indices")
        self.assertNotIn("S&amp;P", embedded)

    def test_report_data_json_preserves_url_query_ampersand(self):
        url = "https://example.com/?a=1&b=2"
        embedded = json_for_script({"url": url})
        parsed = json.loads(embedded)
        self.assertEqual(parsed["url"], url)
        self.assertNotIn("&amp;", embedded)

    def test_report_data_json_escapes_script_closing_boundary(self):
        embedded = json_for_script({"title": "safe </script> boundary"})
        parsed = json.loads(embedded)
        self.assertEqual(parsed["title"], "safe </script> boundary")
        self.assertNotIn("</script>", embedded.lower())


if __name__ == "__main__":
    unittest.main()
