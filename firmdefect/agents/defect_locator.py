"""
缺陷定位Agent：根据推理结果生成具体风险点列表（文件名+行号+风险类型）。
"""
from __future__ import annotations

import logging
from typing import Any

from firmdefect.models import (
    FirmwareProject, DefectReport, RiskSeverity, RiskType,
    SourceLocation, SyncPrimitiveType,
)

logger = logging.getLogger("firmdefect.locator")


class DefectLocatorAgent:
    """
    缺陷定位Agent。
    结合代码解析结果和推理引擎的输出，生成结构化的风险点列表。
    """

    def locate(
        self,
        project: FirmwareProject,
        inference_results: dict[str, Any],
    ) -> list[DefectReport]:
        """
        定位缺陷。
        基于推理结果和工程模型，生成缺陷报告列表。
        """
        defects: list[DefectReport] = []
        seen_locations: set[str] = set()

        # 1. 检查推理引擎报告的潜在死锁
        deadlocks = inference_results.get("potential_deadlocks", [])
        for dl in deadlocks:
            loc_key = f"{dl.get('file', '')}:{dl.get('line', 0)}"
            if loc_key not in seen_locations:
                seen_locations.add(loc_key)
                defects.append(DefectReport(
                    risk_type=RiskType.DEADLOCK,
                    severity=RiskSeverity.HIGH,
                    location=SourceLocation(
                        file=dl.get("file", "unknown"),
                        line=dl.get("line", 0),
                    ),
                    description=(
                        f"潜在死锁: 任务 {dl.get('task_a', '?')} "
                        f"持有{', '.join(dl.get('locks_held', []))}, "
                        f"任务 {dl.get('task_b', '?')} 等待同一资源"
                    ),
                    confidence=dl.get("confidence", 0.7),
                ))

        # 2. 检查推理引擎报告的数据竞争
        data_races = inference_results.get("potential_data_races", [])
        for dr in data_races:
            loc_key = f"{dr.get('file', '')}:{dr.get('line', 0)}"
            if loc_key not in seen_locations:
                seen_locations.add(loc_key)
                defects.append(DefectReport(
                    risk_type=RiskType.DATA_RACE,
                    severity=RiskSeverity.HIGH,
                    location=SourceLocation(
                        file=dr.get("file", "unknown"),
                        line=dr.get("line", 0),
                    ),
                    description=(
                        f"数据竞争: 资源 '{dr.get('resource', '?')}' "
                        f"被 {dr.get('accessors', [])} 并发访问"
                        f"（缺少同步保护）"
                    ),
                    confidence=dr.get("confidence", 0.65),
                ))

        # 3. 分析工程模型检测模式
        defects.extend(self._check_deadlock_patterns(project, seen_locations))
        defects.extend(self._check_data_race_patterns(project, seen_locations))
        defects.extend(self._check_stack_overflow(project, seen_locations))
        defects.extend(self._check_priority_inversion(project, seen_locations))
        defects.extend(self._check_irq_safety(project, seen_locations))

        # 去重并排序
        seen_types: dict[str, DefectReport] = {}
        for d in defects:
            key = f"{d.risk_type.value}:{d.location}"
            if key not in seen_types or d.confidence > seen_types[key].confidence:
                seen_types[key] = d
        result = sorted(
            seen_types.values(),
            key=lambda d: (-d.severity.value, -d.confidence),
        )
        return result

    def _check_deadlock_patterns(
        self, project: FirmwareProject,
        seen: set[str],
    ) -> list[DefectReport]:
        """检测死锁模式：多锁嵌套 + 不同获取顺序。"""
        defects = []
        if len(project.tasks) < 2 or len(project.sync_primitives) < 2:
            return defects

        # 简单检测：如果有多个任务持有多个锁，可能存在死锁风险
        multi_lock_tasks = [
            t for t in project.tasks if len(t.held_locks) > 1
        ]
        if len(multi_lock_tasks) >= 2:
            for mt in multi_lock_tasks[:2]:
                key = f"deadlock:{mt.location}"
                if key not in seen:
                    seen.add(key)
                    defects.append(DefectReport(
                        risk_type=RiskType.DEADLOCK,
                        severity=RiskSeverity.MEDIUM,
                        location=mt.location,
                        description=(
                            f"任务 '{mt.name}' 持有多个锁 "
                            f"({', '.join(mt.held_locks)})，"
                            f"存在潜在死锁风险"
                        ),
                        confidence=0.6,
                    ))

        # 检查嵌套临界区
        cs_groups: dict[str, list] = {}
        for cs in project.critical_sections:
            cs_groups.setdefault(cs.function, []).append(cs)
        for func, sections in cs_groups.items():
            if len(sections) > 4:  # 过多的临界区嵌套
                key = f"deadlock:{sections[0].location}"
                if key not in seen:
                    seen.add(key)
                    defects.append(DefectReport(
                        risk_type=RiskType.DEADLOCK,
                        severity=RiskSeverity.LOW,
                        location=sections[0].location,
                        description=(
                            f"函数 '{func}' 包含 {len(sections)} 个临界区，"
                            f"可能存在嵌套锁风险"
                        ),
                        confidence=0.4,
                    ))

        return defects

    def _check_data_race_patterns(
        self, project: FirmwareProject,
        seen: set[str],
    ) -> list[DefectReport]:
        """检测数据竞争模式：共享资源访问无保护。"""
        defects = []
        for res in project.shared_resources:
            if not res.protecting_primitives and len(res.accessed_by) > 1:
                key = f"data_race:{res.location}"
                if key not in seen:
                    seen.add(key)
                    accessors = res.accessed_by[:5]
                    defects.append(DefectReport(
                        risk_type=RiskType.DATA_RACE,
                        severity=RiskSeverity.HIGH,
                        location=res.location,
                        description=(
                            f"共享资源 '{res.name}' 被 {accessors} 访问"
                            f"但缺少同步保护原语"
                        ),
                        confidence=0.75,
                    ))
        return defects

    def _check_stack_overflow(
        self, project: FirmwareProject, seen: set[str],
    ) -> list[DefectReport]:
        """检测栈溢出风险。"""
        defects = []
        for task in project.tasks:
            if task.stack_size < 512:
                key = f"stack_overflow:{task.location}"
                if key not in seen:
                    seen.add(key)
                    defects.append(DefectReport(
                        risk_type=RiskType.STACK_OVERFLOW,
                        severity=(
                            RiskSeverity.CRITICAL
                            if task.stack_size < 256
                            else RiskSeverity.HIGH
                        ),
                        location=task.location,
                        description=(
                            f"任务 '{task.name}' 栈大小仅为 {task.stack_size} 字节，"
                            f"低于建议最小值 512 字节"
                        ),
                        confidence=0.7,
                    ))
        return defects

    def _check_priority_inversion(
        self, project: FirmwareProject, seen: set[str],
    ) -> list[DefectReport]:
        """检测优先级反转。"""
        defects = []
        for prim in project.sync_primitives:
            if prim.type == SyncPrimitiveType.MUTEX:
                if not prim.priority_inheritance:
                    # 检查是否有不同优先级的任务等待该锁
                    waiters = prim.waiters
                    if len(waiters) >= 2:
                        key = f"priority_inversion:{prim.location}"
                        if key not in seen:
                            seen.add(key)
                            defects.append(DefectReport(
                                risk_type=RiskType.PRIORITY_INVERSION,
                                severity=RiskSeverity.MEDIUM,
                                location=prim.location,
                                description=(
                                    f"互斥量 '{prim.name}' 未启用优先级继承协议，"
                                    f"在 {len(waiters)} 个任务间使用"
                                    f"（任务: {waiters}），可能存在优先级反转"
                                ),
                                confidence=0.55,
                            ))
        return defects

    def _check_irq_safety(
        self, project: FirmwareProject, seen: set[str],
    ) -> list[DefectReport]:
        """检测ISR安全性问题。"""
        defects = []
        for isr in project.isrs:
            if isr.shared_resources:
                key = f"irq_safety:{isr.location}"
                if key not in seen:
                    seen.add(key)
                    defects.append(DefectReport(
                        risk_type=RiskType.IRQ_SAFETY,
                        severity=RiskSeverity.HIGH,
                        location=isr.location,
                        description=(
                            f"ISR '{isr.name}' 访问共享资源 "
                            f"{isr.shared_resources}，需确保 ISR-safe 同步"
                        ),
                        confidence=0.6,
                    ))
        return defects
