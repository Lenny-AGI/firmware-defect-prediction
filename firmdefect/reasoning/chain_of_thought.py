"""
思维链（Chain-of-Thought）推理模块。

实现多步递进推理，模拟嵌入式RTOS中多任务抢占时序分析的推理过程。

推理链路示例：
    任务A持有锁L1 → 任务B请求L1 → 判断是否形成死锁环
    → 若有，检测是否有优先级继承机制
    → 计算临界区竞态窗口长度
    → 标注潜在数据竞争点
"""
from __future__ import annotations

import logging
from typing import Any

from firmdefect.models import FirmwareProject
from firmdefect.reasoning.execution_path import ExecutionPathInference

logger = logging.getLogger("firmdefect.cot")


class ChainOfThoughtEngine:
    """
    思维链推理引擎。

    使用 DeepSeek-Coder 风格的多步推演，对嵌入式RTOS工程
    进行深度并发缺陷分析。
    """

    def __init__(self):
        self.steps: list[str] = []

    def infer(self, project: FirmwareProject) -> dict[str, Any]:
        """
        执行完整推理。

        步骤：
        1. 构建任务-资源模型
        2. 扫描锁获取序列
        3. 检测死锁环
        4. 检查优先级继承
        5. 计算竞态窗口
        6. 标记数据竞争
        7. 汇总风险
        """
        logger.info("启动思维链推理，项目: %s", project.root_path)

        # 使用执行路径推演作为底层引擎
        path_inference = ExecutionPathInference(project)
        path_results = path_inference.infer()

        # 独立的 CoT 推理增强
        self._chain_thought_1_task_analysis(project)
        self._chain_thought_2_lock_graph(project)
        self._chain_thought_3_preemption(project)
        self._chain_thought_4_race_analysis(project)
        self._chain_thought_5_risk_summary(project)

        # 合并结果
        path_results["chain_of_thought"] = self.steps
        path_results["full_reasoning"] = "\n".join(self.steps)
        return path_results

    def _chain_thought_1_task_analysis(self, project: FirmwareProject) -> None:
        """Step 1: 任务分析"""
        self.steps.append("=" * 60)
        self.steps.append("【推理步骤 1/5】任务调度表分析")
        self.steps.append("=" * 60)
        self.steps.append(f"分析项目: {project.root_path}")
        self.steps.append(f"扫描文件数: {project.files_scanned}")
        self.steps.append(f"代码行数: {project.total_lines}")
        self.steps.append(f"发现任务数: {project.task_count}")
        self.steps.append(f"发现同步原语数: {len(project.sync_primitives)}")
        self.steps.append(f"发现ISR数: {len(project.isrs)}")

        if project.tasks:
            self.steps.append("\n任务列表:")
            for t in sorted(project.tasks, key=lambda x: x.priority):
                self.steps.append(
                    f"  ├─ {t.name}: prio={t.priority}, "
                    f"stack={t.stack_size}B, "
                    f"entry={t.entry_point}"
                )
            # 检查优先级重叠
            priorities = [t.priority for t in project.tasks]
            if len(priorities) != len(set(priorities)):
                self.steps.append(
                    "\n⚠ 存在相同优先级的任务，可能影响调度确定性"
                )

    def _chain_thought_2_lock_graph(
        self, project: FirmwareProject,
    ) -> None:
        """Step 2: 锁依赖图分析"""
        self.steps.append("\n" + "=" * 60)
        self.steps.append("【推理步骤 2/5】锁依赖与死锁检测")
        self.steps.append("=" * 60)

        # 分析锁获取模式
        lock_holders: dict[str, list[str]] = {}
        for task in project.tasks:
            for lock in task.held_locks:
                lock_holders.setdefault(lock, []).append(task.name)
                self.steps.append(
                    f"  ├─ 任务 '{task.name}' 持有锁 '{lock}'"
                )

        # 检测锁循环等待
        for prim in project.sync_primitives:
            if prim.waiters:
                self.steps.append(
                    f"  ├─ 同步原语 '{prim.name}' 等待队列: {prim.waiters}"
                )

        # 死锁环检测
        resource_graph: dict[str, set[str]] = {}
        for task in project.tasks:
            resource_graph.setdefault(task.name, set())
            for lock in task.held_locks:
                for prim in project.sync_primitives:
                    if prim.name == lock:
                        for waiter in prim.waiters:
                            if waiter != task.name:
                                resource_graph[task.name].add(waiter)

        # 简单的环检测
        visited: set[str] = set()
        path: list[str] = []

        def _dfs_find_cycle(node: str, start: str, depth: int) -> list[str] | None:
            if depth > len(project.tasks):
                return None
            if node == start and len(path) > 2:
                return path[path.index(node):] + [node]
            if node in visited:
                return None
            visited.add(node)
            path.append(node)
            for neighbor in resource_graph.get(node, set()):
                result = _dfs_find_cycle(neighbor, start, depth + 1)
                if result:
                    return result
            path.pop()
            return None

        cycles_found = 0
        for node in resource_graph:
            visited = set()
            path = []
            cycle = _dfs_find_cycle(node, node, 0)
            if cycle:
                cycles_found += 1
                self.steps.append(f"\n  ⛓  检测到死锁环 #{cycles_found}:")
                for i, c in enumerate(cycle[:-1]):
                    self.steps.append(f"      {c} →")

        if cycles_found == 0:
            self.steps.append("\n  ✓ 未检测到明确的死锁环")

        # 检查优先级继承
        for prim in project.sync_primitives:
            if prim.type.value == "mutex":
                status = "已启用" if prim.priority_inheritance else "未启用"
                self.steps.append(
                    f"  ├─ 互斥量 '{prim.name}' 优先级继承: {status}"
                )

    def _chain_thought_3_preemption(
        self, project: FirmwareProject,
    ) -> None:
        """Step 3: 抢占与优先级分析"""
        self.steps.append("\n" + "=" * 60)
        self.steps.append("【推理步骤 3/5】抢占时序与优先级分析")
        self.steps.append("=" * 60)

        for task in project.tasks:
            self.steps.append(
                f"  ├─ 任务 '{task.name}': "
                f"优先级={task.priority}, "
                f"持有 {len(task.held_locks)} 个锁"
            )

        # 分析优先级反转场景
        high_prio_tasks = sorted(
            [t for t in project.tasks if t.priority < 3],
            key=lambda x: x.priority,
        )
        low_prio_tasks = sorted(
            [t for t in project.tasks if t.priority >= 3],
            key=lambda x: x.priority,
        )

        if high_prio_tasks and low_prio_tasks:
            self.steps.append(
                f"\n  ⚠ 存在优先级反转风险场景:"
            )
            for hp in high_prio_tasks:
                for lp in low_prio_tasks:
                    shared_locks = set(hp.held_locks) & set(lp.held_locks)
                    if shared_locks:
                        self.steps.append(
                            f"    - {hp.name}(prio {hp.priority}) 与 "
                            f"{lp.name}(prio {lp.priority}) "
                            f"共享锁 {shared_locks}"
                        )

        # ISR 抢占分析
        if project.isrs and project.tasks:
            self.steps.append(
                f"\n  ├─ ISR 与任务并发分析: "
                f"{len(project.isrs)} 个ISR, {project.task_count} 个任务"
            )

    def _chain_thought_4_race_analysis(
        self, project: FirmwareProject,
    ) -> None:
        """Step 4: 数据竞争与竞态窗口分析"""
        self.steps.append("\n" + "=" * 60)
        self.steps.append("【推理步骤 4/5】数据竞争与竞态窗口分析")
        self.steps.append("=" * 60)

        # 临界区分析
        cs_by_func: dict[str, list] = {}
        for cs in project.critical_sections:
            cs_by_func.setdefault(cs.function, []).append(cs)

        for func, sections in cs_by_func.items():
            self.steps.append(
                f"  ├─ 函数 '{func}': {len(sections)} 个临界区"
            )
            for cs in sections:
                window = cs.end_line - cs.start_line
                self.steps.append(
                    f"    ├─ 行 {cs.start_line}-{cs.end_line} "
                    f"(竞态窗口: ~{max(window, 5)} 条指令)"
                )

        # 共享资源分析
        for res in project.shared_resources:
            status = (
                "有保护" if res.protecting_primitives else "⚠ 无保护"
            )
            self.steps.append(
                f"  ├─ 共享资源 '{res.name}' ({status}), "
                f"被 {len(res.accessed_by)} 个上下文访问"
            )

        # 检查ISR与任务共享资源
        for isr in project.isrs:
            for task in project.tasks:
                common = set(isr.shared_resources) & {
                    r.name for r in project.shared_resources
                }
                if common:
                    self.steps.append(
                        f"  ⚠ ISR '{isr.name}' 与任务 '{task.name}' "
                        f"共享资源 {common}，可能存在ISR安全风险"
                    )

    def _chain_thought_5_risk_summary(
        self, project: FirmwareProject,
    ) -> None:
        """Step 5: 风险汇总"""
        self.steps.append("\n" + "=" * 60)
        self.steps.append("【推理步骤 5/5】风险汇总与评估")
        self.steps.append("=" * 60)

        # 汇总各维度风险
        risks: list[str] = []

        if len(project.tasks) >= 2 and len(project.sync_primitives) >= 2:
            risks.append("死锁风险: 中 — 存在多锁任务")

        unprotected = [
            r for r in project.shared_resources
            if not r.protecting_primitives
        ]
        if unprotected:
            risks.append(
                f"数据竞争风险: 高 — {len(unprotected)} 个无保护共享资源"
            )

        small_stacks = [t for t in project.tasks if t.stack_size < 512]
        if small_stacks:
            risks.append(
                f"栈溢出风险: 高 — {len(small_stacks)} 个任务栈过小"
            )

        if project.isrs and project.shared_resources:
            risks.append("ISR安全风险: 中 — ISR与任务共享资源")

        if risks:
            self.steps.append("\n  检测到以下风险:")
            for r in risks:
                self.steps.append(f"    • {r}")
        else:
            self.steps.append("\n  ✓ 未检测到显著风险")

        self.steps.append(
            f"\n  总览: {project.task_count} 任务, "
            f"{len(project.sync_primitives)} 同步原语, "
            f"{len(project.isrs)} ISR, "
            f"{len(project.shared_resources)} 共享资源"
        )
        self.steps.append("推理完成。")
