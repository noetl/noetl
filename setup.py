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
    version="0.1.18",
    author="NoETL Team",
    author_email="182583029+kadyapam@users.noreply.github.com",
    description="notOnlyExtractTransformLoadFramework",
    long_description=read_readme(),
    long_description_content_type='text/markdown',
    url="https://github.com/noetl/noetl",
    packages=find_packages(),
    package_data={
        'ui': ['**/*'],
    },
    include_package_data=True,
    install_requires=read_requirements(),
    python_requires=">=3.8",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
    ],
    keywords=["etl", "data-pipeline", "workflow", "automation"],
    entry_points={
        "console_scripts": [
            "noetl = noetl.main:app",
            "noetl-port-killer = noetl.killer:main",
        ],
    },
)
