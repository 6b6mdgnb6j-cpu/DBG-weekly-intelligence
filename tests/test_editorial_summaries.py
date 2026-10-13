import ast
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import snapshot_replay
from automation_pipeline import AutomationValidationError, validate_bilingual_artifacts, validate_manifest
from crawler.manual_editorial_summaries import EditorialSummaryError, load_editorial_summaries, record_hash, summary_id
from crawler.manual_supplements import content_hash, load_supplements, record_hash as supplement_hash, ManualSupplementError
from crawler.manual_translations import original_sha256, stable_item_id
from crawler.translation_quality import validate_translation_field


APPROVED = Path('manual_editorial_summaries/approved/weekly_20261005.json')
WEEK = '2026-10-05'
TITLE = 'Minutes of the Federal Open Market Committee, September 15-16, 2026'
FOMC_CN = '美联储于10月7日公布9月15日至16日FOMC会议纪要。纪要显示，委员会一致同意将联邦基金利率目标区间上调25个基点至3.75%—4.00%，认为通胀仍然偏高，而经济活动保持稳健。多数与会者认为年底前可能还需进一步加息，但强调未来政策决定仍将取决于后续经济数据。'
FOMC_EN = 'The Federal Reserve released the minutes of its September 15–16 FOMC meeting on October 7. The Committee unanimously raised the federal funds rate target range by 25 basis points to 3.75–4.00%, citing elevated inflation and resilient economic activity. Most participants considered another rate increase by year-end likely appropriate, while emphasizing that future decisions would depend on incoming economic data.'


class IncreaseDirectionRegression(unittest.TestCase):
    def issues(self, en, cn):
        return validate_translation_field(en, cn, field_type='summary')

    def test_raised_rates_upward_synonym(self):
        self.assertFalse(self.issues('The central bank raised interest rates.', '央行上调利率。'))

    def test_increased_target_range_upward_synonym(self):
        self.assertFalse(self.issues('The Committee increased the federal funds rate target range by 25 basis points.',
                                     '委员会将联邦基金利率目标区间上调25个基点。'))

    def test_exact_approved_fomc_bilingual_text_unchanged_and_passes(self):
        record = json.loads(APPROVED.read_text())['records'][0]
        self.assertEqual(record['summary_cn'], FOMC_CN)
        self.assertEqual(record['summary_en'], FOMC_EN)
        self.assertFalse(self.issues(FOMC_EN, FOMC_CN))

    def test_generic_adjustment_does_not_preserve_increase(self):
        self.assertIn('translation_action_direction_missing', [i['issue_id'] for i in
                      self.issues('The central bank raised interest rates.', '央行调整利率。')])

    def test_decrease_is_not_an_increase(self):
        self.assertIn('translation_action_direction_missing', [i['issue_id'] for i in
                      self.issues('The central bank raised interest rates.', '央行下调利率。')])

    def test_capital_requirement_adjustment_still_missing_direction(self):
        self.assertIn('translation_action_direction_missing', [i['issue_id'] for i in
                      self.issues('The regulator increased capital requirements.', '监管机构调整资本要求。')])


class GrowthAndScaleRegression(unittest.TestCase):
    def issues(self, en, cn):
        return validate_translation_field(en, cn, field_type='title')

    def test_compound_business_development_equivalence(self):
        self.assertFalse(self.issues("Support the industry's next phase of growth and scale.", '支持行业规模化发展。'))

    def test_exact_approved_dtcc_title_and_record_unchanged(self):
        data=json.loads(Path('manual_supplements/approved/weekly_20260928.json').read_text())
        record=next(r for r in data['records'] if r['source_id']=='SRC-184')
        self.assertEqual(record['title_en'], 'DTCC and iCapital Collaborate to Advance Private Market Infrastructure, Expand Access and Support the Industry’s Next Phase of Growth and Scale')
        self.assertEqual(record['title_cn'], 'DTCC与iCapital合作推进私募市场基础设施，扩大准入并支持规模化发展')
        self.assertEqual(record['url'], 'https://www.dtcc.com/press-releases/2026/dtcc-and-icapital-collaborate-to-advance-private-market-infrastructure')
        self.assertEqual(record['publication_date'], '2026-09-28')
        self.assertEqual(record['source_name'], 'DTCC')
        self.assertEqual(record['summary_en'], "DTCC and iCapital announced a collaboration connecting private-market infrastructure and investment workflows. DTCC also made a strategic investment in iCapital. Initial plans include further integration of DTCC's Alternative Investment Product with iCapital's platform.")
        self.assertEqual(record['summary_cn'], 'DTCC与iCapital宣布合作，连接私募市场基础设施与投资流程；DTCC同时对iCapital作出战略投资。双方初期计划进一步整合DTCC的Alternative Investment Product（AIP）与iCapital平台。')
        self.assertFalse(self.issues(record['title_en'],record['title_cn']))

    def test_revenue_growth_is_not_general_business_development(self):
        for cn in ('公司实现规模化发展。','公司实现业务发展。'):
            with self.subTest(cn=cn):
                self.assertTrue(any(i['issue_id']=='translation_title_proposition_missing' and i['severity']=='FAIL'
                                    for i in self.issues('The company reports revenue growth.',cn)))

    def test_scale_component_and_direction_must_both_exist(self):
        for cn in ('支持行业发展。','支持行业规模调整。'):
            with self.subTest(cn=cn):
                self.assertTrue(any(i['issue_id']=='translation_title_proposition_missing' and i['severity']=='FAIL'
                                    for i in self.issues("Support the industry's growth and scale.",cn)))

    def test_separate_revenue_increase_not_exempted(self):
        issues=self.issues('Support growth and scale while increasing revenue by 25%.','支持规模化发展。')
        self.assertTrue(any(i['issue_id']=='translation_title_proposition_missing' and i['severity']=='FAIL' for i in issues))

    def test_independent_growth_rise_raise_or_record_still_checked(self):
        for phrase in ('revenue growth','revenue rise','raises revenue','record growth'):
            with self.subTest(phrase=phrase):
                self.assertTrue(any(i['issue_id']=='translation_title_proposition_missing' for i in
                                    self.issues('Support growth and scale alongside '+phrase+'.','支持规模化发展。')))

    def test_other_title_anchors_still_checked(self):
        self.assertTrue(any(i['evidence'].get('anchor')=='launch' for i in
                            self.issues('Launch a platform to support growth and scale.','支持规模化发展。')))


class EditorialSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = json.loads(APPROVED.read_text())
        record = self.data['records'][0]
        self.item = {'date':record['date'], 'source':record['source'], 'url':record['url'],
                     'title_original':TITLE, 'title_en':TITLE, 'title_cn':'美国联邦公开市场委员会2026年9月15日至16日会议纪要',
                     'title_original_lang':'en', 'summary':'', 'summary_original':'', 'summary_en':'',
                     'summary_cn':'', 'summary_original_lang':'unknown', 'category':'Macro',
                     'subcategory':'美国', 'official':True, 'priority':1, 'relevance_score':8}

    def rehash(self):
        for record in self.data['records']:
            record['summary_id'] = summary_id(record)
            record['content_sha256'] = record_hash(record)

    def document(self, directory='approved'):
        path = self.root / directory / 'weekly_20261005.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.data, ensure_ascii=False))
        return path, snapshot_replay.sha256(path)

    def load(self, items=None, week=WEEK):
        path, digest = self.document()
        return load_editorial_summaries(path, digest, week, items or [self.item])

    def test_approved_enrichment_preserves_every_original_field_and_input(self):
        before = copy.deepcopy(self.item)
        output, _ = self.load()
        self.assertEqual(self.item, before)
        self.assertEqual({k:v for k,v in output[0].items() if k!='editorial_summary'}, before)
        self.assertEqual(output[0]['editorial_summary']['summary_cn'], FOMC_CN)
        self.assertEqual(output[0]['editorial_summary']['origin'], 'manual_editorial_summary')

    def test_draft_document_rejected(self):
        self.data['approval_status'] = 'DRAFT'
        with self.assertRaisesRegex(EditorialSummaryError, 'approval'): self.load()

    def test_draft_directory_rejected(self):
        path, digest = self.document('drafts')
        with self.assertRaisesRegex(EditorialSummaryError, 'draft'):
            load_editorial_summaries(path,digest,WEEK,[self.item])

    def test_draft_record_rejected(self):
        self.data['records'][0]['approval_status'] = 'DRAFT'
        self.rehash()
        with self.assertRaisesRegex(EditorialSummaryError, 'approved'): self.load()

    def test_missing_approval_rejected(self):
        self.data.pop('approval')
        with self.assertRaisesRegex(EditorialSummaryError, 'approval'): self.load()

    def test_naive_approval_timestamp_rejected(self):
        self.data['approval']['approved_at'] = '2026-10-13T12:00:00'
        with self.assertRaisesRegex(EditorialSummaryError, 'timezone'): self.load()

    def test_wrong_week_rejected(self):
        with self.assertRaisesRegex(EditorialSummaryError, 'week'): self.load(week='2026-09-28')

    def test_wrong_article_url_rejected(self):
        self.item['url'] += '?different=1'
        with self.assertRaisesRegex(EditorialSummaryError, 'identity'): self.load()

    def test_wrong_original_hash_rejected(self):
        self.data['records'][0]['original_summary_sha256'] = '0'*64
        self.rehash()
        with self.assertRaisesRegex(EditorialSummaryError, 'identity'): self.load()

    def test_tampered_record_rejected_even_with_updated_file_digest(self):
        self.data['records'][0]['summary_cn'] += '未经批准。'
        with self.assertRaisesRegex(EditorialSummaryError, 'hash'): self.load()

    def test_tampered_file_digest_rejected(self):
        path, _ = self.document()
        with self.assertRaisesRegex(EditorialSummaryError, 'SHA-256'):
            load_editorial_summaries(path, '0'*64, WEEK, [self.item])

    def test_missing_sha_rejected(self):
        path, _ = self.document()
        with self.assertRaisesRegex(EditorialSummaryError, 'required'):
            load_editorial_summaries(path, None, WEEK, [self.item])

    def test_duplicate_summary_rejected(self):
        self.data['records'].append(copy.deepcopy(self.data['records'][0]))
        with self.assertRaisesRegex(EditorialSummaryError, 'twice'): self.load()

    def test_ambiguous_original_items_rejected(self):
        with self.assertRaisesRegex(EditorialSummaryError, 'ambiguous'):
            self.load(items=[self.item, copy.deepcopy(self.item)])

    def test_nonempty_historical_summary_rejected(self):
        self.item['summary_cn'] = '已有摘要。'
        with self.assertRaisesRegex(EditorialSummaryError, 'empty'): self.load()

    def test_invalid_evidence_domain_rejected(self):
        self.data['records'][0]['source_verification']['official_urls'].append('https://example.test/claim')
        self.rehash()
        with self.assertRaisesRegex(EditorialSummaryError, 'domains'): self.load()

    def test_missing_evidence_rejected(self):
        self.data['records'][0].pop('source_verification')
        self.rehash()
        with self.assertRaisesRegex(EditorialSummaryError, 'evidence'): self.load()

    def test_bilingual_qa_is_not_disabled_for_editorial_summary(self):
        self.data['records'][0]['summary_cn'] = '委员会调整利率。'
        self.rehash()
        with self.assertRaisesRegex(EditorialSummaryError, 'QA failed'): self.load()

    def replay(self, supplement=False):
        registry = json.loads(Path('config/sources.json').read_text())
        statuses = [{'source':s['name'],'status':'true_no_updates','target_period_reached':True}
                    for s in registry if s.get('enabled')]
        statuses.append({'source':'Fixture gap','status':'blocked','target_period_reached':False})
        weekly = {'week_start':WEEK,'week_end':'2026-10-11','translation_mode':'bilingual',
                  'source_count':len(statuses),'registered_source_count':len(registry),'item_count':1,'items':[self.item]}
        archive = self.root/'snapshot.zip'
        status_bytes = json.dumps(statuses).encode()
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('weekly_data_20261005.json',json.dumps(weekly))
            z.writestr('source_status_20261005.json',status_bytes)
        approved = self.root/'translations.json'
        approved.write_text(json.dumps({'schema_version':1,'week_start':WEEK,'overrides':[]}))
        doc,digest = self.document()
        extra = {}
        if supplement:
            path = Path('manual_supplements/approved/weekly_20261005.json')
            extra = {'supplement_file':path,'supplement_sha256':snapshot_replay.sha256(path)}
        before = archive.read_bytes()
        with patch('crawler.collector.collect_week', side_effect=AssertionError('no collection')), \
             patch('crawler.translator.LocalNLLBProvider.translate', side_effect=AssertionError('no NLLB')), \
             patch('requests.sessions.Session.request', side_effect=AssertionError('no network')):
            result = snapshot_replay.replay_snapshot(archive,snapshot_replay.sha256(archive),WEEK,self.root/'out',approved,
                     '46','original-collection-sha','117','original-debug','99','fresh-generation-sha',
                     editorial_summary_file=doc,editorial_summary_sha256=digest,**extra)
        self.assertEqual(archive.read_bytes(),before)
        self.assertEqual((self.root/'out/source_status_20261005.json').read_bytes(),status_bytes)
        return result,self.root/'out'

    def test_replay_and_bundle_validate_with_no_network_or_model_and_new_provenance(self):
        result,out = self.replay()
        self.assertEqual(result['qa']['blocking_count'],0)
        validate_bilingual_artifacts(out,WEEK)
        manifest = validate_manifest(out,WEEK,'99','fresh-generation-sha','fresh-generation-sha')
        self.assertEqual(manifest['snapshot_provenance']['collection']['commit_sha'],'original-collection-sha')
        self.assertEqual(manifest['snapshot_provenance']['editorial_summaries']['original_item_count'],1)
        self.assertEqual(manifest['artifacts']['editorial_summaries']['sha256'],snapshot_replay.sha256(out/'editorial_summaries_20261005.json'))

    def test_summary_and_supplement_bundle_composition(self):
        _,out=self.replay(supplement=True)
        payload=json.loads((out/'weekly_data_20261005.json').read_text())
        self.assertEqual(len(payload['items']),6)
        self.assertEqual(payload['items'][0]['summary_original'],'')
        validate_manifest(out,WEEK,'99','fresh-generation-sha','fresh-generation-sha')

    def test_tampered_output_caught_after_weekly_and_manifest_hashes_are_updated(self):
        _,out=self.replay()
        manifest_path=out/'review_manifest_20261005.json'
        payload=json.loads((out/'weekly_data_20261005.json').read_text())
        payload['items'][0]['editorial_summary']['summary_cn'] += '篡改。'
        (out/'weekly_data_20261005.json').write_text(json.dumps(payload))
        manifest=json.loads(manifest_path.read_text())
        manifest['artifacts']['weekly_data']['sha256']=snapshot_replay.sha256(out/'weekly_data_20261005.json')
        qa_path=out/'qa_report_20261005.json'
        qa=json.loads(qa_path.read_text())
        qa['input_artifacts']['weekly_data_sha256']=manifest['artifacts']['weekly_data']['sha256']
        qa_path.write_text(json.dumps(qa))
        manifest['artifacts']['qa_report']['sha256']=snapshot_replay.sha256(qa_path)
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(AutomationValidationError,'tampered'):
            validate_manifest(out,WEEK)

    def test_summaries_without_manifest_provenance_rejected(self):
        _,out=self.replay()
        path=out/'review_manifest_20261005.json'
        manifest=json.loads(path.read_text());manifest['snapshot_provenance'].pop('editorial_summaries')
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(AutomationValidationError,'provenance'):validate_manifest(out,WEEK)

    def test_summary_sha_without_selection_rejected_before_input_or_output(self):
        with self.assertRaisesRegex(snapshot_replay.SnapshotReplayError,'supplied together'):
            snapshot_replay.replay_snapshot('missing','0'*64,WEEK,self.root/'out','missing','46','old','117','debug','99','new',editorial_summary_sha256='0'*64)
        self.assertFalse((self.root/'out').exists())

    def test_workflow_explicit_snapshot_week_and_sha_guards(self):
        workflow=Path('.github/workflows/weekly-report-production.yml').read_text()
        block=workflow.split('      - name: Prepare manual week input',1)[1].split('      - name:',1)[0]
        script=textwrap.dedent(block.split("          python3 - <<'PY'\n",1)[1].split('\n          PY',1)[0])
        for mode,week,digest,success in [('live',WEEK,'a'*64,False),('snapshot','','a'*64,False),
                                       ('snapshot',WEEK,'',False),('snapshot',WEEK,'a'*64,True)]:
            with self.subTest(mode=mode,week=week,digest=digest):
                env={**os.environ,'GENERATION_MODE':mode,'RAW_WEEK_START':week,'APPLY_SUMMARIES':'true',
                     'EDITORIAL_SUMMARY_SHA256':digest,'APPLY_SUPPLEMENTS':'false','SUPPLEMENT_SHA256':'',
                     'GITHUB_OUTPUT':str(self.root/'github-output')}
                result=subprocess.run([sys.executable,'-c',script],env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode==0,success)


class HistoricalApprovalRegression(unittest.TestCase):
    def test_week_a_24_unique_overrides_and_unrelated_20_records_unchanged(self):
        rows=json.loads(Path('manual_translations/approved/weekly_20260928.json').read_text())['overrides']
        self.assertEqual(len(rows),24)
        self.assertEqual(len({r['item_id'] for r in rows}),24)
        # Frozen semantic digest of the 20 unrelated previously approved records, in original order.
        unchanged=[r for r in rows[:21] if not (r['field']=='summary' and 'ICE-Launches-New-JKM' in r['url'])]
        self.assertEqual(content_hash(unchanged),'a27efc061d84d64352c3299ba6533cb3f177a1e46d3eaaebcbc4d1b4bf3310f1')

    def test_three_new_overrides_have_exact_original_identity_bindings(self):
        rows=json.loads(Path('manual_translations/approved/weekly_20260928.json').read_text())['overrides'][21:]
        self.assertEqual(len(rows),3)
        for row in rows:
            payload={key:row[key] for key in ('source','date','url','field','original_sha256')}
            self.assertEqual(content_hash(payload),row['item_id'])
        self.assertEqual([r['field'] for r in rows],['summary','summary','title'])

    def test_existing_ice_override_updated_once_and_title_untouched(self):
        rows=json.loads(Path('manual_translations/approved/weekly_20260928.json').read_text())['overrides']
        matches=[r for r in rows if 'ICE-Launches-New-JKM' in r['url']]
        self.assertEqual(len(matches),2)
        summary=next(r for r in matches if r['field']=='summary')
        self.assertEqual(summary['manual_translation'],'ICE宣布推出新的JKM LNG（Platts）期权、LNG Balmo运费期货及英国基荷电力期权，拓展天然气及电力衍生品业务。其中，新JKM期权（JKZ）与现有月均价期权形成互补，按月末标的期货结算价结算，为市场参与者提供亚洲天然气价格风险管理工具。')
        self.assertNotIn('此外，ICE',summary['manual_translation'])

    def test_week_a_three_and_week_b_five_supplements_have_valid_identities(self):
        for week,count in [('20260928',3),('20261005',5)]:
            with self.subTest(week=week):
                path=Path('manual_supplements/approved/weekly_'+week+'.json')
                items,data=load_supplements(path,snapshot_replay.sha256(path),data_week := ('2026-09-28' if week=='20260928' else WEEK),[])
                self.assertEqual(len(items),count)
                self.assertEqual(len({r['supplement_id'] for r in data['records']}),count)
                self.assertTrue(all(supplement_hash(r)==r['content_sha256'] for r in data['records']))

    def test_previous_four_week_b_records_and_approval_evidence_preserved(self):
        doc=json.loads(Path('manual_supplements/approved/weekly_20261005.json').read_text())
        self.assertEqual([r['content_sha256'] for r in doc['records'][:4]],[
            'dbce4282cfa367482be3123c3d244aeeb9eb5bab7a3e18a53ef56fe4baadaf12',
            '4cda880428db1bcddb83d4aeb727ac0d37b8f76cbfb445a3a925d8b42256c7b0',
            '2ebbbb2398db5d0bdbf38c6160274c8f5082f748c03114dc21b8e793b846c2d8',
            'd98b670fa35f3f62cb3cc0cf225dca3d4d4f75437b31919de34d00e6c7c1694b'])
        self.assertEqual(doc['approval'],{'reviewed_by':'6b6mdgnb6j-cpu','approved_at':'2026-10-13T09:17:52+08:00'})
        self.assertEqual(doc['revision_approval']['previous_file_sha256'],'589f896a84d9559ae697d3e686e370aaa413fadc63b8bc1726fe128845d7e9d4')
        self.assertEqual(doc['records'][4]['approval']['approved_at'],doc['revision_approval']['approved_at'])

    def test_duplicate_url_or_semantic_event_is_rejected(self):
        path=Path('manual_supplements/approved/weekly_20260928.json')
        items,_=load_supplements(path,snapshot_replay.sha256(path),'2026-09-28',[])
        for url in (items[0]['url'],'https://investor.cmegroup.com/alternate-official-page'):
            with self.subTest(url=url):
                duplicate=copy.deepcopy(items[0]);duplicate['url']=url
                with self.assertRaisesRegex(ManualSupplementError,'duplicate'):
                    load_supplements(path,snapshot_replay.sha256(path),'2026-09-28',[duplicate])

    def test_streamlit_reads_editorial_summary_without_altering_historical_fields(self):
        tree=ast.parse(Path('app.py').read_text())
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='localized_summary')
        data=json.loads(APPROVED.read_text())['records'][0]
        for language,expected in [('中文',FOMC_CN),('English',FOMC_EN)]:
            namespace={'current_language':lambda:language}
            exec(compile(ast.Module(body=[function],type_ignores=[]),'localized-summary','exec'),namespace)
            item={'summary_original':'','summary_en':'','summary_cn':'','editorial_summary':data}
            self.assertEqual(namespace['localized_summary'](item),expected)
            self.assertEqual(item['summary_original'],'')

    def test_approved_publish_current_main_warning_and_replacement_guards_remain(self):
        text=Path('.github/workflows/publish-weekly-approved.yml').read_text()
        for guard in ('Validate source generation run','Validate current main is not stale',
                      '--approve-warning','--replace-same-week','--archive-only-backfill'):
            self.assertIn(guard,text)
