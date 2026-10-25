# AI Risk Framing：先解决风险单元提取

研究新闻如何呈现AI风险、行动者和责任。当前只优化**风险单元提取**，后续变量编码暂缓；v5是开发基线，还没有可正式升级的版本。

我们提取文章支持的“AI相关因素 → 具体负面后果”主张，不是逐句分类。例：一句话同时说岗位消失、战争失控，应拆成两个风险；同一风险的概括、实例和治理回应应归到一起。锚点不必和人工摘句相同，后续仍阅读全文，但不能丢掉独立风险或弄混归属、条件。

## 同学先看三个文件（约10分钟）

1. **本页**：知道任务、目录和希望你帮什么。
2. [典型错误](docs/ERROR_CASES.md)：先看前六例，理解模型究竟错在哪。
3. [两轮结果与结论](docs/STATUS_2026-10-25.md)：哪些方法试过、为什么不能只看F1选版本。

希望你先提出**一项最值得改的地方、原因和最小验证办法**，不必通读所有代码、不必先跑实验。完整边界见 [冻结手册](docs/extraction_manual_frozen.md)，背景补充见 [协作简介](docs/COLLABORATOR_BRIEF.md)。

## 精简目录

```text
ai-risk-framing/
├── README.md                ← 从这里开始
├── docs/
│   ├── ERROR_CASES.md       ← 真实问题和判断分歧
│   ├── STATUS_2026-10-25.md ← 两轮结论
│   └── TECHNICAL_GUIDE.md   ← 需查代码／评分时再看
├── prompts/v5_baseline/     ← 六份真实基线消息
├── prompts/diagnostics/     ← 未通过升级的变体与差异
├── src/risk_units/          ← 历史流程、契约、拆合、评分函数
├── scripts/                 ← 离线检查、评分回放、显式运行入口
├── examples/                ← 合成例＋真实案例索引（无新闻全文）
├── reports/                 ← 逐篇判断、版本、配置与汇总
├── schemas/                 ← 输出结构
└── tests/                   ← 必要的离线检查
```

这是阅读导航，未展开辅助文件；不要求按文件夹顺序逐个阅读。完整来源和hash见 [source_manifest.json](source_manifest.json)。下游编码手册／历史Prompt仅供查阅，不是本轮工作项。

## 可以离线复核，不需要key

在本目录运行；离线命令仅依赖Python标准库：

```sh
python3 scripts/offline_check.py
python3 scripts/replay_scores.py
python3 -m unittest discover -s tests -v
python3 scripts/audit_repo.py
```

这些命令已离线验证。评分回放重算**已有LLM辅助语义判断**的一对一匹配、覆盖和指标，不是程序独立判断了风险，也不代表下游编码准确率。

真实调用入口为 `scripts/run_extraction.py`，默认不读key、不发请求、不写结果。运行条件及迁移边界见 [技术说明](docs/TECHNICAL_GUIDE.md)；未经研究者确认，不启用 `--run`。

## 分享边界

只分享本目录，建议先建私有仓库。新闻全文、Gold原文引文、完整请求／响应、密钥和保留集不在共享包内；案例是自写概述、最小模型判定片段和来源索引。私有仓库不等于取得新闻数据发布许可。

仓库整理阶段没有改Gold或原实验，也没有新模型API调用。GitHub提交、推送和可见性由研究者另行授权；作者、许可证和新闻数据分享范围仍由研究者决定，不自动选开源许可。
