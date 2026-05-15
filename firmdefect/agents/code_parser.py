"""
代码解析Agent：扫描嵌入式工程（.c/.h/.s），提取任务调度表、共享资源互斥量、ISR入口。
"""
from __future__ import annotations

import re
import logging
from pathlib import Path

from firmdefect.models import (
    FirmwareProject, Task, SyncPrimitive, ISR,
    SharedResource, CriticalSection, SourceLocation,
    SyncPrimitiveType,
)

logger = logging.getLogger("firmdefect.parser")

# FreeRTOS 常用宏与API模式
FREERTOS_TASK_PATTERN = re.compile(
    r'xTaskCreate\s*\([^)]+\)',
    re.DOTALL,
)
FREERTOS_MUTEX_PATTERN = re.compile(
    r'(xSemaphoreCreateMutex|xSemaphoreCreateRecursiveMutex'
    r'|xQueueCreate|xSemaphoreCreateBinary)\s*\([^)]*\)',
)
FREERTOS_ISR_PATTERN = re.compile(
    r'(void\s+\w+_IRQHandler\s*\(|__irq\s+void|IRQn_Type)',
)
TASK_FUNCTION_PATTERN = re.compile(
    r'void\s+(\w+Task\w*|task_\w+|\w+_thread)\s*\(void\s*\*?\s*pvParameters\s*\)',
)
CRITICAL_SECTION_PATTERN = re.compile(
    r'(taskENTER_CRITICAL|taskEXIT_CRITICAL|portENTER_CRITICAL|portEXIT_CRITICAL'
    r'|__disable_irq|__enable_irq)',
)
MUTEX_TAKE_PATTERN = re.compile(
    r'(xSemaphoreTake|xQueueReceive)\s*\([^)]+\)',
)
MUTEX_GIVE_PATTERN = re.compile(
    r'(xSemaphoreGive|xQueueSend)\s*\([^)]+\)',
)
SHARED_VAR_PATTERN = re.compile(
    r'(volatile\s+)?(uint\d+_t|int\d+_t|float|double|char|struct)\s+\w+\s*'
    r'(__attribute__\(\(section\("\.(shared|bss|data)"\)\)\))?',
)


class CodeParserAgent:
    """
    代码解析Agent。
    扫描嵌入式工程文件，提取RTOS相关的结构化信息。
    """

    def __init__(self):
        self.project = FirmwareProject(root_path="")

    def parse_project(self, root_path: str | Path) -> FirmwareProject:
        """解析整个嵌入式工程。"""
        root_path = Path(root_path)
        self.project = FirmwareProject(root_path=str(root_path))

        source_files = []
        for ext in (".c", ".h", ".s", ".S"):
            source_files.extend(root_path.rglob(f"*{ext}"))

        # 过滤排除目录
        exclude_dirs = {"build", "out", "vendor", "third_party", ".git"}
        source_files = [
            f for f in source_files
            if not any(p in exclude_dirs for p in f.parts)
        ]

        total_lines = 0
        for file_path in source_files:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                lines = content.split("\n")
                total_lines += len(lines)
                self._parse_file(file_path, content, lines)
            except Exception as e:
                logger.warning("解析文件失败 %s: %s", file_path, e)

        self.project.files_scanned = len(source_files)
        self.project.total_lines = total_lines
        return self.project

    def _parse_file(self, file_path: Path, content: str, lines: list[str]) -> None:
        """解析单个源文件。"""
        rel_path = file_path.relative_to(self.project.root_path) if self.project.root_path else file_path

        self._extract_tasks(content, rel_path, lines)
        self._extract_sync_primitives(content, rel_path, lines)
        self._extract_isrs(content, rel_path, lines)
        self._extract_shared_resources(content, rel_path)
        self._extract_critical_sections(content, rel_path)

    def _extract_tasks(
        self, content: str, rel_path: Path, lines: list[str]
    ) -> None:
        """提取任务定义。"""
        for match in TASK_FUNCTION_PATTERN.finditer(content):
            name = match.group(1)
            line_no = content[:match.start()].count("\n") + 1
            # 估算优先级和栈大小（从xTaskCreate参数提取）
            priority = 1
            stack_size = 1024
            # 查找对应的xTaskCreate调用
            create_match = re.search(
                rf'xTaskCreate\s*\(\s*{re.escape(name)}\s*,',
                content,
            )
            if create_match:
                args = self._extract_function_args(content, create_match.end())
                if len(args) >= 6:
                    try:
                        stack_size = int(args[2])
                    except ValueError:
                        pass
                    try:
                        priority = int(args[4])
                    except ValueError:
                        pass

            self.project.tasks.append(Task(
                name=name,
                priority=priority,
                stack_size=stack_size,
                entry_point=name,
                location=SourceLocation(file=str(rel_path), line=line_no),
            ))

        # 也从 xTaskCreate 直接调用中提取
        for match in FREERTOS_TASK_PATTERN.finditer(content):
            args = self._extract_function_args(content, match.start() + len("xTaskCreate("))
            if len(args) >= 1:
                task_name = args[0].strip()
                # 检查是否已存在
                if not any(t.entry_point == task_name for t in self.project.tasks):
                    line_no = content[:match.start()].count("\n") + 1
                    try:
                        stack_size = int(args[2]) if len(args) > 2 else 1024
                    except ValueError:
                        stack_size = 1024
                    try:
                        priority = int(args[4]) if len(args) > 4 else 1
                    except ValueError:
                        priority = 1
                    self.project.tasks.append(Task(
                        name=f"task_{task_name}",
                        priority=priority,
                        stack_size=stack_size,
                        entry_point=task_name,
                        location=SourceLocation(file=str(rel_path), line=line_no),
                    ))

    def _extract_sync_primitives(
        self, content: str, rel_path: Path, lines: list[str]
    ) -> None:
        """提取同步原语。"""
        for match in FREERTOS_MUTEX_PATTERN.finditer(content):
            matched_text = match.group(0)
            line_no = content[:match.start()].count("\n") + 1

            if "RecursiveMutex" in matched_text:
                prim_type = SyncPrimitiveType.RECURSIVE_MUTEX
            elif "Binary" in matched_text or "binary" in matched_text:
                prim_type = SyncPrimitiveType.BINARY_SEMAPHORE
            elif "Mutex" in matched_text or "mutex" in matched_text:
                prim_type = SyncPrimitiveType.MUTEX
            elif "Queue" in matched_text:
                prim_type = SyncPrimitiveType.QUEUE
            else:
                prim_type = SyncPrimitiveType.SEMAPHORE

            # 尝试从赋值左侧提取名称
            before = content[max(0, match.start() - 50):match.start()]
            name_match = re.search(r'(\w+)\s*=\s*$', before)
            name = name_match.group(1) if name_match else f"sync_{prim_type.value}_{line_no}"

            # 检查是否已存在
            if not any(s.name == name for s in self.project.sync_primitives):
                self.project.sync_primitives.append(SyncPrimitive(
                    name=name,
                    type=prim_type,
                    location=SourceLocation(file=str(rel_path), line=line_no),
                    priority_inheritance=(
                        prim_type == SyncPrimitiveType.MUTEX
                    ),
                ))

    def _extract_isrs(
        self, content: str, rel_path: Path, lines: list[str]
    ) -> None:
        """提取中断服务函数。"""
        for i, line in enumerate(lines):
            stripped = line.strip()
            # 匹配 IRQHandler
            if "_IRQHandler" in stripped:
                name_match = re.search(r'(\w+_IRQHandler)', stripped)
                if name_match:
                    name = name_match.group(1)
                    if not any(isr.name == name for isr in self.project.isrs):
                        self.project.isrs.append(ISR(
                            name=name,
                            vector=0,
                            priority=self._estimate_isr_priority(name),
                            location=SourceLocation(
                                file=str(rel_path), line=i + 1,
                            ),
                        ))

    def _extract_shared_resources(
        self, content: str, rel_path: Path
    ) -> None:
        """提取共享资源（全局变量、共享内存等）。"""
        for match in SHARED_VAR_PATTERN.finditer(content):
            line_no = content[:match.start()].count("\n") + 1
            # 提取变量名
            after_type = content[match.end():match.end() + 60]
            var_match = re.search(r'\b(\w+)\b', after_type)
            if var_match:
                name = var_match.group(1)
                if not any(r.name == name for r in self.project.shared_resources):
                    self.project.shared_resources.append(SharedResource(
                        name=name,
                        type="variable",
                        location=SourceLocation(file=str(rel_path), line=line_no),
                    ))

    def _extract_critical_sections(
        self, content: str, rel_path: Path
    ) -> None:
        """提取临界区。"""
        for match in CRITICAL_SECTION_PATTERN.finditer(content):
            line_no = content[:match.start()].count("\n") + 1
            direction = "enter" if "ENTER" in match.group(0) else "exit"
            prim_name = f"critical_section_{line_no}"

            self.project.critical_sections.append(CriticalSection(
                function=self._find_enclosing_function(content, line_no),
                location=SourceLocation(file=str(rel_path), line=line_no),
                lock=prim_name,
                start_line=line_no,
                end_line=line_no,
                nested_depth=0,
            ))

    # ── 辅助方法 ──

    def _extract_function_args(self, content: str, start_pos: int) -> list[str]:
        """提取函数调用的参数列表（处理嵌套括号）。"""
        depth = 0
        args = []
        current = []
        in_arg = False
        for i in range(start_pos, min(start_pos + 500, len(content))):
            ch = content[i]
            if ch == '(':
                depth += 1
                if depth > 1:
                    current.append(ch)
            elif ch == ')':
                depth -= 1
                if depth < 0:
                    break
                if depth == 0:
                    if current:
                        args.append(''.join(current).strip())
                    break
                current.append(ch)
            elif ch == ',' and depth == 1:
                args.append(''.join(current).strip())
                current = []
            else:
                current.append(ch)
        return args

    def _find_enclosing_function(self, content: str, line_no: int) -> str:
        """查找指定行所在的函数名。"""
        lines = content.split('\n')
        for i in range(min(line_no - 1, len(lines) - 1), -1, -1):
            m = re.match(r'^\s*(?:static\s+)?\w+(?:\s*\*+)?\s+(\w+)\s*\(', lines[i])
            if m:
                return m.group(1)
        return "unknown"

    def _estimate_isr_priority(self, name: str) -> int:
        """根据ISR名称估算优先级。"""
        if "TIM" in name or "TIMER" in name:
            return 3
        if "UART" in name or "USART" in name:
            return 5
        if "DMA" in name:
            return 4
        if "EXTI" in name or "GPIO" in name:
            return 6
        if "ETH" in name or "MAC" in name:
            return 2
        if "SYSTICK" in name or "PendSV" in name:
            return 1
        return 7
