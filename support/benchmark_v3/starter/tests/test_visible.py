import unittest

from relay import RetryPolicy, continue_upload


class VisibleTests(unittest.TestCase):
    def test_success_does_not_sleep(self):
        sleeps = []
        report = continue_upload(lambda checkpoint: {"status": 204, "headers": {}}, sleeps.append)
        self.assertTrue(report.success)
        self.assertEqual([], sleeps)

    def test_non_retryable_stops(self):
        sleeps = []
        report = continue_upload(lambda checkpoint: {"status": 400, "headers": {}}, sleeps.append)
        self.assertFalse(report.success)
        self.assertEqual(1, len(report.attempts))

    def test_default_policy(self):
        p = RetryPolicy()
        self.assertEqual(4, p.max_attempts)
        self.assertEqual((429, 503), p.retry_statuses)


if __name__ == "__main__":
    unittest.main()
