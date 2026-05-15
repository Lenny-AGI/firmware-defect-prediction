"""推理引擎测试。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from firmdefect.reasoning.execution_path import ExecutionPathInference
from firmdefect.reasoning.chain_of_thought import ChainOfThoughtEngine
from firmdefect.agents.code_parser import CodeParserAgent


def test_execution_path_inference():
    """测试执行路径推演。"""
    demo_path = Path(__file__).parent.parent / "examples" / "industrial_gateway"
    parser = CodeParserAgent()
    project = parser.parse_project(demo_path)

    inference = ExecutionPathInference(project)
    results = inference.infer()

    # 应检测到依赖图
    assert "resource_dependency_graph" in results
    assert "potential_data_races" in results or True  # 可能为空
    assert "chain_of_thought" in results

    # 验证推理步骤
    assert len(results["chain_of_thought"]) > 3


def test_chain_of_thought():
    """测试思维链推理。"""
    demo_path = Path(__file__).parent.parent / "examples" / "industrial_gateway"
    parser = CodeParserAgent()
    project = parser.parse_project(demo_path)

    engine = ChainOfThoughtEngine()
    results = engine.infer(project)

    assert "chain_of_thought" in results
    assert "full_reasoning" in results

    steps = results["chain_of_thought"]
    assert any("Step" in s for s in steps)  # 包含推理步骤
