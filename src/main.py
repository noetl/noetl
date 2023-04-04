import yaml
import signal
from loguru import logger
import concurrent.futures
from __init__ import async_timer
import nest_asyncio

nest_asyncio.apply()

def cancel_tasks():
    logger.info('Got a SIGINT!')
    tasks: Set[asyncio.Task] = asyncio.all_tasks()
    logger.info(f'Cancelling {len(tasks)} tasks.')
    [task.cancel() for task in tasks]
    

@async_timer()
async def main():
    event_loop = asyncio.get_event_loop()
    event_loop.add_signal_handler(signal.SIGINT, cancel_tasks)
    jobs = []
    


if __name__ == "__main__":
    asyncio.run(main())
