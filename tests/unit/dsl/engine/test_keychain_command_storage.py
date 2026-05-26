import pytest
from jinja2 import Environment

from noetl.core.credential_refs import KEYCHAIN_MANIFEST_KEY, NOETL_REF_KEY
from noetl.core.dsl.engine.executor.commands import CommandCreationMixin
from noetl.core.dsl.engine.executor.state import ExecutionState
from noetl.core.dsl.engine.models import Playbook


class _CommandCreator(CommandCreationMixin):
    def __init__(self):
        self.jinja_env = Environment()


def _playbook() -> Playbook:
    return Playbook.model_validate(
        {
            "apiVersion": "noetl.io/v10",
            "kind": "Playbook",
            "metadata": {"name": "keychain-storage-test"},
            "workload": {"region": "us-central1"},
            "keychain": [
                {
                    "name": "openai_token",
                    "kind": "secret_manager",
                    "map": {"api_key": "{{ openai_secret_path }}"},
                }
            ],
            "workflow": [
                {
                    "step": "extract_turn",
                    "input": {
                        "region": "{{ workload.region }}",
                        "api_key": "{{ keychain.openai_token.api_key | default('') }}",
                        "header": "Bearer {{ keychain.openai_token.api_key }}",
                    },
                    "tool": {
                        "kind": "python",
                        "input": {
                            "api_key": "{{ keychain.openai_token.api_key | default('') }}",
                            "header": "Bearer {{ keychain.openai_token.api_key }}",
                        },
                        "code": "result = {'ok': True}",
                    },
                }
            ],
        }
    )


@pytest.mark.asyncio
async def test_command_context_stores_refs_and_deferred_templates():
    playbook = _playbook()
    state = ExecutionState("123", playbook, {}, catalog_id=42)
    state.variables[KEYCHAIN_MANIFEST_KEY] = {
        "entries": {
            "openai_token": {
                "kind": "secret_manager",
                "fields": ["api_key"],
            }
        }
    }
    state.variables["keychain"] = {"openai_token": {"api_key": "placeholder-secret"}}
    creator = _CommandCreator()

    command = await creator._create_command_for_step(state, playbook.workflow[0], {})

    assert command.input["region"] == "us-central1"
    assert command.input["api_key"][NOETL_REF_KEY] == {
        "kind": "keychain",
        "name": "openai_token",
        "field": "api_key",
    }
    assert command.input["header"] == "Bearer {{ keychain.openai_token.api_key }}"
    assert command.tool.config["input"]["api_key"][NOETL_REF_KEY]["name"] == "openai_token"
    assert command.tool.config["input"]["header"] == "Bearer {{ keychain.openai_token.api_key }}"
    assert "keychain" not in command.render_context
    assert "openai_token" not in command.render_context


def test_execution_state_serialization_does_not_persist_resolved_keychain_values():
    playbook = _playbook()
    state = ExecutionState(
        "123",
        playbook,
        {"keychain": {"openai_token": {"api_key": "placeholder-secret"}}},
        catalog_id=42,
    )
    state.variables[KEYCHAIN_MANIFEST_KEY] = {
        "entries": {
            "openai_token": {
                "kind": "secret_manager",
                "fields": ["api_key"],
            }
        }
    }
    state.variables["openai_token"] = {"api_key": "placeholder-secret"}

    state_dict = state.to_dict()

    assert "keychain" not in state_dict["variables"]
    assert "openai_token" not in state_dict["variables"].keys()
    assert "keychain" not in state_dict["payload"]
    assert "placeholder-secret" not in str(state_dict)
    assert state_dict["variables"][KEYCHAIN_MANIFEST_KEY]["entries"]["openai_token"]["fields"] == ["api_key"]
