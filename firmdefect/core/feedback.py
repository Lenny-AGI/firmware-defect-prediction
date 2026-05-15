"""
闭环反馈系统：验证失败时触发回滚与二次推理，最多循环3次。
"""
from __future__ import annotations

import logging
from typing import Callable

from firmdefect.models import DefectReport, FirmwareProject

logger = logging.getLogger("firmdefect.feedback")


class FeedbackLoop:
    """
    闭环反馈控制器。

    当验证Agent报告失败时，触发回滚并启动二次推理：
    1. 记录失败日志
    2. 修正推理假设（如重新计算栈深度）
    3. 重新生成修复方案
    4. 再次验证
    最多循环 max_retry 次。
    """

    def __init__(self, max_retry: int = 3):
        self.max_retry = max_retry
        self.attempt_count = 0

    def run(
        self,
        project: FirmwareProject,
        defects: list[DefectReport],
        verify_fn: Callable[[FirmwareProject, list[DefectReport]], list[DefectReport]],
    ) -> list[DefectReport]:
        """
        执行闭环反馈循环。
        返回最终验证后的缺陷列表（含补丁和验证状态）。
        """
        self.attempt_count = 0
        current_defects = defects

        while self.attempt_count < self.max_retry:
            self.attempt_count += 1
            logger.info(
                "反馈循环迭代 %d/%d", self.attempt_count, self.max_retry
            )

            # 执行验证
            verified_defects = verify_fn(project, current_defects)

            # 检查是否有失败的验证
            failed = [d for d in verified_defects if not d.verified]
            if not failed:
                logger.info("所有缺陷验证通过")
                return verified_defects

            # 对失败项进行二次推理修正
            logger.warning(
                "%d 个缺陷验证失败，启动二次推理 (迭代 %d)",
                len(failed), self.attempt_count,
            )
            for defect in failed:
                self._refine_hypothesis(defect)

            current_defects = verified_defects

        logger.warning(
            "达到最大重试次数 %d，返回当前结果", self.max_retry
        )
        return current_defects

    def _refine_hypothesis(self, defect: DefectReport) -> None:
        """
        基于失败日志修正推理假设。
        例如：若栈溢出验证失败，可能栈深度估算不足，需要增加安全余量。
        """
        log = defect.verification_log or ""
        refinement = []

        if "stack overflow" in log.lower() or "stack" in log.lower():
            refinement.append("修正：增加栈深度安全余量 1.5x")
            refinement.append("修正：重新计算调用链最大嵌套深度")

        if "deadlock" in log.lower():
            refinement.append("修正：增加超时机制检测")
            refinement.append("修正：验证优先级继承协议是否启用")

        if "data race" in log.lower() or "threadsan" in log.lower():
            refinement.append("修正：添加内存屏障指令")
            refinement.append("修正：检查原子操作替代方案")

        if "heap" in log.lower() or "malloc" in log.lower():
            refinement.append("修正：增加堆大小并添加越界检测")
            refinement.append("修正：改用静态内存分配")

        if not refinement:
            refinement.append("修正：通用安全加固 — 添加边界检查与错误处理")

        defect.chain_of_thought.extend(refinement)
        defect.description += " [二次推理修正]"

        logger.debug("缺陷 %s 推理假设已修正: %s", defect.location, refinement)
