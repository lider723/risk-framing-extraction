# 这些是失败／诊断条件，不是待选“最新最佳Prompt”

- E0是上轮D2；E只修两个复杂正例里8条候选的16个proposition/reason字段。Call1/2和Call3 user均复用v5_baseline。
- S0是上轮D3；S仅清理Stage1/2的阶段操作冲突。两阶段schema和中间结构保持不变；user消息格式见下方。
- B以v5为父版，仅增加既有纳入门槛的执行澄清；Call1/2及Call3 user复用v5_baseline。
- 原4个v5合成教学例保留在v5实际system消息；E0/E的两个复杂正例不是来自真实语料。
- v6不是本轮基线，因此没有把“编号更高”等同于“更好”塞入此包。

E直接对照E0，S直接对照S0，B直接对照v5；E/S对v5是辅助比较，不能把整个流程差异当作单项改动的效果。

Stage1 user原构建格式：

```text
RECORD_ID: {record_id}
CONTEXT_REVIEW_STATUS: complete
CANDIDATES:
{候选及同段前后句}
COMPLETE ORIGINAL ARTICLE:
{完整带段落号原文}
```

Stage2 user原构建格式：

```text
RECORD_ID: {record_id}
CONFIRMED PROPOSITIONS:
{仅Stage1已确认主张的JSON，保留candidate_id与proposition_id}
COMPLETE ORIGINAL ARTICLE:
{完整带段落号原文}
```

程序不能把Stage1拒绝项偷偷恢复，或把异质复合ID在Stage2静默拆开救分。`src/risk_units/two_stage.py`保留原关系校验与派生函数；结构校验仍不能替代语义拆分判断。
