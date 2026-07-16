import unittest
from importlib.util import find_spec


class PackagingTests(unittest.TestCase):
    def test_distribution_discovers_migration_subpackage(self):
        self.assertIsNotNone(find_spec("codex_dream"))
        self.assertIsNotNone(find_spec("codex_dream.migrations"))


if __name__ == "__main__":
    unittest.main()
