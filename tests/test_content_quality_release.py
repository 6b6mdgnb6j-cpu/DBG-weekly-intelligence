import json
import argparse
import io
import tempfile
import run_weekly
import unittest
from copy import deepcopy
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup
from crawler.translation_quality import (FAIL, audit_translation_quality,
    validate_translation_field)
from crawler.translator import TerminologyNormalizer, TitleTranslator
from crawler.manual_translations import (validate_manual_rows, apply_approved_overrides,
    stable_item_id, original_sha256)
from crawler.adapters.expansion import parse_article_release_list
from crawler.adapters.fin_fsa import parse_fin_fsa_list, fin_fsa_publication_date
from crawler.article_parser import parse_article
from crawler.web_parser import collect_web
from qa_gate import evaluate_content, qa_exit_code

FIXTURES = Path(__file__).parent / 'fixtures' / 'content_quality'
SOURCE = {'id': 'SRC-037', 'name': '芬兰金融监管局', 'url': 'https://www.finanssivalvonta.fi',
          'crawl_url': 'https://www.finanssivalvonta.fi/en/publications-and-press-releases/Press-release/',
          'category': 'Macro', 'max_pages': 1, 'max_scan_candidates': 30}
NEWS = SOURCE['crawl_url'] + '2026/release/'
START, END = date(2026, 9, 28), date(2026, 10, 4)


def field_issues(original, translated, field='title'):
    return validate_translation_field(original, translated, field_type=field, include_sanity=False)


class TranslationContentRegression(unittest.TestCase):
    def test_all_six_production43_failures_blocked_in_final_and_field_checks(self):
        for item in json.loads((FIXTURES / 'production43_translation_cases.json').read_text()):
            with self.subTest(title=item['title_original']):
                self.assertTrue(any(x['severity'] == FAIL for x in audit_translation_quality([item])))
                for field in ('title', 'summary'):
                    self.assertTrue(any(x['severity'] == FAIL for x in field_issues(
                        item[field+'_original'], item[field+'_cn'], field)))

    def test_financial_terms_correct_renderings_pass(self):
        pairs = [
            ('Acceptable Collateral Haircut Review', '合格抵押品折扣率审查'),
            ('Review of haircuts applied to member margin collateral', '审查适用于会员保证金抵押品的折减率'),
            ('IFC issues bonds', '国际金融公司发行债券'),
            ('EIOPA reports progress', '欧洲保险和职业养老金管理局报告进展'),
            ('ICE launches JKM LNG (Platts) options', 'ICE推出JKM LNG（普氏）期权'),
            ('ISS STOXX launches PolicySteward', 'ISS STOXX推出PolicySteward'),
            ('The go-live date follows the registration deadline.', '上线日期晚于注册截止日期。'),
        ]
        for en, cn in pairs:
            with self.subTest(en=en): self.assertFalse(field_issues(en, cn))

    def test_new_entity_names_are_hard_protected_and_accept_chinese_manual_names(self):
        normalizer = TerminologyNormalizer()
        for entity in ('IFC', 'EIOPA', 'Platts', 'PolicySteward'):
            self.assertIn(entity, [x[0] for x in normalizer.protected_entity_occurrences(entity + (' issues bonds' if entity == 'IFC' else ''))])
        self.assertFalse(field_issues('IFC and IMF publish reports', '国际金融公司和国际货币基金组织发布报告'))

    def test_context_free_haircuts_and_options_not_financial(self):
        self.assertFalse(field_issues('Haircuts and colour options', '理发和染色选项'))

    def test_generic_options_inside_financial_text_are_not_derivatives(self):
        for en, cn in [
            ('The equity data feed offers several delivery options.', '股票数据流提供多种交付选项。'),
            ('Options for improving the electricity network are discussed.', '讨论改善电网的方案。'),
            ('The index team reviews options for exporting data.', '指数团队审查数据导出选项。'),
            ('Equity options and data delivery options are available.', '提供股票期权和数据交付选项。'),
        ]:
            with self.subTest(en=en):
                self.assertFalse(field_issues(en, cn))
        # Scope this ambiguous adjective case to the options rule; the existing
        # title-action heuristic independently treats "clear" as a verb.
        issues = field_issues('Clear options for electricity payments are offered.', '提供明确的电费支付选项。')
        self.assertNotIn('translation_financial_term_missing', [x['issue_id'] for x in issues])
        for en in ['Equity options', 'Index (SPX) options', 'JKM LNG (Platts) options',
                   'Trade options on futures', 'New options contracts', 'TTF average price options']:
            with self.subTest(en=en):
                issues = field_issues(en, '提供新的选项')
                self.assertIn('translation_financial_term_missing', [x['issue_id'] for x in issues])

    def test_ifc_requires_institution_context_in_all_entity_paths(self):
        normalizer = TerminologyNormalizer()
        for en, cn in [
            ('Industry Foundation Classes (IFC) data models', '工业基础类数据模型'),
            ('A bank uses Industry Foundation Classes (IFC) files for its investments.',
             '银行使用工业基础类文件进行投资。'),
            ('The International Finance Centre (IFC) houses banks.', '国际金融中心设有银行。'),
            ('The International Finance Centre (IFC) hosts bond investors.', '国际金融中心接待债券投资者。'),
            ('IFC releases an update', '发布更新'),
        ]:
            with self.subTest(en=en):
                self.assertFalse(normalizer.protected_entity_occurrences(en))
                self.assertFalse(field_issues(en, cn))
                normalized, _ = normalizer.normalize(cn, en, '')
                self.assertNotIn('IFC', normalized)
        for en in ['IFC bonds', 'International Finance Corporation issues an update',
                   'LCH Collateral Extensions - ASIA, IFC and IADB denominated in USD']:
            with self.subTest(en=en):
                self.assertTrue(normalizer.protected_entity_occurrences(en))
                self.assertTrue(field_issues(en, '国际货币基金组织（IFC）发布更新'))

    def test_equivalent_currency_scales_pass_without_week_specific_constants(self):
        pairs = [('£894 million', '8.94亿英镑'), ('£894 million', '894百万英镑'),
                 ('GBP 1 billion', '1000百万英镑'), ('GBP 1 billion', '10.000亿英镑'),
                 ('£0.5 million', '英镑50万'), ('£12 million', '1200万英镑'),
                 ('USD 1.25 billion', '12.5亿美元'), ('€2 trillion', '2万亿欧元'),
                 ('£1,234,567', '1234567英镑'), ('£0.75 million', '75万英镑'),
                 ('£894m', '8.94亿英镑'), ('£1.8bn', '18亿英镑'),
                 ('USD 2b', '20亿美元'), ('GBP 75k', '7.5万英镑'),
                 ('GBP 894 million', '894 million GBP'), ('£894 million', '£0.894 billion')]
        for en, cn in pairs:
            with self.subTest(en=en, cn=cn): self.assertFalse(field_issues(en, cn))

    def test_wrong_magnitude_currency_omission_or_incomplete_currency_blocks(self):
        for cn in ['894亿英镑', '894万英镑', '8.94亿美元', '资金流入', '8.94亿英']:
            with self.subTest(cn=cn):
                self.assertIn('translation_monetary_value_mismatch',
                              [x['issue_id'] for x in field_issues('£894 million', cn)])

    def test_multiple_amounts_are_not_matched_to_unrelated_dates(self):
        original = 'In 2026 inflows were £894 million; in 2025 outflows were £1.8 billion.'
        self.assertFalse(field_issues(original, '2026年流入8.94亿英镑，2025年流出18亿英镑。', 'summary'))
        self.assertTrue(field_issues(original, '2026年流入8.94亿英镑。', 'summary'))
        self.assertTrue(field_issues('£10 million and £10 million', '1000万英镑'))

    def test_candidate_and_manual_validation_use_same_material_and_numeric_rules(self):
        for original, translated in [('Collateral haircut review', '抵押品剪发审查'),
                                     ('£12 million', '12亿英镑'),
                                     ('Fiat currency', '菲亚特货币')]:
            self.assertTrue(TitleTranslator._semantic_field_issues(original, translated, 'title', 'LCH'))
            rows = [{'item_id': 'test', 'source': 'LCH', 'field': 'title',
                     'original_text': original, 'title_original': original,
                     'manual_translation': translated}]
            self.assertTrue(validate_manual_rows(rows))

    def test_existing_manual_overrides_remain_first_and_unchanged(self):
        item = {'source': 'ISS STOXX', 'date': '2026-09-30', 'url': 'https://example.test/news',
                'title_original': 'ISS STOXX launches PolicySteward', 'title_cn': '机器翻译'}
        manual = '  ISS STOXX推出PolicySteward\n'
        approved = {'schema_version': 1, 'week_start': '2026-09-28', 'overrides': [{
            'source': item['source'], 'date': item['date'], 'url': item['url'], 'field': 'title',
            'item_id': stable_item_id(item, 'title', item['title_original']),
            'original_sha256': original_sha256(item['title_original']), 'manual_translation': manual}]}
        payload = {'week_start': '2026-09-28', 'items': [item]}
        self.assertEqual(apply_approved_overrides(payload, approved), (1, 0))
        self.assertEqual(item['title_cn'], manual)
        self.assertEqual(item['translation_provenance']['title'], 'manual_approved')
        self.assertFalse(audit_translation_quality([item]))
        # A bad existing approval still wins; QA blocks it without rewriting it.
        approved['overrides'][0]['manual_translation'] = '  ISS STOXX推出政策  '
        self.assertEqual(apply_approved_overrides(payload, approved), (1, 0))
        before = deepcopy(item)
        self.assertTrue(audit_translation_quality([item]))
        self.assertEqual(before, item)

    def test_real_render_and_final_qa_read_post_override_text(self):
        original = 'Fund inflows reached £894 million'
        for machine, manual, should_fail in [
            ('基金流入达到894亿英镑', '基金流入达到8.94亿英镑', False),
            ('基金流入达到8.94亿英镑', '基金流入达到894亿英镑', True),
        ]:
            with self.subTest(manual=manual), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp)
                item = {'source': '英国投资管理协会', 'date': str(START),
                        'url': 'https://www.theia.org/news/press-releases/test',
                        'category': 'Macro', 'subcategory': '英国',
                        'title_original': original, 'title_cn': machine}
                weekly = output / 'weekly_data_20260928.json'
                weekly.write_text(json.dumps({'week_start': str(START), 'week_end': str(END),
                                              'items': [item]}))
                statuses = output / 'source_status_20260928.json'
                statuses.write_text('[]')
                approved = {'schema_version': 1, 'week_start': str(START), 'overrides': [{
                    'source': item['source'], 'date': item['date'], 'url': item['url'],
                    'field': 'title', 'item_id': stable_item_id(item, 'title', original),
                    'original_sha256': original_sha256(original), 'manual_translation': manual}]}
                result = {'week_start': START, 'week_end': END, 'weekly_data_path': weekly,
                          'source_status_path': statuses, 'items': [item]}
                args = argparse.Namespace(start=str(START), no_translate=False, require_translation=False,
                                          skip_qa=False, fail_on_warning=True, output_dir=tmp)
                with patch.object(run_weekly, 'collect_week', return_value=result), patch.object(
                        run_weekly, 'apply_approved_file',
                        side_effect=lambda payload, week: apply_approved_overrides(payload, approved)), patch.object(
                        run_weekly, 'print_generation_summary'), patch('sys.stdout', new_callable=io.StringIO):
                    run_weekly.run_weekly(args)
                self.assertEqual(json.loads(weekly.read_text())['items'][0]['title_cn'], manual)
                html = (output / 'weekly_report_20260928.html').read_text()
                self.assertIn(manual, html)
                self.assertNotIn(machine, html)
                qa = json.loads((output / 'qa_report_20260928.json').read_text())
                numeric = [x for x in qa['content_issues']
                           if x.get('issue_id') == 'translation_monetary_value_mismatch']
                self.assertEqual(bool(numeric), should_fail)
                self.assertEqual(qa['input_artifacts']['weekly_data'], str(weekly))

    def test_final_qa_blocks_original_production_translation_fixture(self):
        items = json.loads((FIXTURES / 'production43_translation_cases.json').read_text())
        checks, _, _ = evaluate_content({'items': items}, START, END)
        check = next(x for x in checks if x['id'] == 'translation_quality_failures')
        self.assertEqual(check['result'], FAIL)
        self.assertEqual(qa_exit_code(check['result']), 2)



class FinFsaPublicationRegression(unittest.TestCase):
    def response(self, html):
        return Mock(text=html, headers={'Content-Type': 'text/html'}, status_code=200)

    def test_actual_nav_dates_explain_old_false_positives(self):
        soup = BeautifulSoup((FIXTURES/'fin_fsa_listing.html').read_text(), 'html.parser')
        old = parse_article_release_list(soup, SOURCE['crawl_url'], SOURCE)
        bad = [x for x in old if x['title'] == 'Financial market stability']
        self.assertTrue(bad)
        self.assertEqual(bad[0]['date'], '30 September 2026')
        new = parse_fin_fsa_list(soup, SOURCE['crawl_url'], SOURCE)
        self.assertTrue(new)
        self.assertTrue(all('/publications-and-press-releases/' in x['url'] for x in new))
        self.assertFalse(any('/financial-market-stability/' in x['url'] for x in new))

    def test_final_qa_blocks_replayed_container_records(self):
        item = {'source': SOURCE['name'], 'date': '2026-09-30',
                'url': SOURCE['url'] + '/en/financial-market-stability/'}
        checks, _, _ = evaluate_content({'items': [item]}, START, END)
        self.assertEqual(next(x for x in checks if x['id'] == 'fin_fsa_publication_pages_only')['result'], FAIL)
        item['url'] = NEWS
        checks, _, _ = evaluate_content({'items': [item]}, START, END)
        self.assertEqual(next(x for x in checks if x['id'] == 'fin_fsa_publication_pages_only')['result'], 'PASS')

    def test_live_article_publication_labels(self):
        for n, expected in [('32', '28 September 2026'), ('41', '1 October 2026')]:
            soup = BeautifulSoup((FIXTURES/('fin_fsa_news_'+n+'.html')).read_text(), 'html.parser')
            self.assertEqual(fin_fsa_publication_date(soup), expected)

    def test_labelled_article_header_time_is_accepted_without_navigation_dates(self):
        html = ('<nav>Press release 30 September 2026</nav><article><header>'
                '<p>Press release <time>1 October 2026</time></p></header>'
                '<h1>Decision</h1></article>')
        with patch('crawler.article_parser.request_get', return_value=self.response(html)):
            _, kept, _ = parse_article(NEWS, SOURCE, START, END, Mock(), list_date='2026-09-30')
        self.assertEqual(kept['date'], '2026-10-01')

    def test_supported_publication_types_require_their_own_labelled_date(self):
        for path, label in [('Press-release', 'Press release'), ('news', 'News'),
                            ('supervision-releases', 'Supervision release')]:
            url = SOURCE['url'] + '/en/publications-and-press-releases/' + path + '/2026/announcement/'
            html = '<article><p>' + label + ' 1 October 2026</p><h1>Announcement</h1></article>'
            with self.subTest(path=path), patch('crawler.article_parser.request_get', return_value=self.response(html)):
                _, kept, _ = parse_article(url, SOURCE, START, END, Mock())
            self.assertEqual(kept['date'], '2026-10-01')

    def test_container_and_decision_index_rejected_even_with_week_date(self):
        for path in ['financial-market-stability/', 'financial-market-stability/macroprudential/',
                     'financial-market-stability/macroprudential/macroprudential-decisions-and-appendices/',
                     'financial-market-stability/macroprudential/macroprudential-decisions-and-appendices/macroprudential-decisions-2026/',
                     'financial-market-stability/macroprudential/macroprudential-decisions-and-appendices/macroprudential-decisions-2026/macroprudential-decision-30-september-2026/']:
            with patch('crawler.article_parser.request_get') as get:
                _, kept, diagnostic = parse_article(SOURCE['url']+'/en/'+path, SOURCE, START, END, Mock(), list_date='2026-09-30')
                self.assertIsNone(kept); self.assertEqual(diagnostic['drop_reason'], 'non_news_container')
                get.assert_not_called()

    def test_article_date_overrides_list_date_and_child_dates_never_used(self):
        html = '<nav>30 September 2026</nav><article>Press release 1 October 2026<h1>Decision</h1><a>2 October 2026</a></article>'
        with patch('crawler.article_parser.request_get', return_value=self.response(html)):
            _, kept, _ = parse_article(NEWS, SOURCE, START, END, Mock(), list_date='2026-09-30')
        self.assertEqual(kept['date'], '2026-10-01')
        for html in ['<nav>30 September 2026</nav><article><h1>Decision</h1><a>Press release 1 October 2026</a></article>',
                     '<article><h1>Decision</h1><time>30 September 2026</time></article>',
                     '<meta name="date" content="2026-09-30"><article><h1>Decision</h1></article>']:
            with patch('crawler.article_parser.request_get', return_value=self.response(html)):
                _, kept, why = parse_article(NEWS, SOURCE, START, END, Mock(), list_date='2026-09-30')
            self.assertIsNone(kept); self.assertEqual(why['drop_reason'], 'untrusted_publication_date')

    def test_out_of_week_article_is_not_made_current_by_navigation(self):
        html = '<nav>30 September 2026</nav><article>Press release 1 September 2026<h1>Decision</h1></article>'
        with patch('crawler.article_parser.request_get', return_value=self.response(html)):
            _, kept, why = parse_article(NEWS, SOURCE, START, END, Mock(), list_date='2026-09-30')
        self.assertIsNone(kept); self.assertEqual(why['drop_reason'], 'outside_period')

    def test_one_decision_news_and_no_navigation_duplicates(self):
        listing = (FIXTURES/'fin_fsa_listing.html').read_text()
        def fetch(url, **kwargs):
            if url == SOURCE['crawl_url']: return self.response(listing)
            n = '32' if 'fin-fsa-regulation-can-be-simplified' in url else '41'
            return self.response((FIXTURES/('fin_fsa_news_'+n+'.html')).read_text())
        with patch('crawler.web_parser.request_get', side_effect=fetch), patch('crawler.article_parser.request_get', side_effect=fetch):
            raw, kept, metadata = collect_web(SOURCE, START, END, Mock())
        self.assertEqual(len(kept), 2)
        self.assertEqual(sum('macroprudential-decision-' in x['url'] for x in kept), 1)


if __name__ == '__main__': unittest.main()
