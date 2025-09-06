import unittest
import part1_bootstrap
import os

class TestPart1Bootstrap(unittest.TestCase):
    def test_log_and_tail_log(self):
        test_msg = "Test log entry"
        part1_bootstrap.log(test_msg)
        log_tail = part1_bootstrap.tail_log(10)
        self.assertIn(test_msg, log_tail)

    def test_permissions_text(self):
        self.assertIn("This tool will:", part1_bootstrap.PERMISSIONS_TEXT)

if __name__ == "__main__":
    unittest.main()
