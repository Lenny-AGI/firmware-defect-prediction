#!/usr/bin/env python3
"""
FirmDefect 演示运行脚本
对示例工业网关固件项目执行完整的多Agent缺陷分析。

执行流程:
  1. 代码解析Agent扫描工程
  2. 长链推理引擎执行路径推演
  3. 缺陷定位Agent生成风险点列表
  4. 修复建议Agent生成补丁方案
  5. 验证Agent进行静态/编译验证
  6. 输出HTML报告

使用方法:
  python run_demo.py                    # 运行完整分析
  python run_demo.py --quick            # 快速模式（仅解析+推理）
  python run_demo.py --output report    # 指定输出目录
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.layout import Layout
from rich.live import Live

# 确保项目根目录在 Python 路径中
project_root = Path(__file__).parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from firmdefect.core.orchestrator import FirmDefectOrchestrator
from firmdefect.models import RiskSeverity

console = Console()

BANNER = """
╔══════════════════════════════════════════════════════════════╗
║              FirmDefect — 多Agent嵌入式缺陷预测系统           ║
║         Multi-Agent Embedded Firmware Defect Prediction      ║
╚══════════════════════════════════════════════════════════════╝
"""


def main():
    console.print(BANNER, style="bold cyan")
    console.print("[dim]版本 0.1.0 | 基于多Agent协作的嵌入式固件缺陷预测与自动化修复[/dim]\n")

    # 确定示例项目路径
    demo_project = project_root / "examples" / "industrial_gateway"
    if not demo_project.exists():
        console.print(f"[red]错误: 示例项目不存在: {demo_project}[/red]")
        sys.exit(1)

    # 快速模式
    quick_mode = "--quick" in sys.argv

    # 初始化编排器
    orchestrator = FirmDefectOrchestrator(
        project_root=str(demo_project),
        max_iterations=1 if quick_mode else 3,
        verbose=True,
    )

    # 运行分析
    console.print("\n[bold yellow]▶ 启动多Agent协作分析流水线...[/bold yellow]\n")
    start = time.time()
    report = orchestrator.run()
    elapsed = time.time() - start

    # ── 详细结果展示 ──
    _show_detailed_results(report, elapsed)

    # ── 生成报告 ──
    _generate_report(report, elapsed)


def _show_detailed_results(report, elapsed):
    """显示详细的缺陷分析和修复方案。"""
    console.print("\n" + "=" * 70)
    console.print("[bold cyan]📋 缺陷分析与修复详情[/bold cyan]")
    console.print("=" * 70)

    for i, defect in enumerate(report.defects, 1):
        severity_color = {
            RiskSeverity.CRITICAL: "red bold",
            RiskSeverity.HIGH: "red",
            RiskSeverity.MEDIUM: "yellow",
            RiskSeverity.LOW: "blue",
        }.get(defect.severity, "white")

        console.print(f"\n[bold]缺陷 #{i}[/bold] | "
                      f"[{severity_color}]{defect.severity.value.upper()}[/{severity_color}] | "
                      f"[dim]{defect.risk_type.value}[/dim]")
        console.print(f"  位置:    [underline]{defect.location}[/underline]")
        console.print(f"  描述:    {defect.description}")
        console.print(f"  置信度:  {defect.confidence:.0%}")
        console.print(f"  验证:    {'✅ 通过' if defect.verified else '❌ 未验证'}")

        # 显示思维链
        if defect.chain_of_thought:
            console.print(f"  推理链:")
            for step in defect.chain_of_thought[-5:]:  # 只显示最后5步
                console.print(f"    └─ {step}")

        # 显示修复方案
        if defect.suggested_fix:
            console.print(f"  修复方案:")
            syntax = Syntax(
                defect.suggested_fix[:300] + "...",
                "c",
                theme="monokai",
                line_numbers=False,
            )
            console.print(syntax)

    # 统计
    console.print("\n" + "=" * 70)
    verified = sum(1 for d in report.defects if d.verified)
    console.print(f"[bold]统计:[/bold] "
                  f"共 {len(report.defects)} 个缺陷, "
                  f"{verified} 个已验证, "
                  f"耗时 {elapsed:.1f}s")


def _generate_report(report, elapsed):
    """生成HTML报告。"""
    output_dir = project_root / "reports"
    output_dir.mkdir(exist_ok=True)

    html = _build_html_report(report, elapsed)
    report_path = output_dir / "firmdefect_report.html"
    report_path.write_text(html, encoding="utf-8")

    console.print(f"\n[green]✅ HTML 报告已生成: {report_path}[/green]")


def _build_html_report(report, elapsed):
    """构建HTML报告内容。"""
    defects_rows = ""
    for i, d in enumerate(report.defects, 1):
        severity_class = d.severity.value
        cot_steps = "<br>".join(
            f"&nbsp;&nbsp;→ {s}" for s in d.chain_of_thought[-5:]
        ) if d.chain_of_thought else "N/A"
        fix_preview = (
            d.suggested_fix[:200].replace("\n", "<br>") + "..."
            if d.suggested_fix else "未生成"
        )
        verified_icon = "✅" if d.verified else "❌"

        defects_rows += f"""
        <tr>
            <td>{i}</td>
            <td><span class="risk-type">{d.risk_type.value}</span></td>
            <td><span class="severity {severity_class}">{d.severity.value}</span></td>
            <td><code>{d.location}</code></td>
            <td>{d.description[:60]}</td>
            <td>{d.confidence:.0%}</td>
            <td>{verified_icon}</td>
            <td><small>{cot_steps}</small></td>
            <td><small><pre>{fix_preview}</pre></small></td>
        </tr>"""

    high_count = sum(
        1 for d in report.defects
        if d.severity in (RiskSeverity.HIGH, RiskSeverity.CRITICAL)
    )

    return f"""\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FirmDefect 分析报告 — 工业网关示例</title>
<style>
  {{"{"}}
    margin: 0; padding: 0; box-sizing: border-box;
  }}
  body {{"{"}}
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0d1117; color: #c9d1d9; padding: 20px;
  }}
  .container {{"{"}}
    max-width: 1200px; margin: 0 auto;
  }}
  h1 {{"{"}}
    color: #58a6ff; border-bottom: 1px solid #30363d; padding-bottom: 10px;
  }}
  h2 {{"{"}} color: #f0883e; margin-top: 30px; }}
  .summary {{"{"}}
    display: grid; grid-template-columns: repeat(4, 1fr);
    gap: 16px; margin: 20px 0;
  }}
  .card {{"{"}}
    background: #161b22; border: 1px solid #30363d;
    border-radius: 8px; padding: 20px; text-align: center;
  }}
  .card .value {{"{"}}
    font-size: 2em; font-weight: bold; color: #58a6ff;
  }}
  .card .label {{"{"}} color: #8b949e; margin-top: 8px; }}
  table {{"{"}}
    width: 100%; border-collapse: collapse; margin: 20px 0;
    background: #161b22; border-radius: 8px; overflow: hidden;
  }}
  th, td {{"{"}}
    padding: 12px 16px; text-align: left; border-bottom: 1px solid #30363d;
  }}
  th {{"{"}} background: #1c2128; color: #8b949e; font-weight: 600; }}
  tr:hover {{"{"}} background: #1c2128; }}
  .severity {{"{"}}
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 0.85em; font-weight: 600;
  }}
  .critical {{"{"}} background: #3d1a1a; color: #ff6b6b; }}
  .high {{"{"}} background: #3d2e1a; color: #ffa657; }}
  .medium {{"{"}} background: #2e3d1a; color: #a3d977; }}
  .low {{"{"}} background: #1a2e3d; color: #79c0ff; }}
  .risk-type {{"{"}}
    background: #1f2937; padding: 2px 8px; border-radius: 4px;
    font-family: monospace; font-size: 0.85em;
  }}
  code {{"{"}}
    background: #1f2937; padding: 2px 6px; border-radius: 4px;
    font-size: 0.85em;
  }}
  pre {{"{"}}
    background: #1f2937; padding: 8px; border-radius: 4px;
    font-size: 0.75em; max-height: 100px; overflow-y: auto;
  }}
  .footer {{"{"}}
    text-align: center; color: #484f58; margin-top: 40px;
    padding-top: 20px; border-top: 1px solid #30363d;
  }}
</style>
</head>
<body>
<div class="container">
  <h1>🔍 FirmDefect 分析报告</h1>
  <p>项目: examples/industrial_gateway | 生成时间: {time.strftime("%Y-%m-%d %H:%M:%S")}</p>

  <div class="summary">
    <div class="card">
      <div class="value">{report.project.files_scanned}</div>
      <div class="label">扫描文件</div>
    </div>
    <div class="card">
      <div class="value">{len(report.defects)}</div>
      <div class="label">检测缺陷</div>
    </div>
    <div class="card">
      <div class="value" style="color:#ff6b6b">{high_count}</div>
      <div class="label">高严重度</div>
    </div>
    <div class="card">
      <div class="value">{report.execution_time_seconds:.1f}s</div>
      <div class="label">分析耗时</div>
    </div>
  </div>

  <h2>📋 项目概览</h2>
  <table>
    <tr><th>指标</th><th>数值</th></tr>
    <tr><td>代码行数</td><td>{report.project.total_lines}</td></tr>
    <tr><td>RTOS任务数</td><td>{report.project.task_count}</td></tr>
    <tr><td>同步原语</td><td>{len(report.project.sync_primitives)}</td></tr>
    <tr><td>ISR数量</td><td>{len(report.project.isrs)}</td></tr>
    <tr><td>共享资源</td><td>{len(report.project.shared_resources)}</td></tr>
    <tr><td>推理迭代</td><td>{report.iterations}</td></tr>
    <tr><td>Token消耗</td><td>{report.total_tokens_used:,}</td></tr>
  </table>

  <h2>🛡 检测到的缺陷</h2>
  <table>
    <tr>
      <th>#</th><th>类型</th><th>严重度</th><th>位置</th>
      <th>描述</th><th>置信度</th><th>验证</th><th>推理链</th><th>修复方案</th>
    </tr>
    {defects_rows}
  </table>

  <div class="footer">
    <p>FirmDefect v0.1.0 — 多Agent协作嵌入式固件缺陷预测与自动化修复系统</p>
    <p>本报告由 FirmDefect 自动生成 | {time.strftime("%Y-%m-%d %H:%M:%S")}</p>
  </div>
</div>
</body>
</html>"""


if __name__ == "__main__":
    main()
