import asyncio
from noetl.shared import setup_logger

logger = setup_logger(__name__, include_location=True)


class State:

    def __init__(self, event, job_id):
        self.job_id = job_id
        self.event = event
        self.queue = asyncio.Queue()
        self.running = True
        self.process_task = None

        logger.info(f"Initialized State for job.", extra={"scope": f"[State {self.job_id}]"})

    async def start(self):
        logger.info("Starting State processor.", extra={"scope": f"[State {self.job_id}]"})
        self.process_task = asyncio.create_task(self.process())

    async def shutdown(self):
        logger.info("Initiating shutdown.", extra={"scope": f"[State {self.job_id}]"})
        await self.save(None)
        self.running = False
        await self.save(None)
        logger.info("Shutdown signal added to queue.", extra={"scope": f"[State {self.job_id}]"})

        try:
            await asyncio.wait_for(self.queue.join(), timeout=5.0)
            logger.info("Queue fully processed.", extra={"scope": f"[State {self.job_id}]"})

        except asyncio.TimeoutError:
            logger.warning("Queue processing timeout. Forcing shutdown.", extra={"scope": f"[State {self.job_id}]"})
            while not self.queue.empty():
                self.queue.get_nowait()
                self.queue.task_done()

        if self.process_task:
            logger.info("Cancelling processing task.", extra={"scope": f"[State {self.job_id}]"})
            self.process_task.cancel()
            try:
                await self.process_task
            except asyncio.CancelledError:
                logger.info("Processing task cancelled.", extra={"scope": f"[State {self.job_id}]"})

        logger.info("State shutdown completed.", extra={"scope": f"[State {self.job_id}]"})



    async def save(self, update):
        if not self.running:
            logger.warning(f"Save called after shutdown. Ignoring update: {update}",
                           extra={"scope": f"[State {self.job_id}]"})
            return
        await self.queue.put(update)

    async def process(self):
        logger.info("State processing started.", extra={"scope": f"[State {self.job_id}]"})
        while self.running:
            try:
                update = await self.queue.get()
                if update is None:
                    logger.info("Received shutdown signal.", extra={"scope": f"[State {self.job_id}]"})
                    self.running = False
                    self.queue.task_done()
                    break
                try:
                    self.handle_event(update)
                except Exception as e:
                    logger.error(f"Failed to process update: {update}. Error: {str(e)}",
                                 extra={"scope": f"[State {self.job_id}]"})
                self.queue.task_done()

            except asyncio.CancelledError:
                logger.info("[Process task cancelled.", extra={"scope": f"[State {self.job_id}]"})
                break
            except Exception as e:
                logger.error(f"Error during process loop: {str(e)}", extra={"scope": f"[State {self.job_id}]"})
        logger.info("Processing loop completed.", extra={"scope": f"[State {self.job_id}]"})


    def handle_event(self, update):
        event_type = update.pop("event_type", "UPDATE_CONTEXT")
        if event_type == "INIT_CONTEXT":
            self.event.initialize_context(self.job_id, update.get("context", {}))
        elif event_type == "START_JOB":
            self.event.start_job(self.job_id, update.get("context", {}))
        elif event_type == "START_STEP":
            self.event.start_step(self.job_id, update.get("step"), update.get("context", {}))
        elif event_type == "COMPLETE_TASK":
            self.event.complete_task(
                job_id=self.job_id,
                step_id=update.get("step_id"),
                task_id=update.get("task_id"),
                context=update.get("context", {})
            )
        elif event_type == "ERROR_STEP":
            self.event.error_step(self.job_id, update.get("context", {}))
        elif event_type == "ERROR_JOB":
            self.event.error_job(self.job_id, update.get("context", {}))
        else:
            logger.warning(f"Unknown event type: {event_type}", extra={"scope": f"[State {self.job_id}]"})
