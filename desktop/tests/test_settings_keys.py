"""API keys: the Credential Manager store, the Settings page's connection checks, and where keys are allowed to go."""
import io
import json
import os
import sys
import tempfile
import types
import unittest
import urllib.error
import uuid
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from hypit_desktop import connection  # noqa: E402
from hypit_desktop.agent import director as dr  # noqa: E402
from hypit_desktop.agent.factory import agent_backend_from  # noqa: E402
from hypit_desktop.credentials import (ARK_KEY, LLM_KEY, PLACEHOLDER_KEY, MemoryStore,  # noqa: E402
                                       WindowsCredentialStore, key_name, stored_or_env)
from hypit_desktop.settings import Settings  # noqa: E402
from hypit_desktop.ui.settings_dialog import SettingsDialog  # noqa: E402


def app():
    return QApplication.instance() or QApplication([])


class FakeResponse:
    def __init__(self, status, body):
        self.status, self._body = status, body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def answering(status, body=""):
    def opener(request, timeout=0):
        if status == 200:
            return FakeResponse(200, body)
        raise urllib.error.HTTPError(request.full_url, status, "x", {}, io.BytesIO(body.encode("utf-8")))
    return opener


def unreachable(request, timeout=0):
    raise urllib.error.URLError("timed out")


class CredentialStoreTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows Credential Manager only")
    def test_round_trip_in_the_windows_credential_manager(self):
        store = WindowsCredentialStore()
        name = f"test-{uuid.uuid4().hex}"
        self.assertEqual(store.get(name), "")
        secret = "ark-密钥-1234567890"           # non-ASCII survives
        try:
            store.set(name, secret)
            self.assertEqual(store.get(name), secret)
            store.set(name, "second")
            self.assertEqual(store.get(name), "second")
        finally:
            store.delete(name)
        self.assertEqual(store.get(name), "")
        store.delete(name)                          # deleting something absent is not an error

    def test_stored_key_wins_over_the_environment(self):
        store = MemoryStore()
        with mock.patch.dict(os.environ, {"SOME_KEY_VAR": "from-env"}):
            self.assertEqual(stored_or_env(store, "x", "SOME_KEY_VAR"), "from-env")
            store.set("x", "from-store")
            self.assertEqual(stored_or_env(store, "x", "SOME_KEY_VAR"), "from-store")
            self.assertEqual(stored_or_env(None, "x", "SOME_KEY_VAR"), "from-env")
        self.assertEqual(stored_or_env(MemoryStore(), "x", "NO_SUCH_VAR_123"), "")


class ConnectionTests(unittest.TestCase):
    def test_ark_answers_are_explained(self):
        invalid = json.dumps({"error": {"code": "InvalidParameter", "message": "content field cannot be empty"}})
        ok, text = connection.test_ark("k", opener=answering(400, invalid))
        self.assertTrue(ok)
        self.assertIn("已开通", text)
        ok, text = connection.test_ark("k", opener=answering(401, json.dumps({"error": {"code": "AuthenticationError"}})))
        self.assertFalse(ok)
        self.assertIn("密钥无效", text)
        missing = json.dumps({"error": {"code": "InvalidEndpointOrModel.NotFound"}})
        ok, text = connection.test_ark("k", opener=answering(404, missing))
        self.assertFalse(ok)
        self.assertIn("还没有开通", text)
        ok, text = connection.test_ark("k", opener=unreachable)
        self.assertFalse(ok)
        self.assertIn("连不上", text)
        self.assertEqual(connection.test_ark("")[0], False)

    def test_ark_check_names_the_models_that_are_not_enabled(self):
        ids = connection.ark_models()
        self.assertEqual(set(ids), {"seedance-2", "seedance-2-fast", "seedance-2-mini", "seedance-2.5"})

        def opener(request, timeout=0):
            model = json.loads(request.data)["model"]
            code, status = ("InvalidEndpointOrModel.NotFound", 404) if model == ids["seedance-2-fast"] else ("InvalidParameter", 400)
            raise urllib.error.HTTPError(request.full_url, status, "x", {}, io.BytesIO(json.dumps({"error": {"code": code}}).encode()))

        ok, text = connection.test_ark("k", opener=opener)
        self.assertTrue(ok)
        self.assertIn("已开通:Seedance 2.0、2.0 Mini、2.5", text)
        self.assertIn("还没有开通:Seedance 2.0 Fast", text)

    def test_ark_check_sends_an_incomplete_task_and_the_key_in_the_header_only(self):
        seen = {}

        def opener(request, timeout=0):
            seen["url"], seen["body"], seen["auth"] = request.full_url, json.loads(request.data), request.get_header("Authorization")
            raise urllib.error.HTTPError(request.full_url, 400, "x", {}, io.BytesIO(b'{"error":{"code":"InvalidParameter"}}'))

        connection.test_ark("secret-key", opener=opener)
        self.assertTrue(seen["url"].endswith("/contents/generations/tasks"))
        self.assertEqual(seen["body"]["content"], [])           # nothing that could generate (or bill) anything
        self.assertEqual(seen["auth"], "Bearer secret-key")
        self.assertNotIn("secret-key", seen["url"])

    def test_llm_answers_are_explained(self):
        self.assertTrue(connection.test_llm("https://x/anthropic", "m", "k", opener=answering(200, "{}"))[0])
        ok, text = connection.test_llm("https://x/anthropic", "m", "k", opener=answering(401, "{}"))
        self.assertFalse(ok)
        self.assertIn("密钥无效", text)
        ok, text = connection.test_llm("https://x/anthropic", "bad-model", "k", opener=answering(400, "supported model names"))
        self.assertFalse(ok)
        self.assertIn("bad-model", text)
        self.assertIn("连不上", connection.test_llm("https://x/anthropic", "m", "k", opener=unreachable)[1])


class KeyPlacementTests(unittest.TestCase):
    def test_the_director_shell_cannot_read_secret_variables(self):
        self.assertFalse(dr.bash_allowed("echo $ANTHROPIC_AUTH_TOKEN"))
        self.assertFalse(dr.bash_allowed('echo "${ARK_API_KEY}"'))
        self.assertFalse(dr.bash_allowed("printf %s $DEEPSEEK_API_KEY"))
        self.assertTrue(dr.bash_allowed("echo hello"))
        self.assertTrue(dr.bash_allowed("hypit plan productions/main/runs/main.svrun"))

    def test_hypit_worker_gets_the_real_key_and_the_director_a_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(Path(tmp) / "s.json")
            store = MemoryStore()
            store.set(ARK_KEY, "ark-real")
            store.set(LLM_KEY, "llm-real")
            backend = agent_backend_from(settings, Path(tmp), store)
            self.assertEqual(backend.cli.extra_env, {"ARK_API_KEY": "ark-real"})
            self.assertEqual(backend.config.llm_key, "llm-real")
            self.assertEqual(backend.cli._env()["ARK_API_KEY"], "ark-real")

            director = backend._default_director(Path(tmp), "llm-real")
            self.assertEqual(director.placeholder_env, {"ARK_API_KEY": PLACEHOLDER_KEY})
            captured = {}
            sdk = types.SimpleNamespace(ClaudeAgentOptions=lambda **kw: captured.update(kw) or kw,
                                        PermissionResultDeny=object, PermissionResultAllow=object)
            with mock.patch.dict(os.environ, {"ARK_API_KEY": "also-in-the-system-environment"}):
                director._options(False, sdk)
            self.assertEqual(captured["env"]["ARK_API_KEY"], PLACEHOLDER_KEY)   # overrides an inherited real key
            self.assertNotIn("ark-real", json.dumps(captured["env"]))

    def test_environment_variables_still_work_without_a_saved_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(Path(tmp) / "s.json")
            with mock.patch.dict(os.environ, {"ARK_API_KEY": "from-env", "DEEPSEEK_API_KEY": "llm-from-env"}):
                backend = agent_backend_from(settings, Path(tmp), MemoryStore())
            self.assertEqual(backend.cli.extra_env["ARK_API_KEY"], "from-env")
            self.assertEqual(backend.config.llm_key, "llm-from-env")


class SettingsDialogTests(unittest.TestCase):
    def make(self, tmp, store=None, **values):
        app()
        settings = Settings(Path(tmp) / "s.json")
        for key, value in values.items():
            settings.set(key, value)
        return settings, store if store is not None else MemoryStore()

    @staticmethod
    def type_into(field, text):
        field.clear()
        QTest.keyClicks(field, text)

    @staticmethod
    def choose(combo, data):
        combo.setCurrentIndex(combo.findData(data))

    def test_typed_keys_go_to_the_store_never_to_settings_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings, store = self.make(tmp)
            dialog = SettingsDialog(settings, store)
            self.type_into(dialog.llm_key, "llm-secret-1")
            self.type_into(dialog.gen_key, "ark-secret-2")
            dialog._save()
            self.assertEqual(store.get(key_name("deepseek")), "llm-secret-1")
            self.assertEqual(store.get(key_name("ark")), "ark-secret-2")
            self.assertEqual(key_name("deepseek"), LLM_KEY)         # the names older versions used still work
            self.assertEqual(key_name("ark"), ARK_KEY)
            self.assertNotIn("secret", (Path(tmp) / "s.json").read_text(encoding="utf-8"))
            self.assertEqual((settings.get("generation_service"), settings.get("llm_provider")), ("ark", "deepseek"))

    def test_choosing_a_provider_fills_in_its_saved_key_or_leaves_the_field_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings, store = self.make(tmp)
            store.set(key_name("deepseek"), "ds-key")
            store.set(key_name("anthropic"), "an-key")
            store.set(key_name("ark"), "ark-key")
            store.set(key_name("gemini"), "gm-key")
            dialog = SettingsDialog(settings, store)
            self.assertEqual((dialog.llm_key.text(), dialog.gen_key.text()), ("ds-key", "ark-key"))
            self.choose(dialog.llm_provider, "anthropic")
            self.assertEqual(dialog.llm_key.text(), "an-key")
            self.choose(dialog.llm_provider, "openai")                 # nothing saved for OpenAI
            self.assertEqual(dialog.llm_key.text(), "")
            self.assertIn("还没有设置密钥", dialog.llm_status.text())
            self.choose(dialog.llm_provider, "deepseek")
            self.assertEqual(dialog.llm_key.text(), "ds-key")
            for service, expected in (("gemini", "gm-key"), ("grok", ""), ("openai", ""), ("ark", "ark-key")):
                self.choose(dialog.service, service)
                self.assertEqual(dialog.gen_key.text(), expected, service)

    def test_edits_survive_switching_and_a_shared_provider_shows_one_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings, store = self.make(tmp)
            dialog = SettingsDialog(settings, store)
            self.type_into(dialog.llm_key, "typed-not-saved")
            self.choose(dialog.llm_provider, "anthropic")
            self.assertEqual(dialog.llm_key.text(), "")
            self.choose(dialog.llm_provider, "deepseek")
            self.assertEqual(dialog.llm_key.text(), "typed-not-saved")        # not lost on the way
            self.assertIn("保存后生效", dialog.llm_status.text())
            self.assertEqual(store.get(key_name("deepseek")), "")             # and still not written
            # the same provider as director and generator is one key
            self.choose(dialog.llm_provider, "openai")
            self.choose(dialog.service, "openai")
            self.type_into(dialog.llm_key, "sk-shared")
            self.assertEqual(dialog.gen_key.text(), "sk-shared")
            dialog._save()
            self.assertEqual(store.get(key_name("openai")), "sk-shared")

    def test_emptying_a_key_removes_it_but_other_providers_keep_theirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings, store = self.make(tmp)
            store.set(key_name("ark"), "ark-key")
            store.set(key_name("gemini"), "gm-key")
            dialog = SettingsDialog(settings, store)
            dialog._clear_generator_key()
            self.assertIn("保存后会清除", dialog.gen_status.text())
            dialog._save()
            self.assertEqual(store.get(key_name("ark")), "")
            self.assertEqual(store.get(key_name("gemini")), "gm-key")

    def test_providers_that_cannot_run_yet_say_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings, store = self.make(tmp)
            dialog = SettingsDialog(settings, store)
            self.assertEqual((dialog.llm_notice.text(), dialog.gen_notice.text()), ("", ""))   # DeepSeek and Ark run
            self.choose(dialog.llm_provider, "openai")
            self.assertIn("协议", dialog.llm_notice.text())
            self.choose(dialog.llm_provider, "anthropic")
            self.assertEqual(dialog.llm_notice.text(), "")
            self.choose(dialog.service, "openai")
            self.assertIn("还没有接入", dialog.gen_notice.text())
            self.assertFalse(dialog.whisperx_home.isEnabled())               # only Ark uses the local alignment service
            self.choose(dialog.service, "ark")
            self.assertTrue(dialog.whisperx_home.isEnabled())
            self.assertEqual([dialog.service.itemData(i) for i in range(dialog.service.count())],
                             ["ark", "openai", "gemini", "grok"])           # Anthropic makes no images or video
            self.assertEqual([dialog.llm_provider.itemData(i) for i in range(dialog.llm_provider.count())],
                             ["deepseek", "anthropic", "openai", "custom"])

    def test_choices_are_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings, store = self.make(tmp)
            dialog = SettingsDialog(settings, store)
            self.choose(dialog.llm_provider, "anthropic")
            self.choose(dialog.service, "gemini")
            dialog._save()
            self.assertEqual((settings.get("llm_provider"), settings.get("llm_base_url"), settings.get("llm_model")),
                             ("anthropic", "https://api.anthropic.com", "claude-sonnet-5-5"))
            self.assertEqual(settings.get("generation_service"), "gemini")
            dialog = SettingsDialog(settings, store)                           # reopened: the choices come back
            self.assertEqual((dialog.llm_provider.currentData(), dialog.service.currentData()), ("anthropic", "gemini"))
            self.choose(dialog.llm_provider, "custom")
            self.assertTrue(dialog.llm_base_url.isEnabled() and dialog.llm_model.isEnabled())
            dialog.llm_base_url.setText("https://llm.example/anthropic")
            dialog.llm_model.setText("my-model")
            dialog._save()
            self.assertEqual((settings.get("llm_base_url"), settings.get("llm_model")), ("https://llm.example/anthropic", "my-model"))

    def test_the_old_hypihub_service_only_shows_when_it_is_already_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings, store = self.make(tmp)
            first = SettingsDialog(settings, store)
            self.assertEqual(first.service.findData("hypihub"), -1)
            settings.set("generation_service", "hypihub")
            dialog = SettingsDialog(settings, store)
            self.assertEqual(dialog.service.currentData(), "hypihub")
            self.assertFalse(dialog.gen_key.isEnabled())

    def test_display_currency_is_a_setting_and_the_ledger_stays_in_dollars(self):
        from hypit_desktop import money
        with tempfile.TemporaryDirectory() as tmp:
            settings, store = self.make(tmp)
            try:
                dialog = SettingsDialog(settings, store)
                self.assertEqual(dialog.currency.currentData(), "CNY")            # the default for yuan-billed services
                dialog._save()
                self.assertEqual(money.fmt(0.68), "¥4.90")                         # 0.68 dollars in the ledger = 4.90 yuan
                self.choose(dialog.currency, "USD")
                dialog._save()
                self.assertEqual(settings.get("display_currency"), "USD")
                self.assertEqual(money.fmt(0.68), "$0.68")
            finally:
                money.configure("CNY")

    def test_connection_result_is_shown_and_the_entered_key_is_what_gets_tested(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings, store = self.make(tmp)
            store.set(key_name("ark"), "stored")
            dialog = SettingsDialog(settings, store)
            self.assertEqual(dialog._key_for_test(dialog.gen_key, "ark", "ARK_API_KEY"), "stored")   # auto-filled
            self.type_into(dialog.gen_key, "typed")
            self.assertEqual(dialog._key_for_test(dialog.gen_key, "ark", "ARK_API_KEY"), "typed")
            dialog.gen_key.clear()
            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "from-env"}):
                self.assertEqual(dialog._key_for_test(dialog.gen_key, "openai", "OPENAI_API_KEY"), "from-env")
            dialog._test_finished("generator", True, "连接正常")
            self.assertTrue(dialog.gen_status.text().startswith("✓"))
            dialog._test_finished("director", False, "密钥无效")
            self.assertTrue(dialog.llm_status.text().startswith("✗"))


class WhisperxHomeTests(unittest.TestCase):
    def test_the_service_folder_is_found_where_configured_or_at_the_standard_path(self):
        from hypit_desktop.agent import whisperx as wx
        from hypit_desktop.hypit.cli import HypitError
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "whisperx"
            exe = home / wx.SERVICE_EXE
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"")
            self.assertEqual(wx.find_whisperx_home(str(home)), home.resolve())
            with mock.patch.object(wx, "STANDARD_HOME", home):                       # no setting: the standard path
                self.assertEqual(wx.find_whisperx_home(""), home.resolve())
            with mock.patch.object(wx, "STANDARD_HOME", Path(tmp) / "nowhere"),                     mock.patch.object(wx, "PACKAGE_DIR", Path(tmp) / "a" / "b" / "c"):
                with self.assertRaises(HypitError):
                    wx.find_whisperx_home(str(Path(tmp) / "missing"))


class ProviderCheckTests(unittest.TestCase):
    @staticmethod
    def recording(status, body="{}", seen=None):
        def opener(request, timeout=0):
            if seen is not None:
                seen.update(url=request.full_url, method=request.get_method(),
                            headers={k.lower(): v for k, v in request.header_items()})
            if status == 200:
                return FakeResponse(200, body)
            raise urllib.error.HTTPError(request.full_url, status, "x", {}, io.BytesIO(body.encode("utf-8")))
        return opener

    def test_each_provider_is_checked_with_a_read_only_call_and_the_key_stays_in_a_header(self):
        expected = {"openai": ("api.openai.com", "authorization", "Bearer k-1"),
                    "grok": ("api.x.ai", "authorization", "Bearer k-1"),
                    "gemini": ("generativelanguage.googleapis.com", "x-goog-api-key", "k-1"),
                    "anthropic": ("api.anthropic.com", "x-api-key", "k-1")}
        for provider, (host, header, value) in expected.items():
            seen = {}
            ok, text = connection.test_key(provider, "k-1", opener=self.recording(200, seen=seen))
            self.assertTrue(ok, provider)
            self.assertEqual((seen["method"], host in seen["url"], seen["headers"][header]), ("GET", True, value), provider)
            self.assertNotIn("k-1", seen["url"])                              # never in the address
            self.assertFalse(connection.test_key(provider, "k-1", opener=self.recording(401))[0], provider)
        # Gemini and Grok answer a bad key with 400, not 401
        self.assertIn("不接受", connection.test_key("gemini", "bad", opener=self.recording(400, "API key not valid"))[1])
        self.assertIn("不接受", connection.test_key("grok", "bad", opener=self.recording(400))[1])
        self.assertIn("连不上", connection.test_key("openai", "k", opener=unreachable)[1])
        self.assertIn("还没有填写", connection.test_key("openai", "")[1])

    def test_anthropic_checks_the_chosen_model(self):
        seen = {}
        ok, _ = connection.test_anthropic("k", "https://api.anthropic.com", "claude-sonnet-5-5", opener=self.recording(200, seen=seen))
        self.assertTrue(ok)
        self.assertTrue(seen["url"].endswith("/v1/models/claude-sonnet-5-5"))
        ok, text = connection.test_anthropic("k", "https://api.anthropic.com", "claude-nope", opener=self.recording(404))
        self.assertFalse(ok)
        self.assertIn("用不了模型", text)
        self.assertFalse(connection.test_anthropic("bad", "https://api.anthropic.com", "m", opener=self.recording(401))[0])

    def test_dispatch_picks_the_right_check(self):
        seen = {}
        connection.test_provider("openai", "k", opener=self.recording(200, seen=seen))
        self.assertEqual(seen["method"], "GET")
        connection.test_provider("deepseek", "k", "https://api.deepseek.com/anthropic", "deepseek-flash",
                                 opener=self.recording(200, seen=seen))
        self.assertEqual((seen["method"], seen["url"].endswith("/v1/messages")), ("POST", True))
        connection.test_provider("anthropic", "k", "https://api.anthropic.com", "claude-sonnet-5-5",
                                 opener=self.recording(200, seen=seen))
        self.assertTrue(seen["url"].endswith("/v1/models/claude-sonnet-5-5"))

    def test_director_authentication_follows_the_provider(self):
        def env_for(auth, max_context):
            captured = {}
            sdk = types.SimpleNamespace(ClaudeAgentOptions=lambda **kw: captured.update(kw) or kw,
                                        PermissionResultDeny=object, PermissionResultAllow=object)
            dr.Director(Path("."), "the-key", "https://x", "m", "l.mjs", "node", auth=auth,
                        max_context=max_context)._options(False, sdk)
            return captured["env"]

        deepseek = env_for("bearer", 900_000)
        self.assertEqual((deepseek["ANTHROPIC_AUTH_TOKEN"], deepseek["ANTHROPIC_API_KEY"]), ("the-key", ""))
        self.assertEqual(deepseek["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "900000")
        anthropic = env_for("x-api-key", 0)
        self.assertEqual((anthropic["ANTHROPIC_API_KEY"], anthropic["ANTHROPIC_AUTH_TOKEN"]), ("the-key", ""))
        self.assertNotIn("CLAUDE_CODE_MAX_CONTEXT_TOKENS", anthropic)

    def test_the_factory_reads_the_chosen_providers_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(Path(tmp) / "s.json")
            store = MemoryStore()
            store.set(key_name("deepseek"), "ds")
            store.set(key_name("anthropic"), "an")
            settings.set("llm_provider", "anthropic")
            backend = agent_backend_from(settings, Path(tmp), store)
            self.assertEqual((backend.config.llm_key, backend.config.llm_auth, backend.config.llm_unavailable), ("an", "x-api-key", ""))
            settings.set("llm_provider", "openai")
            settings.set("generation_service", "openai")
            backend = agent_backend_from(settings, Path(tmp), store)
            self.assertIn("协议", backend.config.llm_unavailable)
            self.assertEqual(backend.config.generation_service, "openai")


if __name__ == "__main__":
    unittest.main()
