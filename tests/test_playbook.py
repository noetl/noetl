import unittest
from unittest.mock import Mock, MagicMock
from playbook import Playbook


class TestPlaybook(unittest.TestCase):
    def setUp(self):
        self.mock_payload = Mock()

        self.MOCK_DATA = {
            'spec': {
                'transitions': {
                    'INITIALIZED': ['RUNNING', 'FAILED', 'TERMINATED'],
                    'RUNNING': ['SUSPENDED', 'COMPLETED', 'TERMINATED', 'FAILED'],
                    'SUSPENDED': ['RUNNING', 'TERMINATED', 'FAILED'],
                    'COMPLETED': ['INITIALIZED'],
                    'FAILED': ['INITIALIZED'],
                    'TERMINATED': ['INITIALIZED']
                }
            }
        }

        self.playbook = Playbook(self.mock_payload)
        self.playbook.template = MagicMock()
        self.playbook.template.get_value.return_value = self.MOCK_DATA['spec']['transitions']

    def test_initialize(self):
        self.assertEqual(self.playbook.payload, self.mock_payload)

    def test_set_transitions(self):
        self.playbook.set_transitions()
        self.assertEqual(self.playbook.transitions, self.MOCK_DATA['spec']['transitions'])

    def test_validate_transition(self):
        self.playbook.set_transitions()

        self.assertTrue(self.playbook.validate_transition('RUNNING', 'COMPLETED'))
        self.assertTrue(self.playbook.validate_transition('SUSPENDED', 'RUNNING'))

        with self.assertRaises(ValueError):
            self.playbook.validate_transition('COMPLETED', 'RUNNING')
            self.playbook.validate_transition('SUSPENDED', 'COMPLETED')

    def test_transition(self):
        self.playbook.set_transitions()

        self.playbook.transition('RUNNING', 'SUSPENDED')
        self.playbook.payload.set_status.assert_called_once_with(state='SUSPENDED')

        with self.assertRaises(ValueError):
            self.playbook.transition('RUNNING', 'INITIALIZED')


if __name__ == "__main__":
    unittest.main()
