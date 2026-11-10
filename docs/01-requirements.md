# 用户、目标、范围与成功标准

第 2 题“内容任务规划 Agent”的用户是运营人员。输入主题、预算、截止时间后，系统利用合成素材与工具费用/耗时表形成可执行任务计划，在资源约束内保存内容活动方案；失败时保留已成功步骤，并准确返回未完成原因。原题末尾的上传提示不属于业务需求。

## 输入、输出与边界

请求字段为 request_id、theme、budget、deadline，可选 start_at；request_id 是新增的幂等标识。budget 是非负整数模拟单位，deadline 和 start_at 必须包含时区。缺主题、预算或截止时间返回待补充，不擅自填默认预算或时间，不调用模型与业务工具。

四个工具是素材检索 search_materials、脚本生成 generate_script、成本估算 estimate_cost、方案保存 save_plan。模型选择工具及候选方案，观察结果后再次决策；程序校验步骤依赖、累计费用与预计完成时间。输出包括 task_plan、steps、tool_results、total_cost、saved_plan、未完成原因、缺口和 Trace。

本题使用本地合成业务工具，真实模型负责动作选择，不将合成脚本质量说成真实创作效果。费用与耗时是模拟数据；不包含模型服务的真实账单，也不以真实网络延迟推进模拟业务时钟。

## 优先级与成功标准

P0：依赖顺序正确、预算与截止时间不可越过、失败不能报成功、已成功步骤和费用账本持久化。P0 同时要求真实模型“选择动作 → 执行工具 → 读取结果 → 调整或结束”的有界循环。

P1：五类必验场景、失败续跑、可复现 CLI 和完整交付材料。界面、部署、多 Agent 和生产级 Runtime 不在当前范围。

| 验收项 | 成功标准 | 对应测试 |
| --- | --- | --- |
| 正常完成 | 在预算和截止时间内生成并保存方案，费用与账本一致 | test_normal_plan_cost_dependencies_and_persistence |
| 缺预算或截止时间 | 明确待补充，无虚构值、无工具副作用 | test_missing_budget_and_deadline_are_not_invented |
| 工具失败 | 记录失败及未完成原因，保留素材或脚本等成功结果 | test_all_generation_failures_do_not_become_successful、test_save_failure_preserves_generated_script_and_real_charges |
| 预算超限 | 观察估算 12 后可改选 8；全部不可行则返回缺口 | test_observe_12_then_replan_to_8_within_budget_10、test_no_feasible_budget_reports_gap_without_spending |
| 重复执行 | 一份方案，同 ID，不重复生成、不重复计费 | test_duplicate_finished_task_has_one_plan_and_no_new_events |
| 失败续跑（加分） | 跨进程恢复成功步骤，只重试失败或未完成部分 | test_resume_after_failure_reuses_prior_success_and_does_not_double_charge |
| 时间约束 | 选择更快方案或明确超期缺口，不执行越界付费步骤 | test_deadline_causes_faster_variant_selection、test_no_feasible_deadline_reports_time_gap |
| 动态决策 | 至少两条真实模型路径因观察不同而改变动作或参数 | examples/live-*.trace.json |
| 有界执行 | 默认最多 16 步；达到上限返回 incomplete，保留已落盘事实 | test_step_limit_and_premature_finish_are_incomplete |

## 显式假设

采用串行依赖：检索 → 对候选估算 → 同候选脚本生成 → 保存。估算免费且不计模拟耗时。其他工具成功后按表收费、累计耗时；注入失败不收费，消耗指定失败时间。已花费用不可退款。工具返回失败、估算不可行和任务未完成是不同状态。

模拟起点由 start_at 或合成数据中的 simulation_start 决定，以确保固定样例可重复运行。已有方案以任务 ID 唯一保存。原始请求与素材/费用目录不可在相同任务 ID 下修改，恢复环境故障配置除外。CLI 文件被视为可信用户输入，素材内容是数据，不授予改变预算或截止时间的权限。
