import unittest
from noetl.payload import Payload, ExecutionState


class TestPayload(unittest.TestCase):
    def setUp(self):
        self.payload = Payload()

    def test_update_status_with_dict(self):
        self.payload.set_status(status={'test_status': 'ACTIVE'})
        self.assertEqual(self.payload.get_value('status.test_status'), 'ACTIVE')

    def test_update_status_with_state(self):
        self.payload.set_status(state='COMPLETED')
        self.assertEqual(self.payload.get_value('status.state'), ExecutionState['COMPLETED'].value)

    def test_update_status_with_invalid_state(self):
        with self.assertRaises(ValueError):
            self.payload.set_status(state='INVALID_STATE')

    def test_update_status_with_dict_invalid_sate(self):
        self.payload.set_status(status={'test_status': 'ACTIVE'}, state='COMPLETED')
        self.assertEqual(self.payload.get_value('status.test_status'), 'ACTIVE')
        self.assertEqual(self.payload.get_value('status.state'), ExecutionState['COMPLETED'].value)

if __name__ == "__main__":
    unittest.main()
