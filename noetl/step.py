from noetl.task import Task
from noetl.interp import replace_placeholders
from noetl.logger import setup_logger
from noetl.context import Context

logger = setup_logger(__name__, include_location=True)


class Step:

    def __init__(self, context: Context, state):
        if not isinstance(context, Context):
            raise TypeError(f"Expected an instance of Context. Got: {type(context)}")
        self.context = context
        self.state = state
        self.step_config = context.get("stepConfig")
        self.tasks_config = context.get("tasks", [])
        self.loop_config = self.step_config.get("loop", {}) if self.step_config else {}
        self.loop_items = self.loop_config.get("items", [])
        self.loop_iterator = self.loop_config.get("iterator", "item")
        if not self.step_config:
            error_msg = f"Missing 'stepConfig' in the context."
            logger.error(error_msg, extra=self.context.scope.get_id())
            raise ValueError(error_msg)
        if not isinstance(self.step_config, dict):
            error_msg = f"'stepConfig' must be a dict. Got: {type(self.step_config)}"
            logger.error(error_msg, extra=self.context.scope.get_id())
            raise ValueError(error_msg)

        if self.loop_config and not isinstance(self.loop_items, list):
            error_msg = f"'loop.items' must be a list. Got: {type(self.loop_items)}"
            logger.error(error_msg, extra=self.context.scope.get_id())
            raise ValueError(error_msg)

    async def execute(self):
        logger.info(f"Starting step execution.", extra=self.context.scope.get_id())
        try:
            if self.loop_config and self.loop_items:
                return await self.for_each()
            return await self.process_tasks(self.context)
        except Exception as e:
            if self.context.break_on_failure:
                raise e
            logger.error(f"Critical error in step execution: {e}", extra=self.context.scope.get_id())
    async def for_each(self):
        logger.info(f"Executing for each step.", extra=self.context.scope.get_id())
        results = []
        for idx, item in enumerate(self.loop_items):
            logger.debug(f"For each step {idx + 1}/{len(self.loop_items)}: {item}", extra=self.context.scope.get_id())

            loop_context = self.context.new_item_context(
                item_config={self.loop_iterator: item},
                item=item
            )
            try:
                result = await self.process_tasks(loop_context)
                results.append(result)
            except Exception as e:
                if self.context.break_on_failure:
                    raise e
                logger.error(f"Loop item {idx + 1} failed: {e}", extra=self.context.scope.get_id(), exc_info=True)
                results.append({"status": "failed", "error": str(e), "item": item})

        logger.info(f"Completed step loop execution.", extra=self.context.scope.get_id())
        return results

    async def process_tasks(self, current_context):
        logger.info(f"Starting to process tasks.", extra=self.context.scope.get_id())
        results = {}
        if not isinstance(self.tasks_config, list):
            error_msg = f"'tasks_config' must be a list. Got: {type(self.tasks_config)}"
            logger.error(error_msg, extra=self.context.scope.get_id())
            raise ValueError(error_msg)

        for task_idx, task_config in enumerate(self.tasks_config, start=1):
            task_name = task_config.get("task")

            if not task_name:
                logger.error(f"Task name is missing in task config: {task_config}", extra=self.context.scope.get_id())
                raise ValueError("Task name is required for each task.")

            try:
                task_context = current_context.new_task_context(task_name)
                logger.debug(f"Task Context: {task_name}", extra=self.context.scope.get_id())
                replace_placeholders(task_context.get("taskConfig"), task_context)
                task = Task(context=task_context, state=self.state)
                logger.info(f"Executing task {task_idx} ({task_name}).", extra=self.context.scope.get_id())
                task_result = await task.execute()
                results[task_name] = {"status": "success", "output": task_result}
                logger.success(f"Task {task_name} succeeded.", extra=self.context.scope.get_id())
            except Exception as e:
                if current_context.break_on_failure:
                    raise e
                logger.error(f"Task {task_name} failed: {e}", extra=self.context.scope.get_id())
                results[task_name] = {"status": "failed", "error": str(e)}

        logger.info("All tasks executed.", extra=self.context.scope.get_id())
        return results
