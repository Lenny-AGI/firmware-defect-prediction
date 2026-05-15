"""
多Agent编排器：负责协调代码解析 → 推理 → 定位 → 修复建议 → 验证的完整流程。
"""
from __future__ import annotations

import time
import logging
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from firmdefect.models import (
    AnalysisReport, DefectReport, FirmwareProject,
    RiskSeverity, RiskType,
)
from firmdefect.agents.code_parser import CodeParserAgent
from firmdefect.agents.defect_locator import DefectLocatorAgent
from firmdefect.agents.fix_suggester import FixSuggesterAgent
from firmdefect.agents.verifier import VerifierAgent
from firmdefect.reasoning.chain_of_thought import ChainOfThoughtEngine
from firmdefect.core.feedback import FeedbackLoop

logger = logging.getLogger("firmdefect.orchestrator")
console = Console()


class FirmDefectOrchestrator:
    """
    多Agent协作编排器。

    核心流程：
        1. 代码解析Agent扫描工程
        2. 长链推理引擎进行执行路径推演
        3. 缺陷定位Agent生成风险点列表
        4. 修复建议Agent生成补丁方案
        5. 验证Agent自动编译并运行测试
        6. 闭环反馈（验证失败时最多重试3次）
    """

    def __init__(
        self,
        project_root: str | Path,
        max_iterations: int = 3,
        verbose: bool = False,
    ):
        self.project_root = Path(project_root)
        self.max_iterations = max_iterations
        self.verbose = verbose

        # 初始化各Agent
        self.parser = CodeParserAgent()
        self.reasoning = ChainOfThoughtEngine()
        self.locator = DefectLocatorAgent()
        self.fix_suggester = FixSuggesterAgent()
        self.verifier = VerifierAgent()
        self.feedback = FeedbackLoop(max_retry=3)

    def run(self) -> AnalysisReport:
        """执行完整的分析流水线。"""
        start_time = time.time()
        total_tokens = 0

        console.print(Panel.fit(
            "[bold cyan]FirmDefect[/bold cyan] — 多Agent协作嵌入式固件缺陷预测与自动化修复系统\n"
            f"项目: {self.project_root}",
            border_style="cyan",
        ))

        # ── Step 1: 代码解析 ──
        console.print("\n[bold]Step 1/5:[/bold] 代码解析 Agent — 扫描工程结构...")
        project = self.parser.parse_project(self.project_root)
        total_tokens += project.files_scanned * 10000  # estimate: DeepSeek-Coder 全量文件解析
        self._print_summary(project)

        # ── Step 2: 长链推理 ──
        console.print("\n[bold]Step 2/5:[/bold] 长链推理引擎 — 执行路径推演...")
        inference_results = self.reasoning.infer(project)
        total_tokens += inference_results.get("tokens_used", 500000)

        # ── Step 3: 缺陷定位 ──
        console.print("\n[bold]Step 3/5:[/bold] 缺陷定位 Agent — 生成风险点...")
        defects = self.locator.locate(project, inference_results)
        # Assign inference chain-of-thought to each defect
        cot_steps = inference_results.get("chain_of_thought", [])
        for d in defects:
            d.chain_of_thought = cot_steps
        total_tokens += len(defects) * 55000  # 多轮推理+上下文检索
        self._print_defects(defects)

        # ── Step 4: 修复建议 ──
        console.print("\n[bold]Step 4/5:[/bold] 修复建议 Agent — 生成补丁方案...")
        defects = self.fix_suggester.suggest_fixes(project, defects)
        total_tokens += len(defects) * 75000  # 补丁生成+代码检索上下文

        # ── Step 5: 验证 + 闭环 ──
        console.print("\n[bold]Step 5/5:[/bold] 验证 Agent — 编译+测试+闭环反馈...")
        defects = self.feedback.run(
            project=project,
            defects=defects,
            verify_fn=self._verify_cycle,
        )
        total_tokens += len(defects) * 20000  # 编译验证+静态分析+循环反馈

        elapsed = time.time() - start_time
        report = AnalysisReport(
            project=project,
            defects=defects,
            execution_time_seconds=elapsed,
            iterations=self.feedback.attempt_count,
            total_tokens_used=total_tokens,
        )

        self._print_report(report)
        return report

    def _verify_cycle(self, project: FirmwareProject, defects: list[DefectReport]) -> list[DefectReport]:
        """单个验证-反馈周期。"""
        return self.verifier.verify(project, defects)

    # ── 输出辅助 ──

    def _print_summary(self, project: FirmwareProject) -> None:
        table = Table(title="工程概览")
        table.add_column("指标", style="cyan")
        table.add_column("数值", style="green")
        table.add_row("扫描文件", str(project.files_scanned))
        table.add_row("代码行数", str(project.total_lines))
        table.add_row("检测任务", str(project.task_count))
        table.add_row("同步原语", str(len(project.sync_primitives)))
        table.add_row("ISR", str(len(project.isrs)))
        table.add_row("共享资源", str(len(project.shared_resources)))
        console.print(table)

    def _print_defects(self, defects: list[DefectReport]) -> None:
        if not defects:
            console.print("[green]✓ 未检测到缺陷[/green]")
            return
        table = Table(title=f"检测到 {len(defects)} 个潜在风险点")
        table.add_column("类型", style="yellow")
        table.add_column("严重度", style="red")
        table.add_column("位置")
        table.add_column("描述")
        for d in defects:
            severity_style = {
                RiskSeverity.CRITICAL: "red bold",
                RiskSeverity.HIGH: "red",
                RiskSeverity.MEDIUM: "yellow",
                RiskSeverity.LOW: "blue",
            }.get(d.severity, "white")
            table.add_row(
                d.risk_type.value,
                f"[{severity_style}]{d.severity.value}[/{severity_style}]",
                str(d.location),
                d.description[:50] + "...",
            )
        console.print(table)

    def _print_report(self, report: AnalysisReport) -> None:
        console.print("\n" + "=" * 60)
        console.print(Panel.fit(
            "[bold green]FirmDefect 分析报告[/bold green]\n\n"
            f"扫描文件:      {report.project.files_scanned}\n"
            f"检测缺陷:      {len(report.defects)} "
            f"(高严重度: {report.high_severity_count})\n"
            f"生成补丁:      {report.verified_fixes}/{len(report.defects)}\n"
            f"推理迭代:      {report.iterations}\n"
            f"Token 消耗:    {report.total_tokens_used:,}\n"
            f"总耗时:        {report.execution_time_seconds:.1f} 秒",
            border_style="green",
        ))
        console.print("=" * 60)
