"""代码解析Agent测试。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from firmdefect.agents.code_parser import CodeParserAgent


def test_parse_industrial_gateway():
    """测试解析示例项目。"""
    demo_path = Path(__file__).parent.parent / "examples" / "industrial_gateway"
    parser = CodeParserAgent()
    project = parser.parse_project(demo_path)

    assert project.files_scanned >= 3  # main.c, uart_driver.c, uart_driver.h
    assert project.total_lines > 100

    # 验证任务提取
    task_names = [t.name for t in project.tasks]
    assert "vSensorTask" in task_names
    assert "vReportTask" in task_names
    assert "vEthRxTask" in task_names
    assert "vLoggerTask" in task_names
    assert "vCmdTask" in task_names

    # 验证同步原语提取
    prim_names = [p.name for p in project.sync_primitives]
    assert "xEthMutex" in prim_names
    assert "xSensorMutex" in prim_names

    # 验证ISR提取
    isr_names = [i.name for i in project.isrs]
    assert "DMA_IRQHandler" in isr_names
    assert "TIM3_IRQHandler" in isr_names

    # 验证共享资源
    assert len(project.shared_resources) > 0

    # 验证优先级
    sensor_task = next(t for t in project.tasks if t.name == "vSensorTask")
    assert sensor_task.priority == 1  # 最高优先级


def test_task_stack_sizes():
    """验证任务栈大小提取。"""
    demo_path = Path(__file__).parent.parent / "examples" / "industrial_gateway"
    parser = CodeParserAgent()
    project = parser.parse_project(demo_path)

    logger_task = next(
        (t for t in project.tasks if t.name == "vLoggerTask"), None
    )
    assert logger_task is not None
    assert logger_task.stack_size >= 128  # DF003: 栈过小
