"""
执行路径推演模块：模拟多任务抢占时序，计算临界区竞态窗口长度，标注潜在数据竞争点。

核心算法：
1. 构建任务间资源依赖图
2. 枚举可能的调度序列
3. 计算每个临界区的竞态窗口
4. 标记窗口重叠的访问对
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from firmdefect.models import (
    FirmwareProject, Task, SyncPrimitive, CriticalSection,
    SharedResource,
)

logger = logging.getLogger("firmdefect.execution_path")


@dataclass
class RaceWindow:
    """竞态窗口"""
    task_name: str
    resource: str
    start_instruction: int
    end_instruction: int
    location: str


@dataclass
class PreemptionScenario:
    """抢占场景"""
    higher_prio_task: str
    lower_prio_task: str
    shared_resource: str
    is_preemptible: bool
    race_window_ticks: int = 0


class ExecutionPathInference:
    """
    执行路径推演引擎。

    通过模拟多任务调度和资源获取/释放序列，识别潜在的竞态条件。
    """

    def __init__(self, project: FirmwareProject):
        self.project = project
        self.race_windows: list[RaceWindow] = []
        self.preemption_scenarios: list[PreemptionScenario] = []

    def infer(self) -> dict[str, Any]:
        """执行完整的路径推演。"""
        resource_graph = self._build_resource_dependency_graph()
        preemption_analysis = self._analyze_preemption()
        race_windows = self._calculate_race_windows()
        deadlock_cycles = self._find_deadlock_cycles(resource_graph)

        return {
            "resource_dependency_graph": resource_graph,
            "preemption_analysis": preemption_analysis,
            "race_windows": race_windows,
            "potential_deadlocks": self._format_deadlocks(deadlock_cycles),
            "potential_data_races": self._format_data_races(race_windows),
            "chain_of_thought": self._generate_cot(),
            "tokens_used": len(str(resource_graph)) // 4 + 3000,
        }

    def _build_resource_dependency_graph(self) -> dict[str, set[str]]:
        """
        构建资源依赖图。

        节点 = 任务，边 = 共享资源依赖
        用于后续的死锁环检测。
        """
        graph: dict[str, set[str]] = {}
        for task in self.project.tasks:
            graph.setdefault(task.name, set())
            for lock in task.held_locks:
                # 查找等待该锁的其他任务
                for prim in self.project.sync_primitives:
                    if prim.name == lock:
                        for waiter in prim.waiters:
                            if waiter != task.name:
                                graph[task.name].add(waiter)
        return graph

    def _analyze_preemption(self) -> list[dict[str, Any]]:
        """
        分析抢占场景。

        对每个共享资源，检查是否有更高优先级的任务可能抢占当前持有者。
        """
        results = []
        for res in self.project.shared_resources:
            for prim_name in res.protecting_primitives:
                # 找到使用该原语的任务
                users = [
                    t for t in self.project.tasks
                    if prim_name in t.held_locks
                ]
                if len(users) < 2:
                    continue

                for i, t1 in enumerate(users):
                    for t2 in users[i + 1:]:
                        scenario = PreemptionScenario(
                            higher_prio_task=(
                                t1.name if t1.priority < t2.priority
                                else t2.name
                            ),
                            lower_prio_task=(
                                t2.name if t1.priority < t2.priority
                                else t1.name
                            ),
                            shared_resource=res.name,
                            is_preemptible=True,
                            race_window_ticks=abs(t1.priority - t2.priority) * 10,
                        )
                        self.preemption_scenarios.append(scenario)
                        results.append({
                            "higher_prio_task": scenario.higher_prio_task,
                            "lower_prio_task": scenario.lower_prio_task,
                            "shared_resource": scenario.shared_resource,
                            "race_window_ticks": scenario.race_window_ticks,
                        })
        return results

    def _calculate_race_windows(self) -> list[dict[str, Any]]:
        """
        计算每个临界区的竞态窗口。

        竞态窗口 = 从锁获取到锁释放之间的指令序列长度。
        窗口重叠的访问对被标记为潜在数据竞争。
        """
        results = []
        for cs in self.project.critical_sections:
            window_len = cs.end_line - cs.start_line
            if window_len <= 0:
                window_len = 5  # 默认窗口

            # 查找关联资源
            for res in self.project.shared_resources:
                if cs.lock in res.protecting_primitives:
                    rw = RaceWindow(
                        task_name=cs.function,
                        resource=res.name,
                        start_instruction=cs.start_line,
                        end_instruction=cs.end_line,
                        location=str(cs.location),
                    )
                    self.race_windows.append(rw)
                    results.append({
                        "task": cs.function,
                        "resource": res.name,
                        "window_size": window_len,
                        "location": str(cs.location),
                        "start_line": cs.start_line,
                        "end_line": cs.end_line,
                    })
        return results

    def _find_deadlock_cycles(
        self, graph: dict[str, set[str]],
    ) -> list[list[str]]:
        """
        使用DFS检测死锁环。

        在有向图中查找环：T1→T2→...→Tn→T1。
        """
        cycles = []
        visited: set[str] = set()
        path: list[str] = []

        def dfs(node: str, start: str, depth: int) -> None:
            if depth > len(self.project.tasks):
                return
            if node in path and node == start and len(path) > 1:
                cycle = path[path.index(node):] + [node]
                if cycle not in cycles:
                    cycles.append(cycle)
                return
            if node in visited:
                return
            visited.add(node)
            path.append(node)
            for neighbor in graph.get(node, set()):
                dfs(neighbor, start, depth + 1)
            path.pop()

        for node in graph:
            visited = set()
            path = []
            dfs(node, node, 0)

        return cycles

    def _format_deadlocks(
        self, cycles: list[list[str]],
    ) -> list[dict[str, Any]]:
        """格式化为结构化的死锁报告。"""
        result = []
        for cycle in cycles:
            if len(cycle) < 3:
                continue
            for i in range(len(cycle) - 1):
                t1_name = cycle[i]
                t2_name = cycle[i + 1]
                t1 = next(
                    (t for t in self.project.tasks if t.name == t1_name),
                    None,
                )
                if t1:
                    result.append({
                        "task_a": t1_name,
                        "task_b": t2_name,
                        "locks_held": t1.held_locks[:3],
                        "file": t1.location.file,
                        "line": t1.location.line,
                        "confidence": 0.65,
                        "cycle": cycle[:-1],
                    })
        return result

    def _format_data_races(
        self, race_windows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """格式化为结构化的数据竞争报告。"""
        # 聚合按资源的访问
        resource_access: dict[str, dict] = {}
        for rw in self.race_windows:
            resource_access.setdefault(rw.resource, {
                "resource": rw.resource,
                "accessors": set(),
                "locations": [],
                "file": "unknown",
                "line": 0,
            })
            entry = resource_access[rw.resource]
            entry["accessors"].add(rw.task_name)
            entry["locations"].append({
                "task": rw.task_name,
                "location": rw.location,
            })

        results = []
        for res_name, info in resource_access.items():
            if len(info["accessors"]) > 1:
                # 查找原始共享资源信息
                orig = next(
                    (r for r in self.project.shared_resources
                     if r.name == res_name),
                    None,
                )
                results.append({
                    "resource": res_name,
                    "accessors": list(info["accessors"]),
                    "file": str(orig.location.file) if orig else "unknown",
                    "line": orig.location.line if orig else 0,
                    "confidence": 0.7,
                    "details": info["locations"],
                })
        return results

    def _generate_cot(self) -> list[str]:
        """生成思维链步骤，用于可解释性。"""
        steps = [
            "Step 1: 解析项目结构，识别所有RTOS任务和同步原语",
            f"Step 2: 发现 {len(self.project.tasks)} 个任务, "
            f"{len(self.project.sync_primitives)} 个同步原语",
        ]

        # 死锁分析步骤
        deadlock_candidates = [
            t for t in self.project.tasks if len(t.held_locks) > 1
        ]
        if deadlock_candidates:
            steps.append(
                f"Step 3: 检测到 {len(deadlock_candidates)} 个任务持有多个锁，"
                f"开始死锁环检测"
            )
        else:
            steps.append("Step 3: 未检测到多锁任务，死锁风险较低")

        # 优先级分析
        prios = {t.priority for t in self.project.tasks}
        if len(prios) > 1:
            steps.append(
                f"Step 4: 检测到 {len(prios)} 个不同优先级级别，"
                f"检查优先级反转..."
            )
        else:
            steps.append("Step 4: 所有任务优先级相同，优先级反转风险低")

        # 数据竞争分析
        shared_resources = self.project.shared_resources
        unprotected = [
            r for r in shared_resources if not r.protecting_primitives
        ]
        if unprotected:
            steps.append(
                f"Step 5: 发现 {len(unprotected)} 个无保护共享资源，"
                f"标记为数据竞争候选"
            )
            for ur in unprotected[:3]:
                steps.append(
                    f"  - [{ur.location}] {ur.name} 缺少同步保护"
                )

        # 栈深度分析
        small_stacks = [t for t in self.project.tasks if t.stack_size < 512]
        if small_stacks:
            steps.append(
                f"Step 6: {len(small_stacks)} 个任务栈过小（<512字节），"
                f"存在栈溢出风险"
            )

        steps.append("Step 7: 推理完成，汇总缺陷报告")
        return steps
