import argparse
import asyncio
from loguru import logger

from src.components.dispatcher import Dispatcher
from src.components.workflow import Workflow
from src.components.config import Config
from __init__ import timer

"""
Not Only ETL is a Workflow Engine designed to manage the execution of complex workflows. 
It provides a flexible and efficient way to define, schedule, and coordinate various operations such as data processing, 
automation, and API interactions, among others. The engine employs a control loop-based approach to coordinate 
the execution of workflows, jobs, tasks, and actions offering an adaptable solution for diverse use cases.
"""


def parse_arguments():
    """
    Parses command-line arguments.
    :return: An argparse.Namespace object containing the parsed command-line arguments.
    :rtype: argparse.Namespace
    """
    parser = argparse.ArgumentParser(prog="noetl", description="Not Only ETL is a Workflow Engine that utilizes \
                            a loop-based approach to coordinate the execution of workflows, jobs, and tasks")
    parser.add_argument("-c", "--config")
    return parser.parse_args()


@timer()
async def main(args):
    """
    Main asynchronous function that initializes the workflow engine and executes it.
    :param args: The command-line arguments parsed by parse_arguments function.
    :type args: argparse.Namespace
    """
    logger.debug(f"args: {args}")
    dispatcher = await Dispatcher.create(config=Config(config_path=args.config))
    await dispatcher.save_instance_id()
    await dispatcher.save_dispatcher_template()
    await dispatcher.create_workflows()
    logger.info(dispatcher)

    # if workflow:
    #     workflow.print()
    #     await workflow.execute()
    # else:
    #     logger.error("Workflow initialization failed.")


if __name__ == "__main__":
    asyncio.run(main(args=parse_arguments()))
