# Production #43 内容质量专项修复

## 基线与边界

- GitHub 仓库：6b6mdgnb6j-cpu/DBG-weekly-intelligence。
- 检查时 main 和 Production #43 (`37731783243`) 均为 `c37006d8190fb19d29ada0f471f3d08d0b4b72f1`；目标周 2026-09-28 至 2026-10-04。
- 使用该次运行的 `weekly-report-review-2026-09-28` artifact（ID 11531265505），包含 51 条周报记录。
- 下载 ZIP SHA-256：`96ee9d8901f6641f9c3d11cebd33359eb82e1da66887b3dab6fa62edfd239bfe`。
- 原工作目录存在与本次无关的未提交修改，因此在 main 基线的独立 managed worktree 内完成修复，未覆盖原目录。
- registry-first 保持不变；仅替换已注册 SRC-037 的解析适配器，不新增来源、不改来源配置、QA 阈值、正式发布流程或人工覆盖顺序。没有触发 production 或发布。

## A. 翻译质量与 QA 漏检

### 根因

原运行工作流成功，但内容 QA 实际为 **WARNING**，并非所有内容正确。已有实体检查没有覆盖 IFC、EIOPA、Platts、PolicySteward；现有 glossary 的普通 term_translations 并不能提供这些语义错误的最终阻断保障。既有 material-term 检查用于最终审计，却未完整用于翻译候选和人工译文导入验证。原检查也没有按币种和数量级归一化比较金额。

| 原案例 | 确认的问题 | 通用修复 |
| --- | --- | --- |
| LCH collateral haircut | 剪发、附加、会员利抵押金，丢失抵押品/保证金含义 | 在抵押品/保证金上下文校验折扣或折减、抵押品及保证金术语 |
| LCH IFC | IFC 被写成国际货币基金组织；go-live 被写成截止日期 | IFC 与全称加入实体保护；拦截机构冲突及上线日/截止日混淆 |
| ICE options / Platts | 金融期权变成选项；Platts 变成板块 | 金融上下文要求期权；保护 Platts，接受普氏 |
| EIOPA | 欧盟能源署、泛化为欧盟监管局 | 保护缩写及全称，接受正确机构中文名，拦截已知冲突 |
| ISS STOXX PolicySteward | 产品名消失，变成普通“政策/政策管理服务” | 产品实体保护，禁止仅靠泛化译文通过 |
| IA £894 million | 标题变成 894 亿（正确为 8.94 亿英镑）；摘要遗漏 £1.8 billion 并把英镑写成“英” | Decimal 按基础币值比较币种、金额、数量级和出现次数；支持 million/billion、m/bn 等及万/亿换算 |

所有新增规则复用于候选校验、人工导入校验、最终 QA。错误旧缓存会经过候选校验，不会直接被当作有效译文使用。未硬编码本周金额或整篇译文，也没有自动猜测并改写金额。

人工译文仍按原身份和原文哈希优先覆盖。已有五条 approved overrides 在原产物上全部匹配（5 applied / 0 unmatched），未修改。既有错误人工译文也不会被机器偷偷改写，但最终 QA 会阻断并要求重新审核；优先级不等于免检。

## B. 芬兰金融监管局误收录

SRC-037 原来使用通用 article/list 解析器，遍历所有 `li`，从整个子树取日期和第一个链接。站点嵌套导航中，宏观审慎决定子链接含有 **30 September 2026**；该日期被赋给祖先 Financial market stability、Macroprudential 等栏目。详情解析又优先采用 list_date，因此没有证明日期属于当前页面。

原产物误收录五页：

1. `/en/financial-market-stability/`
2. `/en/financial-market-stability/macroprudential/`
3. `.../macroprudential-decisions-and-appendices/`
4. `.../macroprudential-decisions-2026/`
5. `.../macroprudential-decision-30-september-2026/`

最后一页是决定/附件索引，重复指向实际新闻，并非带可信发布日期的新闻正文。

修复只针对已注册 SRC-037：

- 列表仅解析真实 publication 列表 `ul.listing.pagelist > li` 的直接新闻链接及该行 time，排除导航。
- URL 必须属于本站按年份归档的 Press-release / News / Supervision-releases 正文路径。
- 详情必须在 article 内有带 Press release / News / Supervision release 标签的发布日期；忽略导航、子链接、列表借来的日期及通用修改日期。缺乏可信日期时丢弃并记录 `untrusted_publication_date`。
- 最终 QA 另行阻断旧产物中的栏目/索引路径，避免重放绕过解析。

真实页面提取结果：监管简化新闻为 **28 September 2026**；宏观审慎新闻为 **1 October 2026**，不是导航里的 30 September。离线采集集成测试保留这两篇新闻，宏观审慎决定仅保留新闻页一次。

## 修改文件

- `crawler/translator.py`：四个实体及必要全称的保护。
- `crawler/translation_quality.py`：金融术语、机构冲突及金额一致性阻断；统一校验入口。
- `crawler/adapters/fin_fsa.py`：新增 SRC-037 专用列表/日期解析。
- `crawler/adapters/__init__.py`：SRC-037 绑定专用适配器。
- `crawler/article_parser.py`：芬兰正文路径与发布日期验证。
- `qa_gate.py`：最终产物芬兰栏目页阻断。
- `tests/test_content_quality_release.py`：22 项专项测试。
- `tests/fixtures/content_quality/production43_translation_cases.json`：Run #43 六个目标案例原字段。
- `tests/fixtures/content_quality/fin_fsa_listing.html`：官方列表页面精简保留导航和真实列表。
- `tests/fixtures/content_quality/fin_fsa_news_32.html`、`fin_fsa_news_41.html`：对应两篇官方新闻的 article 子树。
- 本报告。

HTML fixtures 于本次审计读取官方原始页面后裁剪保留相关结构；它们不是 #43 保存的历史 HTML 快照。但用其旧解析器可以复现与 #43 一致的栏目标题和借用日期，且原产物直接确认五条误收录记录。没有将网页文本作为执行指令。

## 验证结果

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q`：**616 passed**，含原有 594 项与新增 22 项；无失败。
- `git diff --check`：通过。
- 新测试涵盖实际六例的标题及摘要、正确译法、非金融上下文、金额等值/错误/遗漏/重复、人工优先与不改写、最终 QA 阻断、导航日期误用、真实发布日期、跨周日期、旧索引拒绝、采集去重。
- 原 #43 全量产物应用现有人工覆盖后重放 QA：**WARNING → FAIL**。翻译检测 21 条 FAIL，涉及 7 条记录、13 个字段；另一个 FAIL 检查列出全部五个芬兰栏目/索引页。
- 六个指定案例全部被阻断；第七条是 Cboe 摘要同类 `options → 选项` 错误，由可复用规则自然检出。未扩展修复 Cboe 来源或为其豁免检查。
- unittest 日志中的模拟 `PUBLISH BLOCKED / QA report missing` 属既有发布测试；本次未实际调用生产发布。

## 残余风险与重跑建议

**建议合入修复后重新执行 2026-09-28 production，但不能直接重发旧产物。** 新运行仍须走原人工审核与发布流程；解决新 QA 列出的译文问题后才可评估正式发布。未放宽任何检查。

本次验证了采集/翻译校验/人工覆盖/最终 QA 的代码和离线集成测试，未运行真实 NLLB 全周再生成，不能承诺模型会自行产出全部合格译文。规则确保已知确定性错误不会无声通过，必要时进入现有人工审核。未补写本周专用人工译文。

金额检查覆盖明确币种与阿拉伯数字、常见英中数量级，不等于通用数值语义验证；百分比、纯中文数词、未覆盖币种仍有残余风险。严格匹配金额及出现次数，压缩摘要省略金额也会被阻断，需人工恢复信息。

金融语义规则及实体表不能识别所有未知误译。芬兰站点若调整路径、列表结构或发布日期标签，将保守拒收，需从诊断中识别后再调整；未扩大本轮到其他来源，也未引入跨来源事件语义去重。


## 最终合并前复核

复核时远端 main 仍为上述基线。没有发现或纳入本任务之外的 worktree 修改。

- 收窄金融 options 判定至产品/交易语法，避免仅因同段落出现 equity/electricity/index 就要求“期权”；加入普通交付选项、数据导出选项、明确支付选项及期权/普通选项混用测试。
- IFC 的实体保护、规范化及最终检查共用上下文判断：完整机构名或明确金融上下文才启用；不同全称（Industry Foundation Classes、International Finance/Financial Centre/Center）不当作国际金融公司，裸缩写不猜测。
- 补测 million/billion/百万/亿、币种前后位置、缩写和精确等值小数；严重数量级、币种和遗漏错误仍阻断。
- 芬兰正文发布日期允许 article header 内带标签的 inline time，仍不从导航/相关链接/通用日期取值；三个现有 publication 路径类型均经过测试。未增加来源。
- 新增真实 render_report + run_qa 的临时目录集成测试（仅采集和人工覆盖加载被替换为内存 fixture），验证 HTML、保存的 JSON 与 QA 使用同一份覆盖后文本。正确人工译文替换错误机器值；错误人工值仍阻断。未修改生产编排。
- 最终验证：616 tests passed；`python3 -m compileall -q .` 通过（缓存置于临时目录）；`git diff --check` 通过。
- 再次重放 #43：5 条人工覆盖全部匹配；QA 仍 FAIL，21 条翻译阻断涉及 7 条记录，另有五个芬兰栏目页阻断。原六个目标案例没有因误报修正而获得豁免。

代码层面建议合并；这不构成本周产物的发布批准。真实全周模型再生成与人工审核仍待合并后的受控重跑。

复核中另确认既有标题动作规则会把形容词 clear 误当作清算动词（如 Clear options for electricity payments）。本次期权规则不再误判该句，但未扩大修改既有动作规则，也未给最终 QA 添加豁免；此类边界文本仍可能需要人工处理。
