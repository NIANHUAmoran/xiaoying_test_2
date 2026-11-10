import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import load_env


class ConfigTests(unittest.TestCase):
    def test_file_loads_known_keys_preserves_equals_and_shell_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text('# comment\nLLM_BASE_URL=https://provider.example/v1\nLLM_MODEL="file-model"\nLLM_API_KEY="secret=with#characters"\nUNRELATED=ignored\n', encoding="utf-8-sig")
            with patch.dict(os.environ, {"LLM_MODEL": "shell-model"}, clear=True):
                load_env(path)
                self.assertEqual(os.environ["LLM_MODEL"], "shell-model")
                self.assertEqual(os.environ["LLM_API_KEY"], "secret=with#characters")
                self.assertNotIn("UNRELATED", os.environ)

    def test_malformed_file_error_does_not_expose_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text('LLM_API_KEY="hidden-secret', encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                load_env(path)
            self.assertNotIn("hidden-secret", str(caught.exception))
