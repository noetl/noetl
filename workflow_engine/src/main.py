#!/usr/bin/env python
import argparse
import asyncio
from loguru import logger
from workflow_engine.src.components.workflow import Workflow
from workflow_engine.src.components.config import Config
from __init__ import timer

"""
Not Only ETL is a versatile Workflow Engine designed to manage the execution of complex workflows, jobs, and tasks. 
It provides a flexible and efficient way to define, schedule, and coordinate various operations such as data processing, 
automation, and API interactions, among others. The engine employs a control loop-based approach to coordinate 
the execution of workflows, jobs, and tasks, offering an adaptable solution for diverse use cases.
"""

def parse_arguments():
    """
    Parses command-line arguments.
    :return: An argparse.Namespace object containing the parsed command-line arguments.
    :rtype: argparse.Namespace
    """
    parser = argparse.ArgumentParser(prog="noetl", description="Not Only ETL is a Workflow Engine that utilizes \
                            a control loop-based approach to coordinate the execution of workflows, jobs, and tasks")
    parser.add_argument("-c", "--config", default="coordinator.yaml")
    return parser.parse_args()


@timer()
async def main(args):
    """
    Main asynchronous function that initializes the workflow engine and executes it.
    :param args: The command-line arguments parsed by parse_arguments function.
    :type args: argparse.Namespace
    """
    logger.debug(f"args: {args}")
    workflow = await Workflow.initialize_workflow(config=Config(config_path=args.config))

    workflow.print()
    await workflow.execute()


if __name__ == "__main__":
    asyncio.run(main(args=parse_arguments()))
