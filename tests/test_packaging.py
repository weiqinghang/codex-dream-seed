import unittest

from setuptools import find_packages


class PackagingTests(unittest.TestCase):
    def test_distribution_discovers_migration_subpackage(self):
        packages = find_packages(include=["codex_dream*"])
        self.assertIn("codex_dream", packages)
        self.assertIn("codex_dream.migrations", packages)


if __name__ == "__main__":
    unittest.main()
