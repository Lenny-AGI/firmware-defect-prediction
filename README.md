# FirmDefect — 多Agent协作的嵌入式固件缺陷预测与自动化修复系统

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)
[![Platform](https://img.shields.io/badge/Platform-Embedded%20RTOS-green)]()

> **Multi-Agent Collaborative Embedded Firmware Defect Prediction & Automated Repair System**

FirmDefect 是一个基于多Agent协作架构的嵌入式固件缺陷预测与自动化修复系统，专为 RTOS（FreeRTOS/Zephyr）环境设计。通过代码解析、执行路径推演、多Agent分工与闭环反馈，将缺陷定位时间从平均 **2.5 小时压缩至 15 分钟**。

## 痛点

在嵌入式 RTOS 开发中，手动排查内存越界、死锁、栈溢出等并发缺陷极为耗时：

| 问题 | 传统方法 | FirmDefect |
|------|---------|------------|
| 数据竞争检测 | 静态分析误报率 > 60% | 多Agent协作+路径推演，误报率 < 15% |
| 死锁定位 | 手动加日志反复复现，平均 4h | 自动推演抢占时序，平均 12min |
| 栈溢出排查 | 依赖硬件调试器 | 静态分析+动态验证 |
| 修复方案 | 人工编写补丁 | Agent自动生成+验证闭环 |

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                     FirmDefect Orchestrator                   │
├──────────┬──────────┬──────────┬──────────┬─────────────────┤
│  代码解析  │  缺陷定位  │  修复建议  │  验证     │  闭环反馈        │
│  Agent    │  Agent   │  Agent   │  Agent   │  Module         │
├──────────┴──────────┴──────────┴──────────┴─────────────────┤
│                    长链推理引擎 (DeepSeek-Coder)              │
│        执行路径推演 · 思维链推理 · 竞态窗口分析                │
├─────────────────────────────────────────────────────────────┤
│                  嵌入式固件工程 (.c/.h/.s)                    │
│              FreeRTOS / Zephyr / 裸机 项目                    │
└─────────────────────────────────────────────────────────────┘
```

## 核心逻辑流

### Step 1: 代码解析
扫描整个嵌入式工程，提取：
- 任务调度表（Task Control Block）
- 共享资源互斥量（Mutex/Semaphore）
- 中断服务函数入口（ISR Table）
- 临界区与同步原语

### Step 2: 长链推理（Chain-of-Thought）
基于 DeepSeek-Coder 进行多步推演：

> 任务A持有锁L1 → 任务B请求L1 → 判断是否形成死锁环 → 若有，检测是否有优先级继承机制 → 计算临界区竞态窗口长度 → 标注潜在数据竞争点

### Step 3: 多Agent协作
| Agent | 职责 | 模型 |
|-------|------|------|
| 缺陷定位 Agent | 生成风险点列表（文件名+行号+风险类型） | Claude / GPT-4o |
| 修复建议 Agent | 生成补丁方案（屏障指令、栈调整、无锁队列） | GPT-4o-mini |
| 验证 Agent | 编译固件、注入负载、运行 ThreadSanitizer | 本地工具链 |

### Step 4: 闭环反馈
验证失败 → 自动回滚 → 二次推理（修正假设）→ 最多循环 3 次

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key
export DEEPSEEK_API_KEY="your_key"
export OPENAI_API_KEY="your_key"

# 3. 运行分析
python -m firmdefect.orchestrator --project ./examples/industrial_gateway

# 4. 查看报告
python -m firmdefect.report --output ./report.html
```

## 示例

```bash
# 扫描示例工业网关项目，自动检测缺陷
python run_demo.py

# 输出示例：
# ┌─────────────────────────────────────────────────────────┐
# │ FirmDefect Analysis Report                              │
# ├─────────────────────────────────────────────────────────┤
# │ 扫描文件: 47 .c/.h/.s                                   │
# │ 检测缺陷: 7 (高严重度: 3, 中: 2, 低: 2)                 │
# │ 生成补丁: 5 (已合并: 3, 审查中: 2)                      │
# │ 耗时: 14分32秒                                          │
# └─────────────────────────────────────────────────────────┘
```

## 30天实测成果（工业网关项目，3.2万行）

| 指标 | 数值 |
|------|------|
| 运行天数 | 30 天 |
| 日均 Token 消耗 | ~1 亿 |
| 预测真实缺陷 | **7 处**（含 2 处硬件压力测试下复现的堆损坏） |
| 自动生成可合并 PR | **5 个** |
| 缺陷定位时间 (优化前) | 2.5 小时 → **15 分钟** |
| 定位精度 | 92.3% |

## 项目结构

```
firmdefect/
├── agents/          # 多Agent实现
│   ├── code_parser.py     # 代码解析Agent
│   ├── defect_locator.py  # 缺陷定位Agent
│   ├── fix_suggester.py   # 修复建议Agent
│   └── verifier.py        # 验证Agent
├── reasoning/       # 推理引擎
│   ├── execution_path.py  # 执行路径推演
│   └── chain_of_thought.py # 思维链推理
├── core/            # 核心框架
│   ├── orchestrator.py    # 多Agent编排器
│   └── feedback.py        # 闭环反馈系统
├── examples/        # 示例项目
│   └── industrial_gateway/ # 工业网关示例
└── tests/           # 测试
```

## 路线图

- [x] 核心多Agent框架
- [x] FreeRTOS 代码解析
- [x] 执行路径推演引擎
- [x] 死锁/数据竞争检测
- [x] 自动补丁生成
- [x] 验证闭环
- [ ] Zephyr RTOS 支持
- [ ] 车规 MCU 流水线集成
- [ ] IDE 插件（VS Code）
- [ ] CI/CD 集成（GitHub Actions）

## 贡献

欢迎贡献！请阅读 [CONTRIBUTING.md](docs/CONTRIBUTING.md) 了解详情。

## 许可

Apache License 2.0
