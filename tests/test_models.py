import io
import json
import os
import unittest
import urllib.error
from unittest.mock import patch

from src.models import HTTPModel, ModelServiceError


class ModelTests(unittest.TestCase):
    def test_real_adapter_contract_and_secret_not_in_prompt(self):
        env = {"LLM_BASE_URL": "https://provider.example/v1", "LLM_MODEL": "example", "LLM_API_KEY": "local-secret"}
        decision = {"action": "search_materials", "arguments": {}, "basis": "read first"}
        body = json.dumps({"choices": [{"message": {"content": json.dumps(decision)}}]}).encode()
        with patch.dict(os.environ, env), patch("urllib.request.urlopen", return_value=io.BytesIO(body)) as mocked:
            self.assertEqual(HTTPModel().decide({"state": {}}), decision)
            self.assertNotIn(b"local-secret", mocked.call_args.args[0].data)

    def test_provider_error_is_sanitized(self):
        env = {"LLM_BASE_URL": "https://provider.example/v1", "LLM_MODEL": "example", "LLM_API_KEY": "local-secret"}
        error = urllib.error.HTTPError("https://sensitive-host/", 401, "local-secret", {}, None)
        with patch.dict(os.environ, env), patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(ModelServiceError) as caught:
                HTTPModel().decide({})
            self.assertEqual(str(caught.exception), "provider_http_401")


if __name__ == "__main__":
    unittest.main()
