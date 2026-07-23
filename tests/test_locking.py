import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from codex_dream.locking import WorkspaceLockError, workspace_write_lock
from codex_dream.workspace import init_workspace


class WorkspaceLockTests(unittest.TestCase):
    def test_actual_knowledge_cli_write_waits_for_workspace_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            init_workspace(workspace)
            command = [
                sys.executable, "-m", "codex_dream.knowledge",
                "--workspace", str(workspace), "create",
                "--title", "Synthetic locked write", "--kind", "reusable_work",
                "--scope", "project", "--summary", "Synthetic only.",
            ]
            with workspace_write_lock(workspace):
                process = subprocess.Popen(
                    command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
                time.sleep(0.2)
                self.assertIsNone(process.poll(), "knowledge CLI bypassed the Workspace lock")
            stdout, stderr = process.communicate(timeout=3)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertIn('\"knowledge_id\": \"KD-0001\"', stdout)

    def test_second_process_times_out_with_diagnostic_instead_of_waiting_forever(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            init_workspace(workspace)
            code = (
                "import sys,time; from pathlib import Path; "
                "from codex_dream.locking import workspace_write_lock; "
                "ctx=workspace_write_lock(Path(sys.argv[1])); ctx.__enter__(); "
                "print('locked', flush=True); time.sleep(1); ctx.__exit__(None,None,None)"
            )
            process = subprocess.Popen(
                [sys.executable, "-c", code, str(workspace)],
                stdout=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(process.stdout.readline().strip(), "locked")
                with self.assertRaisesRegex(WorkspaceLockError, "timed out"):
                    with workspace_write_lock(workspace, timeout=0.1):
                        pass
            finally:
                process.terminate()
                process.wait(timeout=2)
                if process.stdout:
                    process.stdout.close()


if __name__ == "__main__":
    unittest.main()
