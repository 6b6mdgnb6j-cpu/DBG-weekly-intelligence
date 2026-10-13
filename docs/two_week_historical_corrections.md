# Two-week Historical Content Corrections and Republish Runbook

## Scope and Approval

Base main: `24d32f3c4ca7aa3f7887d6ef39b7a8a8f06d20ce`. This PR prepares reviewed replacements; it does NOT publish or authorize source-health WARNINGs.

Human reviewer: `6b6mdgnb6j-cpu` (verified authenticated owner). New content approval recorded at `2026-10-13T12:03:53+08:00`. The subsequent QA recognition approvals do not change the approved FOMC or DTCC content.

Baseline evidence: real snapshot replay with pre-change approvals reproduced all 45 and 43 published item dictionaries exactly. Sources of truth were the two published archives fetched from that main SHA, not old checkout versions. Original ZIPs were verified before processing and are unchanged.

## Implementation

- Snapshot-only, default-disabled `apply_editorial_summaries` selection and required `editorial_summary_sha256`; reject live mode, missing explicit week, drafts, missing approval, wrong identities/hashes and duplicates. No network/model fallback.
- Apply translations, then approved existing-item summaries, then existing plus new article supplements, then normal rendering/Highlights and QA. No global ranking/relevance/mapping changes.
- FOMC keeps its historical `summary`, `summary_original`, `summary_en`, `summary_cn` and language fields empty and unchanged. Approved human English/Chinese live in `editorial_summary`, with source evidence, approval, record identity/hash, basis and approved-file SHA. HTML and Streamlit only add reading support for this approved field.
- Each editorial pair is evaluated by the existing translation-quality engine at ingestion AND bundle validation; original/source translation QA is also recomputed normally. Any editorial FAIL/WARNING blocks loading. No QA thresholds/severities are lowered.
- Manifest binds the exact approved summary document, unchanged original-item digest and summary provenance. Validators reconstruct and compare enriched original items; updating ordinary output hashes cannot hide modified editorial text. Source-status bytes remain unchanged.
- Supplement system reused. Week B's original four record dictionaries, identities, hashes and old document approval remain exact. New CFTC record has its own approval; `revision_approval` records the new event and binds the previous approved-file SHA rather than rewriting old approval history.
- QA fix 1: add only `上调` to ACTION_DIRECTION_RULES increase signals. No generic “调整”/“变化”, no decrease change.
- QA fix 2: in title increase-anchor inspection only, remove the compound `growth and scale` when Chinese has the complete `规模化发展`. Independent increase/rise/raise/record/growth propositions remain in the checked title; all other anchors and numeric/entity/legal checks remain active. No company/URL/source/week exception and no new global growth synonym.

## Exact Approved-File Digests

|File|SHA-256|
|---|---|
|manual_translations/approved/weekly_20260928.json|`e31c7d9ba4df560d6655f38e4381e8f408f6075c94da2f886ae84a31e310ddf0`|
|manual_supplements/approved/weekly_20260928.json|`a1fa3e8c3990f92ec7d04e8731074f5a03317a770f576f84d0364951292d0e54`|
|manual_translations/approved/weekly_20261005.json (unchanged)|`be848dd94341bb1fd787a2e03ea213ac46a64d7a86eba983b3d3b1f35610b1cd`|
|manual_supplements/approved/weekly_20261005.json|`ec566efae4efb5dcb205a5f4e983796df3acae863fee1d363f1722d36c658500`|
|manual_editorial_summaries/approved/weekly_20261005.json|`7d93ec65792e4bebc2695bf016318c6824c4e526a1c36954f30a8424cb823e3a`|

## Existing Week A Field Changes

Only these four fields plus their existing manual-translation provenance may differ. The three new overrides bring 21 to 24; ICE updates one existing override without changing its original hash/identity or creating a duplicate. All 20 unrelated old override records remain identical (permanent frozen digest regression).

### summary_cn: https://www.eurex.com/ex-en/find/news-center/news/building-liquidity-in-europes-volatility-markets-5594946

- Before: 欧洲波动性市场正在变得越来越流动,
- Approved replacement: 欧洲波动性市场的流动性不断增强，市场参与者可利用日益丰富的产品开展波动性交易策略。
- Stable item/field ID: `0aad741a583a764797cbce912c0386fc89859d6cabf9be6e018a5309f0d189d0`
- Original English SHA-256: `0ead8d1cfcc87542e6471f1e6684cb0eca700286de5bbff67466d8a1aaa19c98`
- Approval: 6b6mdgnb6j-cpu, 2026-10-13T12:03:53+08:00. Original English, date, source, URL, category and business mapping preserved.

### summary_cn: https://www.sec.gov/newsroom/press-releases/2026-100-sec-proposal-would-address-how-investment-advisers-funds-can-custody-crypto-assets-under-federal

- Before: SEC今天提出了新的规则和修正案, 已注册的投资顾问和监管基金的加密资产保管,即 已注册的投资公司和企业...
- Approved replacement: 美国证券交易委员会（SEC）提出新规则及修订案，为注册投资顾问及受监管基金的加密资产托管提供专门框架。
- Stable item/field ID: `80eaff24416a7451161ab1f4425aeb8741dc6c8c7d60826a8d0d1d8e6c1e9a95`
- Original English SHA-256: `da6043874b3f7c9cdb0be27151fbd4803f7361e854ebe108e4c34fe810db5ebc`
- Approval: 6b6mdgnb6j-cpu, 2026-10-13T12:03:53+08:00. Original English, date, source, URL, category and business mapping preserved.

### title_cn: https://ir.cboe.com/news/news-details/2026/Cboe-and-SP-Dow-Jones-Indices-Sign-25-Year-Extension-of-Exclusive-Licensing-Agreement-Through-2051/default.aspx

- Before: Cboe和S&P道斯指数签署了25年延长独家许可协议,到2051年
- Approved replacement: Cboe与标普道琼斯指数将独家许可协议延长25年，合作延续至2051年
- Stable item/field ID: `53fbbcd7204ce41ba4c7c7afdd3491eeb2061ca9d9d0e1c870a7ee371ea5115d`
- Original English SHA-256: `dc7fafbbea7cf4d899467a0f958e1a75b6cecc21baec9a96b3717c8db09cb958`
- Approval: 6b6mdgnb6j-cpu, 2026-10-13T12:03:53+08:00. Original English, date, source, URL, category and business mapping preserved.

### summary_cn: https://ir.theice.com/press/news-details/2026/ICE-Launches-New-JKM-LNG-Platts-Options-LNG-Balmo-Freight-Futures-and-U-K--Electricity-Options-in-an-Expansion-of-Global-Natural-Gas-and-Power-Markets/default.aspx

- Before: 更多能源合约纳入 ICE Risk Model 2。

ICE 的 JKM LNG（Platts）是东北亚天然气的基准价格。

洲际交易所（Intercontinental Exchange, Inc.，NYSE: ICE）是全球领先的金融市场技术与数据提供商之一，为全球资本市场提供支持，并运营着全球规模最大、流动性最强的能源衍生品交易及清算市场。该公司今日宣布推出新的 JKM LNG（Platts）期权、LNG Balmo（月内剩余期间）运费期货以及英国基荷电力期权，以拓展 ICE 的全球天然气及电力市场。新的 JKM 期权（JKZ）是对 ICE 现有 JKM 平均价格期权的补充，其结算方式与 ICE 的 TTF 期权类似，在月底以标的期货的结算价进行结算。新期权使客户能够管理某一特定时点的亚洲天然气价格风险，与用于管理月内累积风险敞口的平均价格期权相配合。此外，ICE……
- Approved replacement: ICE宣布推出新的JKM LNG（Platts）期权、LNG Balmo运费期货及英国基荷电力期权，拓展天然气及电力衍生品业务。其中，新JKM期权（JKZ）与现有月均价期权形成互补，按月末标的期货结算价结算，为市场参与者提供亚洲天然气价格风险管理工具。
- Stable item/field ID: `983c64cfedca57ecdd1d95afc6b29747b9f4104d26a6e33e56e4f95afc29faa2`
- Original English SHA-256: `77c1f6f830073b2f7a331d5f35b0b1bf9c38a606350fa460bf3de1d477be3b76`
- Approval: 6b6mdgnb6j-cpu, 2026-10-13T12:03:53+08:00. Original English, date, source, URL, category and business mapping preserved.

## FOMC Editorial Summary

Source: SRC-011 / 联邦储备系统. Published date 2026-10-07; meeting date 2026-09-15/16 (not weekly-filter dates).

Evidence: [release](https://www.federalreserve.gov/newsevents/pressreleases/monetary20261007a.htm), [full official minutes](https://www.federalreserve.gov/monetarypolicy/fomcminutes20260916.htm). Full minutes independently reviewed: policy-action section and 12-0 vote support 25 bp increase to 3.75–4.00%; participants' outlook supports another likely increase by year-end with data dependence. Approval wording unchanged byte-for-byte.

English: The Federal Reserve released the minutes of its September 15–16 FOMC meeting on October 7. The Committee unanimously raised the federal funds rate target range by 25 basis points to 3.75–4.00%, citing elevated inflation and resilient economic activity. Most participants considered another rate increase by year-end likely appropriate, while emphasizing that future decisions would depend on incoming economic data.

Chinese: 美联储于10月7日公布9月15日至16日FOMC会议纪要。纪要显示，委员会一致同意将联邦基金利率目标区间上调25个基点至3.75%—4.00%，认为通胀仍然偏高，而经济活动保持稳健。多数与会者认为年底前可能还需进一步加息，但强调未来政策决定仍将取决于后续经济数据。

Article identity: `1c71278375032e12738e384b10fa3a3c1d88429e529b4239b8ba22c8067e6fec`.
Original title hash: `19bf593907ffcb36bf0af77df07aba4b0d3207f3528f238cebd6c7d6864d2340`.
Original summary hash (empty string): `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
Summary identity: `502c146012fb90794aa929fb9493b39574d7023d091de130ff15553c7db09b93`.
Record hash: `c9ffc4a44e5bb53275a5f8530673524d1619eedd8c4577a36c45be629d3807ea`.
Origin: `manual_editorial_summary`; basis: `human_authored_summary_of_official_evidence`.

## Approved Article Additions

### 20260928 / SRC-149 / 2026-10-02

- Source: 芝加哥商品交易所集团; official URL: https://investor.cmegroup.com/news-releases/news-release-details/cme-group-reports-record-average-daily-volume-september-and-q3
- English title: CME Group Reports Record Average Daily Volume for September and Q3, Driven by Growth Across Asset Classes
- Chinese title: CME Group公布9月及第三季度创纪录日均成交量，各资产类别推动增长
- English summary: CME Group reported September ADV of 31.8 million contracts, up 22% year over year, and Q3 ADV of 29.4 million, up 16%. September interest-rate ADV reached 16.2 million contracts, up 22%.
- Chinese summary: CME Group公布9月日均成交量达3180万份合约，同比增长22%；第三季度达2940万份，同比增长16%。9月利率产品日均成交量达1620万份合约，同比增长22%。
- Relevance: Eurex竞争、全球衍生品及利率市场规模。区别于10/08国际ADV新闻，但Q3全球数字重叠，编辑需避免重复强调。
- Identity: `9b3042ef3d80a716845e263cb895fd6dd855e4aa0f52e0da9a609a27ebb2bf44`; record hash: `73613a12c56875a6c5cb0b2e7d491400b529ee5fedb5635d10e1c7aeb24d3da8`.
- Explicit approval: 6b6mdgnb6j-cpu, 2026-10-13T12:03:53+08:00. Evidence: official release review in record source_verification.
- Duplicate guard: official/canonical URL and same-source date/title/summary similarity checked against the original reviewed items and additions. Four missing events remain distinct; no articles are inserted twice.

### 20260928 / SRC-184 / 2026-09-28

- Source: DTCC; official URL: https://www.dtcc.com/press-releases/2026/dtcc-and-icapital-collaborate-to-advance-private-market-infrastructure
- English title: DTCC and iCapital Collaborate to Advance Private Market Infrastructure, Expand Access and Support the Industry’s Next Phase of Growth and Scale
- Chinese title: DTCC与iCapital合作推进私募市场基础设施，扩大准入并支持规模化发展
- English summary: DTCC and iCapital announced a collaboration connecting private-market infrastructure and investment workflows. DTCC also made a strategic investment in iCapital. Initial plans include further integration of DTCC's Alternative Investment Product with iCapital's platform.
- Chinese summary: DTCC与iCapital宣布合作，连接私募市场基础设施与投资流程；DTCC同时对iCapital作出战略投资。双方初期计划进一步整合DTCC的Alternative Investment Product（AIP）与iCapital平台。
- Relevance: Clearstream及基金服务竞争、私募市场交易后基础设施。投资金额未披露，不补数字。
- Identity: `c2be4775ea0c480cc57a254820884cc78ffd4dc51254c0dd1b8aaa12d28cff9b`; record hash: `ae5df41b41617cfe740eb5d8fdb1ca56f376906831fe4748e48e1c1d658d395b`.
- Explicit approval: 6b6mdgnb6j-cpu, 2026-10-13T12:03:53+08:00. Evidence: official release review in record source_verification.
- Duplicate guard: official/canonical URL and same-source date/title/summary similarity checked against the original reviewed items and additions. Four missing events remain distinct; no articles are inserted twice.

### 20260928 / SRC-013 / 2026-10-01

- Source: 商品期货交易委员会; official URL: https://www.cftc.gov/PressRoom/PressReleases/9306-26
- English title: CFTC Staff Extends Brexit-Related No-Action Positions
- Chinese title: CFTC工作人员延长英国脱欧相关不采取执法行动安排
- English summary: CFTC staff extended temporary Brexit-related no-action positions to maintain regulatory certainty for UK-US derivatives trading and clearing while relevant UK comparability determinations and exemptions are assessed.
- Chinese summary: CFTC工作人员延长英国脱欧相关临时不采取执法行动安排，在评估英国相关等效性认定及豁免期间，维持英美衍生品交易和清算的监管确定性。
- Relevance: 跨境衍生品交易与清算监管连续性；不是永久规则或委员会正式豁免。
- Identity: `05b3b12ae7ee2463eb453e0f479e73d2102eab1e9ad347707596ff87f555a9e5`; record hash: `975e3d30da5aa811e2acf8e5cd78580c2f4a74b5bf92e4e39524845b27a51013`.
- Explicit approval: 6b6mdgnb6j-cpu, 2026-10-13T12:03:53+08:00. Evidence: official release review in record source_verification.
- Duplicate guard: official/canonical URL and same-source date/title/summary similarity checked against the original reviewed items and additions. Four missing events remain distinct; no articles are inserted twice.

### 20261005 / SRC-013 / 2026-10-05

- Source: 商品期货交易委员会; official URL: https://www.cftc.gov/PressRoom/PressReleases/9308-26
- English title: CFTC Issues No-Action Letter for DCMs Regarding Converting Existing Perpetual-Style Broad-Based Security Index Futures into True Perpetual Futures
- Chinese title: CFTC就DCM将现有永续型宽基证券指数期货转换为真正永续期货发出不采取执法行动函
- English summary: CFTC staff offered conditional no-action relief for designated contract markets converting existing perpetual-style broad-based security index futures into true perpetual futures by removing expiration dates. Customer protections and regulatory filings are required; the relief expires October 20, 2026.
- Chinese summary: CFTC工作人员为指定合约市场（DCM）有条件地提供不采取执法行动安排，允许通过取消到期日，将现有永续型宽基证券指数期货转为真正永续期货。转换须满足客户保护及监管申报要求；该安排于2026年10月20日到期。
- Relevance: 衍生品合约结构、交易场所规则及客户保护；非单一执法案件、非永久许可、非加密币期货。
- Identity: `830d41de47ae110c515a87706b4cf8afaf181e3cf819685faf6d452d55ce8959`; record hash: `69496cdfa5fed22dbbfafbdb0219d89b6d6b2c1e5d40009260431f48e40b6842`.
- Explicit approval: 6b6mdgnb6j-cpu, 2026-10-13T12:03:53+08:00. Evidence: official release review in record source_verification.
- Duplicate guard: official/canonical URL and same-source date/title/summary similarity checked against the original reviewed items and additions. Four missing events remain distinct; no articles are inserted twice.

Week B previous four records preserve original approval 2026-10-13T09:17:52+08:00; hashes:

- SRC-150 / ae1cd624d4a66283fb09b464d264d549574e71c619535a1bd83797de5944174f: dbce4282cfa367482be3123c3d244aeeb9eb5bab7a3e18a53ef56fe4baadaf12
- SRC-150 / b5d1ce4d932f8172059f94921cb3a39ee0f63264e8e6f553e1d29abfed786f39: 4cda880428db1bcddb83d4aeb727ac0d37b8f76cbfb445a3a925d8b42256c7b0
- SRC-149 / b12be5569d7307c0c3b6766cf66bad19741f68b8d7b930da99ff886f0db53512: 2ebbbb2398db5d0bdbf38c6160274c8f5082f748c03114dc21b8e793b846c2d8
- SRC-186 / afcfe3f52e368259e260457b5f18f648c32b390bb823a118f1171a5cc7bb9c60: d98b670fa35f3f62cb3cc0cf225dca3d4d4f75437b31919de34d00e6c7c1694b

## Real Offline Acceptance

|Week|Baseline → candidate|Overrides applied/absent/conflicts/ambiguous|Supplements|Summaries|Highlights|Translation FAIL/WARNING|Overall blocking|
|---|---|---|---:|---:|---:|---|---:|
|2026-09-28|45 → 48|24/0/0/0|3|0|5|0/0|0|
|2026-10-05|43 → 44|57/0/0/0|5 (4 old + 1 new)|1|5|0/0|0|

All previous items preserve identity, English originals, ordering and unrelated values. Week A first45 differ only at approved four fields/manual provenance; Week B first43 differ only by FOMC editorial_summary. IOSCO title/date remain unchanged. Source-status files match original ZIP bytes; existing Week B four supplements remain exact; approved texts and ZIPs are immutable.

Source warnings are NOT suppressed. Overall status remains WARNING in both weeks, with the same 2 source-warning categories:

- A: CFTC blocked, AMF date_parse_failed, CCP Global date_parse_failed, DTCC no_candidates; AMF retry hotspot12/35,429.
- B: CCP Global date_parse_failed, ICE network_error, DTCC no_candidates, MSCI blocked; AMF retry hotspot19/35,429.

Existing-highlight selection runs normally, no forced scores or fixed titles. Bilingual artifact, manifest and bundle validators pass. Original collection run/SHA/digest remains separate from candidate generation SHA and runID. Local acceptance uses run ID0 explicitly as offline, never as a real GitHub Production ID.

Tests: new focused module45 passed, combined translation/editorial/snapshot/automation suite411 passed, full discovery715 passed (670 baseline+45 new; no excluded files, including test_content_quality_release). Compileall crawler/tests/scripts/root Python passed; all workflow YAML parsed; git diff --check passed. HTML summary language selection executed with Node and Streamlit function tested independently without loading UI/network. Existing publish replacement/current-main/manual-WARNING tests remain in the full suite.

## Exact Human-Executed Deployment Sequence (NOT executed)

After review/merge, use `weekly-report-production.yml` on current main. Both reports already exist, so replacement is explicit. WARNING approval is a NEW separate human decision, not covered by this content approval.

### Step A: Generate Older Week

```yaml
week_start: 2026-09-28
generation_mode: snapshot
snapshot_artifact_id: 11543067970
snapshot_artifact_name: weekly-report-debug-37759948823-1
snapshot_sha256: 73225821087fd876c447800c21b3f931e9dcf9597a58f45bf6f0067f905e2608
collection_run_id: 37759948823
collection_sha: f64d909db3682d738fe67520991ba25ec32dc721
apply_editorial_supplements: true
supplement_sha256: a1fa3e8c3990f92ec7d04e8731074f5a03317a770f576f84d0364951292d0e54
apply_editorial_summaries: false
editorial_summary_sha256: ""
```

Review the NEW successful A run artifact, including 48 items/5 highlights/QA/source warnings/hashes. If explicitly approved, dispatch existing `publish-weekly-approved.yml`:

```yaml
source_run_id: <NEW_SUCCESSFUL_A_PRODUCTION_RUN_ID>
week_start: 2026-09-28
approve_warning: <true ONLY after separate explicit human WARNING approval>
replace_same_week: true
archive_only_backfill: true
```

Verified existing publish semantics: both replacement and archive-only flags required for an existing older archive. Only weekly_20260928 archive changes; latest must still point to Week B. No use of original failed collection run as publish source.

### Step B: Generate Again on New Main

A publish commits to main. Verify main AFTER that commit. Do NOT reuse B artifact generated before A publication: current-main guard correctly rejects it as stale. Only now dispatch new B Production:

```yaml
week_start: 2026-10-05
generation_mode: snapshot
snapshot_artifact_id: 11724736313
snapshot_artifact_name: weekly-report-debug-38196887790-1
snapshot_sha256: 27045723754fd37a611d436c95c74120a3940c9588a9b34317969b5b6f431eec
collection_run_id: 38196887790
collection_sha: a2b550e8b903a339c74eb8302148cb94637aabb3
apply_editorial_supplements: true
supplement_sha256: ec566efae4efb5dcb205a5f4e983796df3acae863fee1d363f1722d36c658500
apply_editorial_summaries: true
editorial_summary_sha256: 7d93ec65792e4bebc2695bf016318c6824c4e526a1c36954f30a8424cb823e3a
```

Review NEW B run and explicitly approve retained WARNINGs before dispatching existing Approved Publish:

```yaml
source_run_id: <NEW_SUCCESSFUL_B_PRODUCTION_RUN_ID>
week_start: 2026-10-05
approve_warning: <true ONLY after separate explicit human WARNING approval>
replace_same_week: true
archive_only_backfill: false
```

This is valid only while latest is still Week B. If latest has advanced, STOP and re-review the plan (B would also need archive-only mode). Verify both archives and latest after human execution. Approved Publish workflow is byte-for-byte unchanged: successful Production on main, exact current-main SHA, full bundle integrity, explicit WARNING/replacement guards, commit race guard remain active.

## Expiry and Unresolved Risks

GitHub artifacts freshly checked available:

- A11543067970 expires 2026-10-15 18:28:44 Asia/Shanghai.
- B11724736313 expires 2026-10-19 11:04:40 Asia/Shanghai.

Verified local originals are in .local/content-quality-audit/snapshots of the user's actual repository. Local copies do NOT automatically substitute for expired GitHub artifacts; existing workflow rejects expiry. If A expires before review/merge/dispatch, STOP and separately approve a provenance-preserving input arrangement; do not fabricate run/artifact IDs or weaken download checks.

IOSCO publication-date/title parsing remains unresolved and unchanged. Source adapters are not repaired by these editorial additions. Current content approval is not publication/WARNING approval. No generated outputs, raw ZIPs, temporary validation scripts or unrelated dirty work are included in this PR.

No Production/Approved Publish triggered, no live collection/NLLB, no registry/relevance/ranking/mapping changes, no published file modifications, no merge. STOP after opening this PR and await human review.
