from setuptools import setup, find_packages
import os
from pathlib import Path


def read_readme():
    this_directory = Path(__file__).parent
    readme_file = this_directory / 'README.md'
    if readme_file.exists():
        return readme_file.read_text(encoding='utf-8')
    return ""

def get_version():
    import re
    pyproject_file = Path(__file__).parent / 'pyproject.toml'
    if pyproject_file.exists():
        content = pyproject_file.read_text()
        match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
        if match:
            return match.group(1)
    return "0.1.18"


setup(
    name="noetl",
    version=get_version(),
    author="NoETL Team",
    author_email="182583029+kadyapam@users.noreply.github.com",
    description="A framework to build and run data pipelines and workflows.",
    long_description=read_readme(),
    long_description_content_type='text/markdown',
    url="https://github.com/noetl/noetl",
    packages=find_packages() + ['ui'],
    package_data={
        '': ['*.md', '*.txt', '*.yml', '*.yaml'],
        'ui': ['static/**/*', 'templates/**/*', '**/*'],
        'noetl': ['*.py'],
    },
    include_package_data=True,
    python_requires=">=3.11",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: System :: Systems Administration",
        "Topic :: Database",
    ],
    keywords="etl elt data pipeline workflow automation fastapi react",
    entry_points={
        'console_scripts': [
            'noetl=noetl.main:app',
        ],
    },
    project_urls={
        "Bug Reports": "https://github.com/noetl/noetl/issues",
        "Source": "https://github.com/noetl/noetl",
        "Documentation": "https://github.com/noetl/noetl/blob/main/README.md",
    },
)
