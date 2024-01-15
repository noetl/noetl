from setuptools import setup, find_packages
from setuptools.command.install import install as InstallCommand
import subprocess


class CustomInstallCommand(InstallCommand):
    def run(self):
        subprocess.call(["python", "spacy_download.py"])
        super().run()


setup(
    name="noetl",
    version="0.1.2",
    author="NoETL Team",
    description="NoETL: A Python package for managing workflows",
    packages=find_packages(),
    install_requires=[
        "asyncio==3.4.3",
        "loguru==0.7.2",
        "aiohttp==3.9.1",
        "pyyaml==6.0",
        "requests>=2.31.0",
        "spacy==3.6.1",
        "psutil==5.9.5",
        "fastapi==0.103.1",
        "uvicorn==0.23.2",
        "nats-py==2.6.0",
        "strawberry-graphql==0.211.1",
        "aioprometheus[aiohttp]==23.3.0",
        "aioprometheus[binary]==23.3.0"
    ],
    entry_points={
        "console_scripts": [
            "noetl = noetl.cli:main",
        ],
    },
    cmdclass={
        "install": CustomInstallCommand,
    },
)
