from noetl.dsl.context import Context
from noetl.runtime.state import State
from noetl.dsl.action import Action
from noetl.shared import setup_logger

logger = setup_logger(__name__, include_location=True)


class Task:
    def __init__(self, context: Context, state: State):
        self.context = context
        self.state = state
        self.task_config = context.get("taskConfig", {})
        self.loop_config = self.task_config.get("loop", {})
        self.loop_items = self.loop_config.get("items", [])
        self.loop_iterator = self.loop_config.get("iterator", "item")

        if not isinstance(self.loop_items, list):
            error_msg = f"'loop.items' must be a list."
            logger.error(error_msg, extra=self.context.scope.get_id())
            raise ValueError(error_msg)

        logger.debug(f"Task Config: {self.task_config}", extra=self.context.scope.get_id())

    async def execute(self):
        logger.info(f"Starting Task execution.", extra=self.context.scope.get_id())
        if self.loop_config and self.loop_items:
            return await self.for_each()
        return await self.process_actions(self.context)

    async def for_each(self):
        logger.info(f"Executing Task with loop.", extra=self.context.scope.get_id())
        results = []
        for idx, item in enumerate(self.loop_items):
            loop_context = self.context.new_item_context(item_config={self.loop_iterator: item}, item=item)
            logger.debug(f"For each item {idx + 1}/{len(self.loop_items)}: {item}", extra=self.context.scope.get_id())
            try:
                result = await self.process_actions(loop_context)
                results.append(result)
            except Exception as e:
                if self.context.break_on_failure():
                    raise e
                logger.error(f"Loop item {idx + 1} failed: {e}", extra=self.context.scope.get_id())
                results.append({
                    "status": "failed",
                    "error": str(e),
                    "item": item,
                })
        logger.info("All items processed.", extra=self.context.scope.get_id())
        return results

    async def process_actions(self, current_context: Context):
        logger.info("Executing actions.", extra=self.context.scope.get_id())
        results = []
        actions = current_context.get("actions", [])
        if not isinstance(actions, list):
            raise ValueError(f"The 'actions' key must be a list in taskConfig.")
        for action_id, action_config in enumerate(actions, start=1):
            action_context = current_context.new_action_context(action_config, str(action_id))
            try:
                logger.info(f"Executing Action {action_id}/{len(actions)}", extra=self.context.scope.get_id())
                action = Action(context=action_context, state=self.state, action_id=action_id)
                logger.debug(
                    f"Action Context: {action_context['actionConfig'].get('action')}", extra=self.context.scope.get_id()
                )
                action_result = await action.execute()
                results.append({
                    "action_id": action_id,
                    "action_name": action_context["actionConfig"].get("action"),
                    "result": action_result,
                })
            except Exception as e:
                if current_context.break_on_failure:
                    raise e
                logger.error(f"Action {action_id} failed: {e}", extra=self.context.scope.get_id())
                results.append({
                    "action_id": action_id,
                    "action_name": action_context["actionConfig"].get("action"),
                    "status": "failed",
                    "error": str(e),
                })
        logger.success(f"All actions executed successfully.", extra=self.context.scope.get_id())
        return results
