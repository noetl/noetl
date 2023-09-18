from setuptools import setup, find_packages

setup(
    name="noetl",
    version="0.1.0",
    author="Alexe Kuksin",
    description="A Python package for NoETL",
    packages=find_packages(),
    install_requires=[
        "asyncio==3.4.3",
        "loguru==0.7.2",
        "aiofiles==23.2.1",
    ],
)
