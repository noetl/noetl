from noetl.storage import StorageInterface

class Event:
    def __init__(self, storage: StorageInterface):
        self.storage = storage

    def close(self):
        self.storage.close()

    def initialize_context(self, job_id: str, context: dict):
        self.storage.record_event(job_id, "INIT_CONTEXT", context)

    def start_job(self, job_id: str, context: dict):
        self.storage.record_event(job_id, "START_JOB", context)

    def start_step(self, job_id: str, step_id: str, context: dict, step_loop_id: str = "1"):
        self.storage.record_event(job_id, "START_STEP", context,
                                  step_id=step_id, step_loop_id=step_loop_id)

    def complete_task(self, job_id: str, step_id: str, task_id: str, context: dict,
                      step_loop_id: str = "1", task_loop_id: str = "1"):
        self.storage.record_event(job_id, "COMPLETE_TASK", context,
                                  step_id=step_id, task_id=task_id,
                                  step_loop_id=step_loop_id, task_loop_id=task_loop_id)

    def add_action_output(self, job_id: str, step_id: str, task_id: str, action_id: str, context: dict,
                          step_loop_id: str = "1", task_loop_id: str = "1", action_loop_id: str = "1"):
        self.storage.record_event(job_id, "ADD_ACTION_OUTPUT", context,
                                  step_id=step_id, task_id=task_id, action_id=action_id,
                                  step_loop_id=step_loop_id, task_loop_id=task_loop_id, action_loop_id=action_loop_id)

    def error_step(self, job_id: str, context: dict):
        self.storage.record_event(job_id, "ERROR_STEP", context)

    def error_job(self, job_id: str, context: dict):
        self.storage.record_event(job_id, "ERROR_JOB", context)

    def reconstruct_job_state(self, job_id: str):
        return self.storage.reconstruct_state(job_id)
