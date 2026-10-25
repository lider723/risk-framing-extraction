# 按需查：流程、评分、版本和数据

不必先通读。本页是定位实现的索引，主要入口仍是README、错误案例和结果页。

## 1. 输入、输出与下游要求

文章是采样单位；风险主张是提取／后续编码单位；逐字片段是证据锚点。发言者是主张的来源，不能直接当成风险致因者或AI行动者角色。

输入JSONL每行一个对象，至少包含 `record_id`、`title`、`paragraph_numbered_article`。正文按行写 `[P001] ...`，标题由程序补为P000；段落不可重复。同原始输入格式，不需要把Gold送给模型。

输出为 `record_id` 与 `risk_units`，每单元包含 `unit_id`、`risk_claim_spans`、`necessary_context_spans`。每处证据是单段连续逐字引文。必要语境包括归属、潜在／实际、条件、反驳与有关治理回应，可以离核心句较远。后续仍阅读全文，但不能指望全文自动修复独立风险漏提或错误拆合。

**当前只优化提取，不启动下游编码。** [完整冻结手册](extraction_manual_frozen.md)未改；编码手册及历史编码Prompt仅作下游需求查阅。

## 2. 流程及代码地图

```text
全文 → Call1分块发现 → Call2同分块补漏 → 冻结候选ID
     → Call3局部确认 → 按请求扩展相邻段／全文 → 全文审阅后最终确认
     → 程序检查引文、映射和未解决项 → 导出风险单元
```

| 关注点 | 实际位置 |
| --- | --- |
| 标题／段落号、约800-token分块、整段保留、重叠一段 | `src/risk_units/prep.py` |
| Call1/2构造、候选合并和Call3轮次 | `src/risk_units/pipeline.py`：`extract_article`、`confirm_article` |
| 局部句、语境扩展、强制全文审阅后complete | `common.py`、`contracts.py`：`ContextController` |
| schema、逐字引文、唯一原文切片修复、双向映射 | `common.py`、`contracts.py` |
| 两阶段变体的检查与权威映射派生 | `two_stage.py`；消息格式见 `prompts/diagnostics/README.md` |
| 请求、响应模型核对、重试、修复、缓存、请求上限 | `pipeline.py`：`Client`、`verified_stage` |
| 严格一对一匹配和P/R/F1 | `scoring.py`；入口 `scripts/replay_scores.py` |
| 实验配置、面板ID、调用／token、逐字合规 | `reports/experiment_index.json` |

### 完整提取与诊断实验不是同一种运行

两轮诊断固定历史v5候选，从首轮就提供全文，状态complete，只测确认／拆合，不重做发现。分阶段方案先确认命题再归并，第一阶段拒绝项不会暗中由第二阶段恢复；未拆开的复合命题也不能靠程序伪造拆分救分。

本次可移植入口运行的是**历史完整v5流程**，不是把它冒充为两轮固定候选实验的逐字重演。诊断变体实际Prompt、schema、两阶段派生函数、逐篇评分／恢复关系均已提供；完整原始诊断请求仍在受限包。

## 3. 评分究竟怎么算

1. 既有语义复核为预测单元标记 `supported/context/unsupported/boundary` 和风险含义签名。判断依靠全文、AI—后果关系、归属及条件，不靠相同段落或相同字串。
2. 对每条原参考与意义相符的supported预测建边；最大一对一匹配得TP。每预测和每参考严格最多用一次；FP=预测数−TP，FN=参考数−TP。
3. P=TP/预测数，R=TP/参考数，F1=2TP/(预测数+参考数)。无有效分母返回null，不给空文章编出100%准确率。
4. 内容覆盖允许一条混合预测覆盖两条参考，但仍可能不能安全用于编码。重复、异质合并、无依据、边界、语境独立建项、严重归属／条件错误分别计数；FP不是“全是幻觉”。
5. 技术失败／部分完成不当空风险，也不直接当语义FN；主表比较共同成功ID，同时报告计划范围及不可交付文章。重复试次不混入主表。

`reports/scoring_replay.json`保存两轮全部计划文章的状态、原参考签名、逐单元既有判断、匿名复核ID、条件／单元恢复关系及原结果hash。没有重新判断、删除坏输出、改Gold或以脱敏文本重新算逐字率。程序可在不读取新闻的情况下重算配对与指标，但**不能凭这些签名独立验证语义判断是否正确**。

来源评分为同一助手的 `llm_assisted`，非独立人类盲评。语义标记不是下游变量Gold；内容覆盖不是实测的“下游编码不受影响率”。认知／学生技能的别名只用于覆盖和重复审计，不把原参考合并成更小分母。

## 4. 版本和运行参数

v5原始代码默认8月模型，历史11月wrapper仅替换模型；本仓库沿用 **gpt-4o-2024-11-20**，不退回8月、不偷偷换供应商。六份原消息和冻结手册字节未改，hash见来源索引。

| 条件 | 父版本与变化 |
| --- | --- |
| 第一轮D0／D1／D2 | D1原4合成例；D0移除4例；D2只替换2个复杂正例 |
| 第一轮D3 | D1改两阶段确认／归并，示例机械适配结构 |
| 第二轮V5／E0／S0 | 同期重跑的D1／D2／D3，不与上轮不同样本直接比F1 |
| 第二轮E／S／B | E只修E0示例字段；S只修S0阶段冲突；B只澄清V5纳入门槛 |

E0、S0与父版本对应，不重复再放一套权威模板。D0仅需移除v5 system中原4合成例。v6是更早历史对照，不是当前主线；历史共同成功54篇报告v5约59.0%、v6约52.2% F1，不和12篇诊断表直接比较。不再复制整套v6和两轮数千日志。

历史端点为 `https://api.vveai.com/v1`，temperature=0。第三方返回的模型名是元数据，不证明底层权重。可移植完整v5使用历史4次传输尝试、最多1次契约修复、120秒超时、Call1/2最多4096输出token、Call3最多16384、最多6轮语境审阅。完整v5只限制请求数，不具有第二轮独立实现的累计token预算。第一轮诊断为3次传输尝试／最多2次契约修复；第二轮为2次／1次，另有160请求、150万返回token及预留预算。这些是历史差异，未静默统一。

### 已验证的离线命令

从仓库根目录运行：

```sh
python3 scripts/offline_check.py
python3 scripts/replay_scores.py
python3 -m unittest discover -s tests -v
python3 scripts/audit_repo.py
python3 scripts/run_extraction.py
```

离线只需标准库；已用Python3.9.6核验，22项测试及两轮评分回放通过，含合成输入的模拟完整流程。最后一条默认不读key、不写文件、不发API。在线依赖在requirements里单列，核对现有环境为openai 2.48.0、tiktoken 0.14.0；本次没有安装依赖或实测在线调用。

拿到授权开发包后，可先预览：

```sh
python3 scripts/run_extraction.py --inputs local_only/development/articles.jsonl
```

缺文件明确报错，不联网补文、不用合成文冒充真实样本。只有研究者另行批准实际运行后，才添加 `--run --max-api-calls 明确上限`；key由 `OPENAI_API_KEY` 或 `LOCAL_FRAME_API_KEY` 环境变量提供，端点可由 `AI_RISK_BASE_URL` 显式指定；`.env.example`不自动加载。不读取原项目临时key文件。

输出只能在被忽略的 `local_only/` 子目录。缓存按请求hash核对；可移植manifest另锁定输入、六模板、schema、模型／端点、源码和语境上限。换配置使用新目录，不能混用历史缓存。在线首次加载tokenizer可能下载编码表；默认离线检查不会触发。

本次适配：提取原函数，改相对导入；凭据改ENV-only；原main对固定60篇及Gold路径的依赖改成显式输入；默认0次请求、输出限local_only；模型沿用11月wrapper。没有改Prompt、语义门槛、引文／映射契约、历史重试或修复逻辑。入口只经过离线与模拟测试，不声称产生了新实验或已验证的模型结果。

接口字段按[官方OpenAI Chat Completions说明](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)核对；仍保留历史调用方式，不迁移API或模型。官方说明不担保第三方兼容性。

## 5. 共享数据与追溯

共享：说明／手册、Prompt、代码、schema、合成示例、真实案例概述及最小模型判定片段、去引文评分和统计。受限本地：新闻全文、Gold引文、完整请求／响应、key、未用保留43篇及后续池；本次未读取保留数据。

若需复核全文，由研究者提供允许分享的开发子集，放 `local_only/development/`；原记录按 `examples/case_index.json` 和 `reports/scoring_replay.json` 的逻辑路径找，核对SHA-256。`round1_delivery/`、`round2_delivery/`、`project/`只是来源标签，不是自动搜索路径。没有原包只能复核已有判断的算分，不能冒称重新验证了原文或完整实验。

`source_manifest.json`记录来源、原hash、目标hash与转换。第一轮部分记录用规范化JSON对象hash，第二轮用文件字节hash；导出明确标注hash_kind，并补第一轮文件hash，不能混用。原项目及旧实验只读未改；不自动提交、推送或授予权限。作者、许可和新闻共享范围由研究者决定。
