import os
import signal
import socket
import tempfile
import time
import unittest
from pathlib import Path

from codex_dream.console import ConsoleError, console_status, start_console, stop_console
from codex_dream.workspace import init_workspace


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class ConsoleRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "workspace"
        init_workspace(self.workspace)
        self.port = free_port()

    def tearDown(self):
        try:
            stop_console(self.workspace)
        except Exception:
            pass
        self.temp.cleanup()

    def test_start_status_duplicate_start_and_stop_are_deterministic(self):
        started = start_console(self.workspace, "127.0.0.1", self.port, False)
        self.assertTrue(started["running"])
        duplicate = start_console(self.workspace, "127.0.0.1", self.port, False)
        self.assertTrue(duplicate["already_running"])
        self.assertEqual(console_status(self.workspace)["status"], "running")
        stopped = stop_console(self.workspace)
        self.assertFalse(stopped["running"])
        self.assertTrue(stop_console(self.workspace)["already_stopped"])

    def test_port_conflict_and_stale_pid_are_diagnosed(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
            occupied.bind(("127.0.0.1", self.port))
            occupied.listen(1)
            with self.assertRaisesRegex(ConsoleError, "already in use"):
                start_console(self.workspace, "127.0.0.1", self.port, False)
        runtime = self.workspace / "state/private/console-service.json"
        runtime.write_text('{"pid": 99999999, "url": "http://127.0.0.1:1"}', encoding="utf-8")
        self.assertEqual(console_status(self.workspace)["status"], "stale_pid")
        stopped = stop_console(self.workspace)
        self.assertTrue(stopped["already_stopped"])
        self.assertFalse(runtime.exists())

    def test_abnormal_exit_is_reported_instead_of_claimed_running(self):
        started = start_console(self.workspace, "127.0.0.1", self.port, False)
        os.kill(int(started["pid"]), signal.SIGTERM)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and console_status(self.workspace)["status"] == "running":
            time.sleep(0.05)
        self.assertIn(console_status(self.workspace)["status"], {"stale_pid", "unhealthy"})


if __name__ == "__main__":
    unittest.main()
