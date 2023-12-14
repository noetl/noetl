import json
import asyncio
from loguru import logger
from config import Config
from store import Store
from playbook import Workflow


if __name__ == "__main__":
    workflow_template = Config.create_from_file()
    logger.info(json.dumps(workflow_template, indent=4))
    workflow_template.update_vars()
    workflow = Workflow.create(workflow_template, Store("event_store"))
    asyncio.run(workflow.run_workflow())
