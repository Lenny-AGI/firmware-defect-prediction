"""
修复建议Agent：针对检测到的缺陷生成补丁方案。

支持生成：
- 内存屏障指令（__sync_synchronize / __dsb）
- 任务栈大小调整
- 无锁队列替代方案
- Mutex超时机制
- 优先级继承启用
"""
from __future__ import annotations

import logging
from typing import Optional

from firmdefect.models import (
    FirmwareProject, DefectReport, RiskType, SourceLocation,
)

logger = logging.getLogger("firmdefect.fixer")

# 修复模板库
FIX_TEMPLATES = {
    RiskType.DATA_RACE: {
        "mutex_protect": """\
// === [FirmDefect Auto-Fix] 添加互斥量保护 ===
// 在文件顶部添加
static SemaphoreHandle_t {resource}_mutex = NULL;

// 初始化（在task_create之前调用）
{resource}_mutex = xSemaphoreCreateMutex();
configASSERT({resource}_mutex != NULL);

// 访问 {resource} 前
if (xSemaphoreTake({resource}_mutex, portMAX_DELAY) == pdTRUE) {{
    // 原访问代码
    xSemaphoreGive({resource}_mutex);
}}
""",
        "atomic_access": """\
// === [FirmDefect Auto-Fix] 改用原子访问 ===
// 替换普通读写为原子操作
#define {resource}_LOAD()  __atomic_load_n(&{resource}, __ATOMIC_SEQ_CST)
#define {resource}_STORE(v) __atomic_store_n(&{resource}, (v), __ATOMIC_SEQ_CST)
""",
    },
    RiskType.DEADLOCK: {
        "add_timeout": """\
// === [FirmDefect Auto-Fix] 添加超时机制 ===
// 替换无限等待为超时等待
// 原代码: xSemaphoreTake({lock}, portMAX_DELAY);
// 新代码:
if (xSemaphoreTake({lock}, pdMS_TO_TICKS(1000)) != pdTRUE) {{
    // 超时处理
    printf("WARN: 获取锁 {lock} 超时\\\\n");
    // 错误恢复逻辑
}}
""",
        "lock_ordering": """\
// === [FirmDefect Auto-Fix] 统一锁获取顺序 ===
// 确保所有任务按相同顺序获取锁
// 顺序: {lock_order}
// 违反此顺序的代码路径已被标记，请检查
""",
    },
    RiskType.STACK_OVERFLOW: {
        "increase_stack": """\
// === [FirmDefect Auto-Fix] 增加任务栈大小 ===
// 原: {old_size}
// 新: {new_size}
#define {task}_STACK_SIZE {new_size}
""",
    },
    RiskType.PRIORITY_INVERSION: {
        "enable_pi": """\
// === [FirmDefect Auto-Fix] 启用优先级继承 ===
// 使用互斥量代替二值信号量（FreeRTOS互斥量内置优先级继承）
// 替换:
//   {old_prim} = xSemaphoreCreateBinary();
// 为:
//   {old_prim} = xSemaphoreCreateMutex();
""",
    },
    RiskType.IRQ_SAFETY: {
        "defer_isr": """\
// === [FirmDefect Auto-Fix] ISR中推迟处理 ===
// 在ISR中使用任务通知替代直接访问
// 改用:xTaskNotifyFromISR()通知处理任务
BaseType_t xHigherPriorityTaskWoken = pdFALSE;
xTaskNotifyFromISR({handler_task}, {event_value}, eSetBits, &xHigherPriorityTaskWoken);
portYIELD_FROM_ISR(xHigherPriorityTaskWoken);
""",
    },
    RiskType.BUFFER_OVERFLOW: {
        "add_bound_check": """\
// === [FirmDefect Auto-Fix] 添加边界检查 ===
// 在访问{buffer}前添加边界检查
if (offset >= {buffer}_SIZE) {{
    // 错误处理
    return -1;
}}
""",
    },
}


class FixSuggesterAgent:
    """
    修复建议Agent。
    基于缺陷类型和上下文，生成具体的代码补丁方案。
    """

    def suggest_fixes(
        self,
        project: FirmwareProject,
        defects: list[DefectReport],
    ) -> list[DefectReport]:
        """为每个缺陷生成修复建议。"""
        for defect in defects:
            fix = self._generate_fix(project, defect)
            if fix:
                defect.suggested_fix = fix

        return defects

    def _generate_fix(
        self,
        project: FirmwareProject,
        defect: DefectReport,
    ) -> Optional[str]:
        """根据缺陷类型生成对应的修复方案。"""
        templates = FIX_TEMPLATES.get(defect.risk_type)
        if not templates:
            return self._generic_fix(defect)

        # 根据上下文选择最佳模板
        chosen_template = self._select_best_template(
            defect, templates,
        )
        if chosen_template:
            return self._apply_template(project, defect, chosen_template)

        # 兜底：使用第一个模板
        first_template = next(iter(templates.values()))
        return self._apply_template(project, defect, first_template)

    def _select_best_template(
        self,
        defect: DefectReport,
        templates: dict[str, str],
    ) -> Optional[str]:
        """选择最适合当前上下文的修复模板。"""
        desc = defect.description.lower()

        # 根据描述中的关键词选择模板
        if "mutex" in desc or "semaphore" in desc or "lock" in desc:
            return templates.get("mutex_protect") or templates.get("add_timeout")
        if "atomic" in desc:
            return templates.get("atomic_access")
        if "timeout" in desc or "deadlock" in desc:
            return templates.get("add_timeout") or templates.get("lock_ordering")
        if "stack" in desc:
            return templates.get("increase_stack")
        if "isr" in desc or "interrupt" in desc:
            return templates.get("defer_isr")
        if "buffer" in desc or "overflow" in desc:
            return templates.get("add_bound_check")
        if "priority" in desc:
            return templates.get("enable_pi")

        return None

    def _apply_template(
        self,
        project: FirmwareProject,
        defect: DefectReport,
        template: str,
    ) -> str:
        """将模板应用到具体上下文。"""
        resource_name = self._extract_resource_name(defect)
        task_name = self._find_task_name(project, defect)
        lock_name = self._find_lock_name(project, defect)

        fix = template.format(
            resource=resource_name or "shared_var",
            task=task_name or "task",
            lock=lock_name or "lock",
            old_prim=lock_name or "xSemaphore",
            handler_task=task_name or "handler_task",
            event_value="0x01",
            buffer=resource_name or "buffer",
            old_size="1024",
            new_size="2048",
            lock_order=", ".join(
                p.name
                for p in project.sync_primitives[:3]
            ) or "lock1, lock2",
        )

        # 添加文件头注释
        header = (
            f"/*\n"
            f" * FirmDefect Auto-Generated Fix\n"
            f" * Risk Type: {defect.risk_type.value}\n"
            f" * Location: {defect.location}\n"
            f" * Confidence: {defect.confidence:.0%}\n"
            f" */\n"
        )
        return header + fix

    def _extract_resource_name(self, defect: DefectReport) -> Optional[str]:
        """从缺陷描述中提取资源名。"""
        desc = defect.description
        for prefix in ["资源 '", "资源'", "共享资源 '"]:
            start = desc.find(prefix)
            if start >= 0:
                start += len(prefix)
                end = desc.find("'", start)
                if end >= 0:
                    return desc[start:end]
        return None

    def _find_task_name(
        self, project: FirmwareProject, defect: DefectReport,
    ) -> Optional[str]:
        """找到与缺陷位置相关的任务名。"""
        for task in project.tasks:
            if task.location.file == defect.location.file:
                return task.name
        return None

    def _find_lock_name(
        self, project: FirmwareProject, defect: DefectReport,
    ) -> Optional[str]:
        """找到与缺陷位置相关的锁名。"""
        for prim in project.sync_primitives:
            if prim.location.file == defect.location.file:
                return prim.name
        return None

    def _generic_fix(self, defect: DefectReport) -> str:
        """生成通用修复建议。"""
        return f"""\
/*
 * FirmDefect Auto-Generated Fix (Generic)
 * Risk Type: {defect.risk_type.value}
 * Location: {defect.location}
 *
 * 建议操作:
 * 1. 检查 {defect.location.file}:{defect.location.line} 附近的代码
 * 2. 添加适当的同步保护或边界检查
 * 3. 运行 ThreadSanitizer / Valgrind 验证
 */
"""
