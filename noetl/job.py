import asyncio
import os
from noetl.logger import setup_logger
from noetl.interp import process_payload
from noetl.storage import StorageFactory
from noetl.event import Event
from noetl.state import State
from noetl.step import Step
from noetl.context import Context

logger = setup_logger(__name__, include_location=True)

class Job:
    def __init__(self, payload):
        config = process_payload(payload)
        self.context = Context(configs=config, cwd_path=os.getcwd())
        self.state = State(event=Event(
            storage=StorageFactory.get_storage({
                "storage_type": self.context.storage_type,
                "file_path": self.context.execution_path,
            })
        ), job_id=self.context.get_job_id())
        self.state_queue = asyncio.Queue()
        self.state_worker_active = True
        self.state_worker_task = None
        logger.info("initialized.", extra=self.context.scope.get_id())

    async def start_worker(self):
        logger.info(f"Starting worker...", extra=self.context.scope.get_id())
        self.state_worker_task = asyncio.create_task(self.state_worker())

    async def state_worker(self):
        while self.state_worker_active or not self.state_queue.empty():
            try:
                operation, payload = await self.state_queue.get()
                if operation == "start":
                    await self.state.start()
                    logger.info("State started.", extra=self.context.scope.get_id())
                elif operation == "save":
                    await self.state.save(payload)
                    logger.info("State saved.", extra=self.context.scope.get_id())
                else:
                    logger.warning(f"Unknown state operation: {operation}", extra=self.context.scope.get_id())
                self.state_queue.task_done()
            except Exception as e:
                logger.critical(f"Failed to process state operation: {str(e)}", extra=self.context.scope.get_id())

    async def shutdown_state_worker(self):
        logger.info(f"Shutting down state worker...", extra=self.context.scope.get_id())
        self.state_worker_active = False
        await self.state_queue.join()
        if self.state_worker_task and not self.state_worker_task.done():
            self.state_worker_task.cancel()
            try:
                await self.state_worker_task
            except asyncio.CancelledError:
                logger.info(f"State worker task cancelled successfully.", extra=self.context.scope.get_id())

        logger.info(f"State worker shut down.", extra=self.context.scope.get_id())

    async def execute(self):
        await self.start_worker()
        await self.state_queue.put(("start", None))

        await self.state_queue.put((
            "save",
            {
                "event_type": "INIT_CONTEXT",
                "context": {
                    "status": "initialized",
                    "config": self.context,
                },
            }
        ))
        logger.info(f"Starting workflow execution.", extra=self.context.scope.get_id())
        results = {}
        try:
            steps = self.context.get_steps()
            await self.state_queue.put((
                "save",
                {
                    "event_type": "START_JOB",
                    "context": {
                        "status": "running",
                        "steps": steps,
                    }
                }
            ))
            if not isinstance(steps, list):
                raise ValueError(f"Steps config must be a list, got {type(steps)}")

            for step_config in steps:
                step_context = self.context.new_step_context(step_config)
                step_name = step_context.get("stepName")
                logger.info(f"Starting step '{step_name}'.", extra=self.context.scope.get_id())
                await self.state_queue.put((
                    "save",
                    {
                        "event_type": "START_STEP",
                        "step": step_name,
                        "context": {"description": f"Step {step_name} started."}
                    }
                ))
                step = Step(context=step_context, state=self.state)
                try:
                    step_result = await step.execute()
                    results[step_name] = step_result
                    logger.success(f"Step '{step_name}' completed successfully.", extra=self.context.scope.get_id())
                except Exception as e:
                    error_context = {
                        "event_type": "ERROR_STEP",
                        "step": step_name,
                        "context": {
                            "description": f"Error during step '{step_name}': {str(e)}",
                            "status": "failed",
                        }
                    }
                    try:
                        await self.state_queue.put(("save", error_context))
                    except Exception as queue_error:
                        logger.critical(f"State queue failed: {str(queue_error)}", extra=self.context.scope.get_id())
                    logger.error(f"Step '{step_name}' failed: {str(e)}", extra=self.context.scope.get_id())
                    if self.context.break_on_failure:
                        raise e
            logger.success(f"Workflow executed successfully.", extra=self.context.scope.get_id())
            return results
        except Exception as e:
            error_context = {
                "event_type": "ERROR_JOB",
                "context": {
                    "status": "failed",
                    "error": str(e),
                }
            }
            try:
                await self.state_queue.put(("save", error_context))
            except Exception as queue_error:
                logger.critical(f"Job queue error: {str(queue_error)}", extra=self.context.scope.get_id())
            logger.critical(f"Workflow execution failed: {str(e)}", extra=self.context.scope.get_id())
            if self.context.break_on_failure:
                raise e
        finally:
            if self.state_worker_task and not self.state_worker_task.done():
                self.state_worker_task.cancel()
                try:
                    await asyncio.wait_for(self.state_worker_task, timeout=5)
                except asyncio.TimeoutError:
                    logger.error("State worker has not canceled within timeout.", extra=self.context.scope.get_id())
                except asyncio.CancelledError:
                    logger.info("State worker cancelled gracefully.", extra=self.context.scope.get_id())
        await self.shutdown_state_worker()
