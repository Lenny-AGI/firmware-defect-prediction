"""FirmDefect - Multi-Agent Embedded Firmware Defect Prediction & Repair System"""
from setuptools import setup, find_packages

setup(
    name="firmdefect",
    version="0.1.0",
    description="Multi-Agent Collaborative Embedded Firmware Defect Prediction & Automated Repair System",
    author="FirmDefect Team",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "pydantic>=2.0.0",
        "pyyaml>=6.0",
        "rich>=13.0.0",
        "typer>=0.9.0",
        "openai>=1.0.0",
        "httpx>=0.25.0",
    ],
    entry_points={
        "console_scripts": [
            "firmdefect=core.orchestrator:app",
        ],
    },
)
