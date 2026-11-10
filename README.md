# 第 2 题：内容任务规划 Agent

帮助运营人员在预算与截止时间内完成内容活动方案。交付任务计划、步骤状态、工具结果、费用账本、已保存方案或未完成原因。使用 Python 标准库和 SQLite，无第三方依赖。

本目录是独立项目根目录。若当前位于外层工作区，先执行 `cd .\xiaoying_test_2`；上传 GitHub 时以本目录内容作为仓库根目录。代码不会导入其他题目录。

已完成 30 项测试和 13 个离线执行场景，并通过配置的 qwen3.8-max 实际验证正常、超预算重规划、工具一次失败三条路径。真实模型实际观察到 premium 估算 12 超出预算 10 后，改选 lean 并以费用 8 保存方案。证据见 [评估文档](docs/03-evaluation.md)。

## 项目目录

```text
xiaoying_test_2/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── src/                          # 模型、工具、任务状态、CLI
├── tests/                        # 可执行测试、复现、交付与数据库核对
├── examples/                     # 成组输入、实际输出、Trace、测试结果
│   ├── README.md                 # 验证材料索引
│   ├── normal.input.json
│   ├── normal.output.json
│   ├── normal.trace.json
│   ├── missing-budget.*.json
│   ├── tool-failure.*.json
│   ├── over-budget.*.json
│   ├── live-*.{input,output,trace}.json
│   └── test-results.txt
├── data/                         # 合成素材、费用与耗时表、故障配置
└── docs/
    ├── 01-requirements.md        # 用户、目标、范围、成功标准
    ├── 02-solution.md            # 调用流程、动态决策、技术取舍
    ├── 03-evaluation.md          # 预期、实际结果、失败与限制
    ├── 04-ai-usage.md            # AI 辅助、个人贡献及验证
    └── 05-retrospective.md       # 难点、学习收获、下一步
```

## 环境、安装与离线复现

要求 Python 3.12+，已在 Windows / Python 3.12.3 验证。依赖声明见 requirements.txt，全部使用标准库，无须安装第三方包。无需模型配置即可执行：

```powershell
python --version
python tests/reproduce.py
python tests/check_submission.py
```

复现脚本通过真实 CLI 在临时数据库中运行各场景，检查实际退出码和关键结果，生成 [测试结果](examples/test-results.txt) 与 [离线汇总](examples/offline-validation.json)；不会调用真实模型或覆盖归档的真实模型输出。交付核查验证目录、五份文档、成组材料、Trace 与输出一致性和费用账本，结果在 [submission-check.json](examples/submission-check.json)。

单独运行一条或只运行测试：

```powershell
python -B -m src --mock --input examples/normal.input.json --db .runtime/demo.sqlite3 --output .runtime/demo.output.json
python -B -m unittest discover -s tests -v
```

## 输入、输出和计费

输入示例：

```json
{
  "request_id": "campaign-001",
  "theme": "健康生活",
  "budget": 10,
  "deadline": "2026-11-11T10:00:00+08:00"
}
```

主题、预算、截止时间必填；缺预算或截止时间返回 needs_information，不调用模型和业务工具。request_id 用于持久化、幂等和续跑；修改原始请求需使用新 ID。预算为非负整数模拟单位。可选 start_at，否则采用合成数据中的 simulation_start。

工具费用/耗时表在 [data/world.json](data/world.json)。检索费用 0、耗时 1 分钟；估算免费且不耗模拟时间；premium/lean/basic 脚本分别为 10/6/4 单位、6/3/2 分钟；保存费用 2、耗时 1 分钟。因此完整候选总费用为 12/8/6。失败不收费，默认耗时 1 分钟；已经成功产生的费用不退款。

输出中 task_plan 为依赖计划，steps 为各步骤最新状态，tool_results 保留全部执行事件，total_cost 是实际成功工具费用合计，saved_plan 是真实保存结果；未完成时 reason 和 unmet_constraints 说明失败或资源缺口。估算超限不是已经花费，失败步骤不会被伪装为成功事件。

**模拟费用与业务时间不等于模型服务的实际账单和网络时延。** 合成时钟固定以便复现历史日期；不以运行当天日期解释固定样例是否过期。业务工具是本地合成函数，真实模型负责规划与选择动作。

## 超预算、失败、重复与续跑

```powershell
python -B -m src --mock --input examples/over-budget.input.json --db .runtime/budget.sqlite3
python -B -m src --mock --input examples/tool-failure.input.json --data data/tool-failure.world.json --db .runtime/failure.sqlite3
```

第一条展示预算 10 下从估算 12 改选 8；第二条全部候选生成失败，明确未完成，成功检索结果保留。工具失败或无可行方案退出码为 1，是此负例的预期结果。

重复完成任务会返回原方案、duplicate=true，没有新工具费用。续跑演示：

```powershell
python -B -m src --mock --input examples/resume-before.input.json --data data/transient-failure.world.json --db .runtime/resume.sqlite3 --max-steps 3
python -B -m src --mock --input examples/resume.input.json --data data/transient-failure.world.json --db .runtime/resume.sqlite3
```

第一次执行注入一次生成失败并达到 3 步上限，退出码 1；第二次同请求、同数据库恢复，从失败步骤继续，成功检索不再执行，费用累计正确。需要重新演示时使用新数据库路径。

## 真实模型配置与运行

参照 [.env.example](.env.example)，在本目录创建 .env，填写 LLM_BASE_URL、LLM_MODEL、LLM_API_KEY；也可用 --env-file 指定本机配置文件。交付目录不含真实密钥。环境变量优先于文件；支持单行 KEY=VALUE、整行注释和成对引号，不支持变量展开或多行值。

服务需支持 HTTPS、Bearer 认证及 /chat/completions JSON 协议。LLM_BASE_URL 填接口前缀，程序自动追加 /chat/completions，不要重复填写该后缀。请求包含 model、messages、temperature；响应读取 choices[0].message.content 中的纯 JSON 动作。

配置后执行以下命令，不加 --mock：

```powershell
python -B -m src --input examples/live-normal.input.json --db .runtime/live-normal.sqlite3 --output examples/live-normal.output.json
python -B -m src --input examples/live-over-budget.input.json --db .runtime/live-over-budget.sqlite3 --output examples/live-over-budget.output.json
python -B -m src --input examples/live-transient-failure.input.json --data data/transient-failure.world.json --db .runtime/live-transient-failure.sqlite3 --output examples/live-transient-failure.output.json
python -B tests/check_live_outputs.py
python tests/reproduce.py
```

数据库核对脚本需要上述三份本地数据库；独立评审可先直接阅读归档 JSON。最后的离线复现命令用于提取新 Trace，不重写真实输出。单独指定外部配置时，对每条真实命令追加 `--env-file 本机文件路径`。

每轮模型依据上一步工具结果选择下一动作，默认最多 16 步（包括 finish），--max-steps 可设置 1..100。每次模型请求超时 30 秒，没有程序自动重试；保存、生成之前都检查依赖和资源约束。达到上限或模型协议错误返回 incomplete，并保留实际已发生的保存和计费事实。

退出码 0 表示 completed 或 needs_information；1 表示 incomplete；2 表示输入、配置或初始化错误。默认真实模式缺配置会报错，不会静默切换 Mock；必填约束缺失时先返回补充信息而不要求模型配置。

## 评审入口与提交信息

| 检查项 | 入口 |
| --- | --- |
| 用户、范围与验收 | [01-requirements.md](docs/01-requirements.md) |
| 调用链、状态、费用与取舍 | [02-solution.md](docs/02-solution.md) |
| 预期、实际结果、失败和限制 | [03-evaluation.md](docs/03-evaluation.md) |
| AI 辅助与个人贡献边界 | [04-ai-usage.md](docs/04-ai-usage.md) |
| 难点、用时与下一步 | [05-retrospective.md](docs/05-retrospective.md) |
| 全部输入、输出和 Trace | [examples/README.md](examples/README.md) |

题号：2。GitHub URL、最终 commit SHA 待创建仓库并完成最终提交后填写；私有仓库需给指定评审账号读取权限。本人实际投入、独立修改及亲自验证记录应在提交前如实补充。目前完成本地交付，尚未远程发布。
