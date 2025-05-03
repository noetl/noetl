from noetl.pubsub.nats_payload import Payload, AppConst


class Playbook:
    METADATA_EVENT_TYPE = AppConst.METADATA_EVENT_TYPE
    METADATA_COMMAND_TYPE = AppConst.METADATA_COMMAND_TYPE

    def __init__(self, payload: Payload):
        self.payload = payload
        self.template = None
        self.transitions = None

    async def load_template(self):
        playbook_path = self.payload.get_value("playbook.path")
        playbook_bucket = self.payload.get_value("playbook.bucket")
        kv_playbook = await self.payload.kv_get_decoded(playbook_bucket, playbook_path)
        if kv_playbook:
            self.template = kv_playbook

    def set_transitions(self):
        self.transitions = self.template.get_value("spec.transitions", {})

    def validate_transition(self, current_state, next_state):
        states = self.transitions.get(current_state)

        if states is None:
            raise ValueError(f"No transitions defined for the state: {current_state}")

        elif isinstance(states, list):
            if next_state not in states:
                raise ValueError(f"Transition to '{next_state}' from '{current_state}' is not allowed.")
        elif next_state != states:
            raise ValueError(f"Transition to '{next_state}' from '{current_state}' is not allowed.")

        return True

    def transition(self, current_state, next_state):
        if self.validate_transition(current_state, next_state):
            self.payload.set_status(state=next_state)
