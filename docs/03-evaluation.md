# 测试预期、实际结果、失败与限制

环境为 Windows / Python 3.12.3。离线复现实际执行 CLI、检查退出码、保存状态和费用账本，然后运行单元测试；报告见 [test-results.txt](../examples/test-results.txt) 与 [offline-validation.json](../examples/offline-validation.json)。30 项测试通过；13 个离线执行场景覆盖五项必验和失败续跑加分项。结构核查结果见 [submission-check.json](../examples/submission-check.json)。

## 必验场景与证据

| 验收点 | 预期与实际结果 | 输入 | 实际输出 | 独立 Trace |
| --- | --- | --- | --- | --- |
| 正常完成 | premium 完成并保存，总费用 12，模拟耗时 8 分钟 | [normal.input](../examples/normal.input.json) | [normal.output](../examples/normal.output.json) | [normal.trace](../examples/normal.trace.json) |
| 缺预算 | needs_information，列明 budget，无模型调用、无工具费用 | [missing-budget.input](../examples/missing-budget.input.json) | [missing-budget.output](../examples/missing-budget.output.json) | [missing-budget.trace](../examples/missing-budget.trace.json) |
| 缺截止时间 | needs_information，列明 deadline，不擅自补值 | [missing-deadline.input](../examples/missing-deadline.input.json) | [missing-deadline.output](../examples/missing-deadline.output.json) | [missing-deadline.trace](../examples/missing-deadline.trace.json) |
| 工具失败 | 全部候选生成失败，incomplete/tool_failure，费用 0，保留检索结果 | [tool-failure.input](../examples/tool-failure.input.json) | [tool-failure.output](../examples/tool-failure.output.json) | [tool-failure.trace](../examples/tool-failure.trace.json) |
| 超预算重规划 | 预算 10，premium 估算 12 不可行，改选 lean 并以费用 8 完成 | [over-budget.input](../examples/over-budget.input.json) | [over-budget.output](../examples/over-budget.output.json) | [over-budget.trace](../examples/over-budget.trace.json) |
| 重复执行 | 同一方案 ID、一份方案、费用仍为 12、没有新增工具执行事件 | [duplicate.input](../examples/duplicate.input.json) | [duplicate.output](../examples/duplicate.output.json) | [duplicate.trace](../examples/duplicate.trace.json) |

正常、信息不足、工具失败三类均提供输入、实际输出与运行记录，另外补齐预算超限和重复执行。输入校验与恢复已完成任务的记录由 runtime 标识，不冒充模型动作。其余离线策略标记为 mock，仅用于证明流程与校验。

## 扩展与对抗验证

- [no-feasible.output](../examples/no-feasible.output.json)：预算 5，最低费用 6，返回预算缺口 1，无保存。
- [deadline.output](../examples/deadline.output.json)：截止 09:05，premium 预计 09:08，改 lean 并恰好于 09:05 完成。
- [deadline-failure.output](../examples/deadline-failure.output.json)：截止 09:03，最快预计 09:04，返回 1 分钟缺口，不产生付费步骤。
- [transient-failure.output](../examples/transient-failure.output.json)：离线策略观察 premium 一次失败后换 lean，保留检索，费用 8，耗时 6 分钟。
- [save-failure.output](../examples/save-failure.output.json)：保存失败，方案不存在，已生成脚本与已花费用 10 均保留，不虚报费用 12 或保存成功。
- [resume-before.output](../examples/resume-before.output.json)、[resume.output](../examples/resume.output.json)：第一次限制 3 步，生成失败后停止；第二次同请求、同数据库恢复，只重新生成和保存，检索仅成功执行一次，总费用 12。

单元测试还检查负费用不能变成预算退款、时区与预算类型校验、截止早于起点、越过步骤依赖、未估算就生成、切换候选不退还已花费用、并发执行同一步只收费一次、SQLite 保存失败回滚、模型修改预算被拒绝、完成后不能继续花钱、提前结束和步数上限。成功步骤在 SQLite 中持久化，失败尝试保留于 tool_results；续跑成功更新最新步骤状态，不覆盖历史失败事件。

## 真实模型路径

2026 年 11 月 11 日（Asia/Shanghai），通过用户配置的 qwen3.8-max 实际运行三条路径，并用 [check_live_outputs.py](../tests/check_live_outputs.py) 核对 SQLite、方案数量、费用与时间账本，结果见 [live-validation-summary.json](../examples/live-validation-summary.json)。

| 场景 | 模型实际观察与后续动作 | 实际输出 | 独立 Trace |
| --- | --- | --- | --- |
| 正常 | 估算 premium=12 可行，生成、保存、结束，共 5 步；费用 12 | [live-normal.output](../examples/live-normal.output.json) | [live-normal.trace](../examples/live-normal.trace.json) |
| 超预算 | 观察 premium=12、gap=2，改估 lean=8，再生成保存，共 6 步；费用 8 | [live-over-budget.output](../examples/live-over-budget.output.json) | [live-over-budget.trace](../examples/live-over-budget.trace.json) |
| 一次失败 | 观察 generate_script 返回 retryable，模型选择重试 premium，成功后保存；共 6 步，费用 12，耗时 9 分钟，检索一次 | [live-transient-failure.output](../examples/live-transient-failure.output.json) | [live-transient-failure.trace](../examples/live-transient-failure.trace.json) |

三条输入为对应的 live-*.input.json，逐项链接见 [材料索引](../examples/README.md)。真实失败路径选择了重试，离线策略选择了换 lean；两者的实际行为分别归档，不用离线结果替代模型结果。模型请求由程序逐步发出，重试由模型看到失败后选择，不是程序自动重试。

每条真实路径各有一份方案；累计成功费用等于输出 total_cost 和保存方案 total_cost，完成模拟时间不晚于 deadline。费用、状态与本地数据库已实际一致性核对；数据库本身和密钥不纳入提交。

## 局限与未完成事项

- 三次真实调用不能证明模型在所有输入下稳定成功；没有做大样本通过率、提示注入鲁棒性或真实延迟统计。其他失败与续跑场景主要由离线测试证明。
- 业务工具是合成的本地函数；脚本是模板生成，不证明真实内容质量、素材相关性或创意效果。真实模型只承担规划与动作选择。
- 预算是整数模拟单位，时间是串行模拟耗时，不包括模型 API 真实账单和网络时延；模拟时钟可复现固定日期。
- 只支持预定义 premium/lean/basic 候选，不做任意任务图优化、并行关键路径或全局最优求解。
- 缺信息时要求用户补齐并重新提交，未实现多轮对话界面；CLI 假定用户可信，没有身份认证。
- SQLite 保证本地事务和幂等，不等价于外部付费服务恰好执行一次；真实服务需额外使用服务端幂等键和事务协调。
- 费用或素材目录变更要求新任务 ID，未实现正在进行任务的价格迁移。恢复环境故障允许，但不静默更改原始预算或截止时间。
- 模型非法输出明确返回未完成，不做隐式格式修复；单次决策请求超时 30 秒、最多默认 16 步，未提供全请求的墙钟超时。
- GitHub URL、最终 commit SHA 与私有仓库评审权限待提交时填写，尚未完成远程发布。
