from setuptools import setup, find_packages

setup(
    name="noetl",
    version="0.1.0",
    author="Alexey Kuksin",
    description="NoETL Python package",
    packages=find_packages(),
    install_requires=[
        "asyncio==3.4.3",
        "loguru==0.7.2",
        "aiofiles==23.2.1",
    ],
)
