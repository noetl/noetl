from setuptools import setup, find_packages

setup(
    name="noetl",
    version="0.1.0",
    description="The NoETL suite",
    url="https://github.com/noetl/noetl",
    author="Alexey Kuksin",
    author_email="alexey@kuksin.us",
    license="MIT",
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.11",
    ],
    packages=find_packages(where='src/noetl'),
    package_dir={'': 'src/noetl'},
    install_requires=[
        "loguru>=0.7.0",
        "pyyaml>=6.0.0",
        "aiofiles>=23.1.0",
        "strawberry-graphql==0.195.2",
        "redis==4.6.0",
        "aiohttp==3.8.4",
    ],
    python_requires='>=3.11',
)
