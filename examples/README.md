# 输入、实际输出与运行记录索引

每个场景成组提供 `.input.json`、`.output.json`、`.trace.json`。实际输出由程序运行产生，独立 Trace 直接提取其中 trace，不补造动作。输入校验和重复请求恢复标记 actor=runtime，真实模型路径标记 mode=live，离线策略标记 mode=mock。

## 必验材料

| 场景 | 输入 | 实际输出 | 运行记录 |
| --- | --- | --- | --- |
| 正常完成 | [normal.input](normal.input.json) | [normal.output](normal.output.json) | [normal.trace](normal.trace.json) |
| 缺预算 | [missing-budget.input](missing-budget.input.json) | [missing-budget.output](missing-budget.output.json) | [missing-budget.trace](missing-budget.trace.json) |
| 缺截止时间 | [missing-deadline.input](missing-deadline.input.json) | [missing-deadline.output](missing-deadline.output.json) | [missing-deadline.trace](missing-deadline.trace.json) |
| 工具失败 | [tool-failure.input](tool-failure.input.json) | [tool-failure.output](tool-failure.output.json) | [tool-failure.trace](tool-failure.trace.json) |
| 超预算后重规划 | [over-budget.input](over-budget.input.json) | [over-budget.output](over-budget.output.json) | [over-budget.trace](over-budget.trace.json) |
| 重复执行 | [duplicate.input](duplicate.input.json) | [duplicate.output](duplicate.output.json) | [duplicate.trace](duplicate.trace.json) |

普通场景使用 [world.json](../data/world.json)；工具失败使用 [tool-failure.world.json](../data/tool-failure.world.json)，一次失败使用 [transient-failure.world.json](../data/transient-failure.world.json)，保存失败使用 [save-failure.world.json](../data/save-failure.world.json)。

## 加分项及扩展边界

`resume-before` / `resume` 是同请求、同数据库的前后两次执行，展示失败续跑。`no-feasible` 返回预算缺口，`deadline` 展示选择更快候选，`deadline-failure` 返回时间缺口，`transient-failure` 观察一次生成失败后换候选，`save-failure` 保留脚本及已花费用。这些场景均提供同名三件材料；详情见 [评估文档](../docs/03-evaluation.md)。

13 个离线执行记录的状态、费用和退出码见 [run-summary.json](run-summary.json)。它们证明流程和确定性校验，不能冒充真实模型决策证据。

## 真实模型路径

| 场景 | 输入 | 实际输出 | 运行记录 |
| --- | --- | --- | --- |
| 正常 | [live-normal.input](live-normal.input.json) | [live-normal.output](live-normal.output.json) | [live-normal.trace](live-normal.trace.json) |
| 预算 10，先估 12 再改 8 | [live-over-budget.input](live-over-budget.input.json) | [live-over-budget.output](live-over-budget.output.json) | [live-over-budget.trace](live-over-budget.trace.json) |
| 一次失败后由模型决定重试 | [live-transient-failure.input](live-transient-failure.input.json) | [live-transient-failure.output](live-transient-failure.output.json) | [live-transient-failure.trace](live-transient-failure.trace.json) |

配置的 qwen3.8-max 实际执行了这三条路径，历史数据库核对见 [live-validation-summary.json](live-validation-summary.json)。工具失败路径的实际选择是重试 premium，费用 12；离线策略选择 lean，费用 8，二者分别按真实观察归档。

## 复现与报告

项目根目录执行 `python tests/reproduce.py`，生成离线实际输出、提取 Trace 并运行测试；执行 `python tests/check_submission.py`，核对结构、全部成组材料、Trace、账本和文档链接。真实数据库核对命令见根 README，离线复现不调用真实服务。

报告：[测试结果](test-results.txt)、[离线验证](offline-validation.json)、[交付核查](submission-check.json)、[用时与完成状态](delivery-status.json)。
