"""
核心数据模型：表示嵌入式固件中的各类抽象结构。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


# ──────────────────────────────────────────────
# 符号与资源
# ──────────────────────────────────────────────

class RiskSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskType(Enum):
    DATA_RACE = "data_race"
    DEADLOCK = "deadlock"
    STACK_OVERFLOW = "stack_overflow"
    BUFFER_OVERFLOW = "buffer_overflow"
    PRIORITY_INVERSION = "priority_inversion"
    USE_AFTER_FREE = "use_after_free"
    DOUBLE_FREE = "double_free"
    NULL_DEREFERENCE = "null_dereference"
    MISSING_LOCK = "missing_lock"
    IRQ_SAFETY = "irq_safety"


class SyncPrimitiveType(Enum):
    MUTEX = "mutex"
    SEMAPHORE = "semaphore"
    RECURSIVE_MUTEX = "recursive_mutex"
    BINARY_SEMAPHORE = "binary_semaphore"
    SPINLOCK = "spinlock"
    QUEUE = "queue"


class TaskState(Enum):
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    SUSPENDED = "suspended"
    DELETED = "deleted"


@dataclass
class SourceLocation:
    """源代码位置"""
    file: str
    line: int
    column: int = 0

    def __str__(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass
class Task:
    """RTOS 任务控制块"""
    name: str
    priority: int
    stack_size: int
    entry_point: str
    location: SourceLocation
    state: TaskState = TaskState.READY
    held_locks: list[str] = field(default_factory=list)
    blocked_on: Optional[str] = None


@dataclass
class SyncPrimitive:
    """同步原语（互斥量/信号量/队列）"""
    name: str
    type: SyncPrimitiveType
    location: SourceLocation
    owner: Optional[str] = None
    waiters: list[str] = field(default_factory=list)
    is_recursive: bool = False
    priority_inheritance: bool = False


@dataclass
class ISR:
    """中断服务函数"""
    name: str
    vector: int
    priority: int
    location: SourceLocation
    shared_resources: list[str] = field(default_factory=list)


@dataclass
class SharedResource:
    """共享资源"""
    name: str
    type: str  # "memory", "register", "fifo", "variable"
    location: SourceLocation
    protecting_primitives: list[str] = field(default_factory=list)
    accessed_by: list[str] = field(default_factory=list)  # task/isr names


@dataclass
class CriticalSection:
    """临界区"""
    function: str
    location: SourceLocation
    lock: str
    start_line: int
    end_line: int
    nested_depth: int = 0
    shared_resources: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────
# 分析结果
# ──────────────────────────────────────────────

@dataclass
class DefectReport:
    """单一缺陷报告"""
    risk_type: RiskType
    severity: RiskSeverity
    location: SourceLocation
    description: str
    confidence: float  # 0.0 - 1.0
    chain_of_thought: list[str] = field(default_factory=list)
    suggested_fix: Optional[str] = None
    fix_file: Optional[str] = None
    verified: bool = False
    verification_log: Optional[str] = None


@dataclass
class FirmwareProject:
    """嵌入式固件工程的完整表示"""
    root_path: str
    tasks: list[Task] = field(default_factory=list)
    sync_primitives: list[SyncPrimitive] = field(default_factory=list)
    isrs: list[ISR] = field(default_factory=list)
    shared_resources: list[SharedResource] = field(default_factory=list)
    critical_sections: list[CriticalSection] = field(default_factory=list)
    files_scanned: int = 0
    total_lines: int = 0

    @property
    def task_count(self) -> int:
        return len(self.tasks)

    @property
    def has_deadlock_potential(self) -> bool:
        """检查是否存在死锁的可能性（多个锁 + 多个任务）"""
        multi_lock_tasks = sum(1 for t in self.tasks if len(t.held_locks) > 1)
        return multi_lock_tasks >= 2


@dataclass
class AnalysisReport:
    """完整分析报告"""
    project: FirmwareProject
    defects: list[DefectReport] = field(default_factory=list)
    execution_time_seconds: float = 0.0
    iterations: int = 1
    total_tokens_used: int = 0

    @property
    def high_severity_count(self) -> int:
        return sum(
            1 for d in self.defects
            if d.severity in (RiskSeverity.HIGH, RiskSeverity.CRITICAL)
        )

    @property
    def verified_fixes(self) -> int:
        return sum(1 for d in self.defects if d.verified)
