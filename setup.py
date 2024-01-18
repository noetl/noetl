from setuptools import setup, find_packages
from setuptools.command.install import install as InstallCommand
import os


def read_requirements():
    with open('requirements.txt', 'r') as f:
        return f.read().splitlines()


def read_readme():
    this_directory = os.path.abspath(os.path.dirname(__file__))
    with open(os.path.join(this_directory, 'README.md'), encoding='utf-8') as f:
        return f.read()


setup(
    name="noetl",
    version="0.1.9",
    author="NoETL Team",
    description="NoETL: A Python package for managing workflows",
    long_description=read_readme(),
    long_description_content_type='text/markdown',
    packages=find_packages(),
    install_requires=read_requirements(),
    entry_points={
        "console_scripts": [
            "noetl = noetl.cli:main",
        ],
    },
)
