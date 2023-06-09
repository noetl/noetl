import argparse
import asyncio
from loguru import logger
from src.components.dispatcher import Dispatcher
from src.components.models.config import Config
from __init__ import timer
from src.storage import db

"""
Not Only ETL is a Workflow Engine designed to manage the execution of complex workflows. 
It provides a flexible and efficient way to define, schedule, and coordinate various operations such as data processing, 
automation, command-line, and API interactions. 
"""


def parse_arguments():
    """
    Parses command-line arguments.
    :return: An argparse.Namespace object containing the parsed command-line arguments.
    :rtype: argparse.Namespace
    """
    parser = argparse.ArgumentParser(prog="NoETL", description="Not Only ETL is a Workflow Engine that utilizes \
                            a loop-based approach to dispatch the execution of workflows.")
    parser.add_argument("-c", "--config")
    return parser.parse_args()


@timer()
async def main(args):
    """
    Main asynchronous function that initializes the workflow dispatcher engine.
    :param args: The command-line arguments.
    :type args: argparse.Namespace
    """
    logger.debug(f"args: {args}")
    config = Config()
    await db.pool_connect()
    config.set_config_path(config_path=args.config)
    dispatcher = await Dispatcher.create(config=config)
    await dispatcher.save_dispatcher_template()
    # await dispatcher.process_workflow_configs()
    logger.info(dispatcher)


if __name__ == "__main__":
    asyncio.run(main(args=parse_arguments()))
