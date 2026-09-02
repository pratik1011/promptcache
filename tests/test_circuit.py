"""Circuit breaker and backoff tests."""
import unittest

from promptcache.production.circuit import CircuitBreaker, next_delay


class CircuitBreakerTests(unittest.TestCase):
    def test_opens_after_threshold(self):
        breaker = CircuitBreaker(fail_threshold=3, open_seconds=60)
        for _ in range(3):
            breaker.record_failure("p1")
        self.assertFalse(breaker.allow("p1"))
        # other providers are unaffected
        self.assertTrue(breaker.allow("p2"))

    def test_success_resets_failures(self):
        breaker = CircuitBreaker(fail_threshold=3, open_seconds=60)
        breaker.record_failure("p1")
        breaker.record_success("p1")
        breaker.record_failure("p1")
        self.assertTrue(breaker.allow("p1"))

    def test_recovers_after_open_window(self):
        breaker = CircuitBreaker(fail_threshold=1, open_seconds=10)
        breaker.record_failure("p1")
        self.assertFalse(breaker.allow("p1"))
        # simulate the open window elapsing
        breaker._opened_until["p1"] = 0  # now in the past
        self.assertTrue(breaker.allow("p1"))
        breaker.record_success("p1")
        self.assertEqual(breaker._failures["p1"], 0)

    def test_reset_clears_state(self):
        breaker = CircuitBreaker(fail_threshold=1, open_seconds=60)
        breaker.record_failure("p1")
        breaker.reset()
        self.assertTrue(breaker.allow("p1"))
        self.assertEqual(breaker._failures, {})
        self.assertEqual(breaker._opened_until, {})


class BackoffTests(unittest.TestCase):
    def test_next_delay_exponential(self):
        self.assertEqual(next_delay(0), 0.5)
        self.assertEqual(next_delay(1), 1.0)
        self.assertEqual(next_delay(2), 2.0)

    def test_next_delay_capped(self):
        self.assertEqual(next_delay(10), 8.0)


if __name__ == "__main__":
    unittest.main()