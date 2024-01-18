from setuptools import setup, find_packages
from setuptools.command.install import install as InstallCommand

def read_requirements():
    with open('requirements.txt', 'r') as f:
        return f.read().splitlines()

setup(
    name="noetl",
    version="0.1.7",
    author="NoETL Team",
    description="NoETL: A Python package for managing workflows",
    packages=find_packages(),
    install_requires=read_requirements(),
    entry_points={
        "console_scripts": [
            "noetl = noetl.cli:main",
        ],
    },
)
