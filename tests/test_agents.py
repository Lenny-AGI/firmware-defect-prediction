"""Agent集成测试。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from firmdefect.agents.code_parser import CodeParserAgent
from firmdefect.agents.defect_locator import DefectLocatorAgent
from firmdefect.agents.fix_suggester import FixSuggesterAgent
from firmdefect.agents.verifier import VerifierAgent
from firmdefect.reasoning.chain_of_thought import ChainOfThoughtEngine


def test_defect_locator():
    """测试缺陷定位Agent。"""
    demo_path = Path(__file__).parent.parent / "examples" / "industrial_gateway"
    parser = CodeParserAgent()
    project = parser.parse_project(demo_path)

    engine = ChainOfThoughtEngine()
    inference_results = engine.infer(project)

    locator = DefectLocatorAgent()
    defects = locator.locate(project, inference_results)

    assert len(defects) > 0

    # 应检测到特定缺陷
    risk_types = [d.risk_type.value for d in defects]
    # 至少应检测到: data_race, stack_overflow 等
    assert "data_race" in risk_types or "stack_overflow" in risk_types

    # 验证置信度范围
    for d in defects:
        assert 0.0 <= d.confidence <= 1.0

    # 验证风险位置非空
    for d in defects:
        assert d.location.file


def test_fix_suggester():
    """测试修复建议Agent。"""
    demo_path = Path(__file__).parent.parent / "examples" / "industrial_gateway"
    parser = CodeParserAgent()
    project = parser.parse_project(demo_path)

    engine = ChainOfThoughtEngine()
    inference_results = engine.infer(project)

    locator = DefectLocatorAgent()
    defects = locator.locate(project, inference_results)

    fixer = FixSuggesterAgent()
    defects = fixer.suggest_fixes(project, defects)

    for d in defects:
        assert d.suggested_fix is not None
        assert "FirmDefect" in d.suggested_fix


def test_verifier_static():
    """测试静态验证模式。"""
    demo_path = Path(__file__).parent.parent / "examples" / "industrial_gateway"
    parser = CodeParserAgent()
    project = parser.parse_project(demo_path)

    engine = ChainOfThoughtEngine()
    inference_results = engine.infer(project)

    locator = DefectLocatorAgent()
    defects = locator.locate(project, inference_results)

    fixer = FixSuggesterAgent()
    defects = fixer.suggest_fixes(project, defects)

    verifier = VerifierAgent()
    defects = verifier.verify(project, defects)

    for d in defects:
        assert d.verification_log is not None
