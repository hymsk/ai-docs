"""Isolated tests for the optional AI Docs Web manager."""

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[2]
MANAGER = SKILL_ROOT / "scripts" / "web-mcp-manager.py"


class WebMcpManagerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(SKILL_ROOT / "web-mcp/source"))
        spec = importlib.util.spec_from_file_location("ai_docs_manager_test", MANAGER)
        cls.manager = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.manager
        spec.loader.exec_module(cls.manager)

    def runtime_digest(self, runtime):
        digest = hashlib.sha256()
        files = []
        for path in runtime.rglob("*"):
            if path.is_file() and path.name != "runtime-manifest.json":
                files.append((path.relative_to(runtime).as_posix(), path))
        for relative, path in sorted(files):
            encoded = relative.encode("utf-8")
            content = path.read_bytes()
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
        return digest.hexdigest()

    def environment(self, root):
        home = root / "home"
        environment = dict(os.environ)
        environment.update({
            "HOME": str(home),
            "XDG_DATA_HOME": str(root / "data"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_CACHE_HOME": str(root / "cache"),
            "XDG_STATE_HOME": str(root / "state"),
        })
        return environment

    def run_raw(self, environment, *arguments):
        return subprocess.run(
            [sys.executable, str(MANAGER), *arguments],
            cwd=str(SKILL_ROOT), env=environment, capture_output=True, text=True,
            timeout=60, check=False,
        )

    def run_json(self, environment, *arguments):
        completed = self.run_raw(environment, *arguments)
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        return json.loads(completed.stdout)

    def test_plan_uses_xdg_user_paths_and_has_no_implicit_side_effects(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            payload = self.run_json(environment, "plan")
            self.assertEqual(payload["scope"], "user")
            self.assertEqual(payload["paths"]["runtime"], str(root / "data" / "ai-docs-web" / "runtime"))
            self.assertEqual(payload["paths"]["config"], str(root / "config" / "ai-docs-web" / "server.json"))
            self.assertIn("start the service", payload["does_not"])
            self.assertFalse((root / "data").exists())

    def test_install_is_idempotent_and_copies_only_the_canonical_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            first = self.run_json(environment, "install")
            second = self.run_json(environment, "install")
            status = self.run_json(environment, "status")
            runtime = root / "data" / "ai-docs-web" / "runtime"
            config = root / "config" / "ai-docs-web" / "server.json"
            credentials = root / "config" / "ai-docs-web" / "credentials.env"
            self.assertEqual(first["status"], "changed")
            self.assertEqual(second["status"], "current")
            self.assertEqual(status["status"], "current")
            self.assertTrue((runtime / "source" / "ai_docs_web.py").is_file())
            self.assertTrue((runtime / "scripts" / "build.js").is_file())
            self.assertTrue((runtime / "assets" / "default-resources.json").is_file())
            self.assertEqual((runtime / "VERSION").read_bytes(), (SKILL_ROOT / "VERSION").read_bytes())
            self.assertTrue((runtime / "LICENSE").is_file())
            self.assertTrue((runtime / "THIRD_PARTY_NOTICES.md").is_file())
            manifest = json.loads((runtime / "licenses/manifest.json").read_text(encoding="utf-8"))
            for entry in manifest["files"]:
                self.assertEqual(hashlib.sha256((runtime / entry["file"]).read_bytes()).hexdigest(), entry["sha256"])
            self.assertFalse((runtime / "scripts" / "vendor" / "viz.js").exists())
            value = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(value["mcp"]["reference"]["name"], "ai-docs")
            self.assertEqual(value["server"]["public"], {
                "scheme": "http", "host": "127.0.0.1", "port": 18080,
            })
            self.assertEqual(value["mcp"]["reference"]["scheme"], "http")
            self.assertEqual(value["mcp"]["reference"]["host"], "127.0.0.1")
            self.assertEqual(value["mcp"]["reference"]["port"], 18080)
            self.assertEqual(value["mcp"]["reference"]["path"], "/mcp")
            self.assertTrue(Path(value["renderer"]["node"]).is_absolute())
            self.assertEqual(value["max_rpc_bytes"], 6 * 1024 * 1024)
            self.assertIn("AI_DOCS_API_TOKEN=", credentials.read_text(encoding="utf-8"))
            self.assertNotIn("replace-with", credentials.read_text(encoding="utf-8"))
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            self.assertEqual(credentials.stat().st_mode & 0o777, 0o600)
            self.assertEqual(runtime.stat().st_mode & 0o777, 0o755)

            doctor = self.run_json(environment, "doctor")
            self.assertTrue(doctor["ok"])
            self.assertEqual(doctor["config"]["renderer_directory"], str(runtime))

    def test_user_unit_uses_unquoted_systemd_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            unit = root / "config" / "systemd" / "user" / "ai-docs-web.service"
            content = unit.read_text(encoding="utf-8")
            self.assertIn("WorkingDirectory={}".format(root / "cache" / "ai-docs-web" / "workspace"), content)
            self.assertNotIn('WorkingDirectory="', content)
            self.assertNotIn('EnvironmentFile="', content)
            self.assertIn("Environment=AI_DOCS_NODE=", content)
            self.assertNotIn('ReadOnlyPaths="', content)
            self.assertNotIn('ReadWritePaths="', content)

    def test_install_refuses_an_unmanaged_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            runtime = root / "data" / "ai-docs-web" / "runtime"
            runtime.mkdir(parents=True)
            completed = self.run_raw(environment, "install")
            self.assertEqual(completed.returncode, 1)
            self.assertIn("without matching managed state", completed.stderr)

    def test_install_rejects_a_bind_host_with_an_embedded_port(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            completed = self.run_raw(environment, "install", "--bind-host", "127.0.0.1:18080")
            self.assertEqual(completed.returncode, 1)
            self.assertIn("valid hostname, IPv4 address", completed.stderr)

    def test_install_derives_public_and_mcp_addresses_from_host_port_and_schemes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(
                environment,
                "install",
                "--bind-host", "127.0.0.2",
                "--port", "19090",
                "--public-scheme", "https",
                "--public-host", "docs.example.test",
                "--public-port", "443",
                "--mcp-scheme", "http",
                "--mcp-host", "127.0.0.2",
                "--mcp-port", "19090",
            )
            config = json.loads((root / "config" / "ai-docs-web" / "server.json").read_text(encoding="utf-8"))
            self.assertEqual(config["server"]["host"], "127.0.0.2")
            self.assertEqual(config["server"]["port"], 19090)
            self.assertEqual(config["server"]["public"], {
                "scheme": "https", "host": "docs.example.test", "port": 443,
            })
            self.assertEqual(config["mcp"]["reference"]["host"], "127.0.0.2")
            self.assertEqual(config["mcp"]["reference"]["port"], 19090)

    def test_wildcard_bind_requires_an_explicit_public_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            completed = self.run_raw(environment, "install", "--bind-host", "0.0.0.0")
            self.assertEqual(completed.returncode, 1)
            self.assertIn("--public-host is required", completed.stderr)

    def test_install_repairs_private_user_config_and_credential_permissions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            config = root / "config" / "ai-docs-web" / "server.json"
            credentials = root / "config" / "ai-docs-web" / "credentials.env"
            config.chmod(0o644)
            credentials.chmod(0o644)
            status = self.run_json(environment, "status")
            self.assertEqual(status["status"], "not-installed-or-drifted")
            doctor = self.run_raw(environment, "doctor")
            self.assertEqual(doctor.returncode, 1)
            self.assertIn("permissions are not private", doctor.stderr)
            repaired = self.run_json(environment, "install")
            self.assertIn("server configuration_permissions", repaired["changed"])
            self.assertIn("credentials_permissions", repaired["changed"])
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            self.assertEqual(credentials.stat().st_mode & 0o777, 0o600)

    def test_doctor_uses_the_installed_absolute_node_path_not_the_current_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            empty_bin = root / "empty-bin"
            empty_bin.mkdir()
            environment["PATH"] = str(empty_bin)
            doctor = self.run_json(environment, "doctor")
            configured = json.loads((root / "config" / "ai-docs-web" / "server.json").read_text(encoding="utf-8"))
            self.assertEqual(doctor["node"]["executable"], configured["renderer"]["node"])

    def test_opencode_registration_is_managed_and_unmanaged_conflicts_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            registered = self.run_json(environment, "register", "--host", "opencode")
            current = self.run_json(environment, "register", "--host", "opencode")
            config = root / "config" / "opencode" / "opencode.json"
            entry = json.loads(config.read_text(encoding="utf-8"))["mcp"]["ai-docs"]
            self.assertEqual(registered["status"], "changed")
            self.assertEqual(current["status"], "current")
            self.assertEqual(entry["headers"]["Authorization"], "Bearer {env:AI_DOCS_API_TOKEN}")
            removed = self.run_json(environment, "unregister", "--host", "opencode")
            self.assertEqual(removed["status"], "changed")
            self.assertNotIn("mcp", json.loads(config.read_text(encoding="utf-8")))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            config = root / "config" / "opencode" / "opencode.json"
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({"mcp": {"ai-docs": {"type": "remote", "url": "https://other.test/mcp"}}}), encoding="utf-8")
            completed = self.run_raw(environment, "register", "--host", "opencode")
            self.assertEqual(completed.returncode, 1)
            self.assertIn("unmanaged", completed.stderr)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            config = root / "config" / "opencode" / "opencode.json"
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({"mcp": {"ai-docs": "keep-me"}}), encoding="utf-8")
            completed = self.run_raw(environment, "register", "--host", "opencode")
            self.assertEqual(completed.returncode, 1)
            self.assertIn("unmanaged", completed.stderr)
            self.assertEqual(json.loads(config.read_text(encoding="utf-8"))["mcp"]["ai-docs"], "keep-me")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            config = root / "config" / "opencode" / "opencode.json"
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({"mcp": {"ai-docs": None}}), encoding="utf-8")
            completed = self.run_raw(environment, "register", "--host", "opencode")
            self.assertEqual(completed.returncode, 1)
            self.assertIn("unmanaged", completed.stderr)
            self.assertIsNone(json.loads(config.read_text(encoding="utf-8"))["mcp"]["ai-docs"])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            config = root / "config" / "opencode" / "opencode.json"
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({"mcp": {"ai-docs": {
                "type": "remote",
                "url": "http://127.0.0.1:18080/mcp",
                "enabled": True,
                "oauth": False,
                "timeout": 30000,
                "headers": {"Authorization": "Bearer {env:AI_DOCS_API_TOKEN}"},
            }}}), encoding="utf-8")
            completed = self.run_raw(environment, "register", "--host", "opencode")
            self.assertEqual(completed.returncode, 1)
            self.assertIn("unmanaged", completed.stderr)

    def test_install_creates_a_private_preview_library_writable_by_the_service(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            library = root / "data" / "ai-docs-web" / "data" / "private" / "library"
            config = json.loads((root / "config" / "ai-docs-web" / "server.json").read_text(encoding="utf-8"))
            self.assertTrue(library.is_dir())
            self.assertEqual(library.stat().st_mode & 0o777, 0o700)
            self.assertEqual(config["library_directory"], str(library))
            self.assertEqual(config["schema_version"], 2)
            self.assertEqual(config["public_directory"], "public")
            self.assertTrue((library / "public").is_dir())
            self.assertEqual((library / "public").stat().st_mode & 0o777, 0o700)
            self.assertEqual(config["preview"], {
                "enabled": True, "path": "/preview", "write_back": True, "session_seconds": 43200,
            })
            self.assertEqual(config["library_limits"], {
                "max_files": 1000, "max_total_bytes": 52428800, "max_path_depth": 8,
            })
            unit = (root / "config" / "systemd" / "user" / "ai-docs-web.service").read_text(encoding="utf-8")
            read_write = [line for line in unit.splitlines() if line.startswith("ReadWritePaths=")][0]
            self.assertEqual(read_write, "ReadWritePaths={} {}".format(config["workspace_root"], library))
            status = self.run_json(environment, "status")
            self.assertEqual(status["status"], "current")
            self.assertEqual(status["details"]["paths"]["library"], str(library))

    def test_upgrade_migrates_a_v1_configuration_and_keeps_a_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            config_path = root / "config" / "ai-docs-web" / "server.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            v1 = {
                "schema_version": 1,
                "workspace_root": config["workspace_root"],
                "documents_directory": str(root / "data" / "ai-docs-web" / "data" / "public" / "docs"),
                "static_directory": str(root / "data" / "ai-docs-web" / "data" / "public" / "static"),
                "metadata_directory": str(root / "data" / "ai-docs-web" / "data" / "private" / "metadata"),
                "library_directory": config["library_directory"],
                "server": dict(config["server"], static_prefix="/static/"),
                "preview": dict(config["preview"], **config["library_limits"]),
                "mcp": config["mcp"],
                "renderer": config["renderer"],
            }
            config_path.write_text(json.dumps(v1), encoding="utf-8")
            payload = self.run_json(environment, "upgrade")
            self.assertIn("config_migration", payload["changed"])
            migrated = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(migrated["schema_version"], 2)
            self.assertNotIn("documents_directory", migrated)
            self.assertNotIn("static_prefix", migrated["server"])
            self.assertEqual(migrated["library_limits"]["max_files"], 1000)
            self.assertEqual(migrated["preview"], config["preview"])
            backup = json.loads((config_path.parent / "server.json.v1-backup").read_text(encoding="utf-8"))
            self.assertEqual(backup["schema_version"], 1)
            doctor = self.run_json(environment, "doctor")
            self.assertTrue(doctor["ok"])

    def test_upgrade_refuses_migration_when_public_root_has_markdown(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            config_path = root / "config" / "ai-docs-web" / "server.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            library = Path(config["library_directory"])
            (library / "public" / "stale.md").write_text("# stale\n", encoding="utf-8")
            v1 = dict(config, schema_version=1)
            v1.pop("public_directory")
            config_path.write_text(json.dumps(v1), encoding="utf-8")
            completed = self.run_raw(environment, "upgrade")
            self.assertEqual(completed.returncode, 1)
            self.assertIn("would publish existing Markdown", completed.stderr)
            # 拒绝迁移时配置保持 v1 原样
            self.assertEqual(json.loads(config_path.read_text(encoding="utf-8"))["schema_version"], 1)
            self.assertFalse((config_path.parent / "server.json.v1-backup").exists())

    def test_preview_write_back_false_keeps_private_library_readonly_but_public_writable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            config_path = root / "config" / "ai-docs-web" / "server.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["preview"]["write_back"] = False
            config_path.write_text(json.dumps(config), encoding="utf-8")
            library = config["library_directory"]

            self.assertEqual(self.run_json(environment, "status")["status"], "not-installed-or-drifted")
            upgraded = self.run_json(environment, "upgrade")

            self.assertIn("systemd_unit", upgraded["changed"])
            unit = (root / "config" / "systemd" / "user" / "ai-docs-web.service").read_text(encoding="utf-8")
            read_write = [line for line in unit.splitlines() if line.startswith("ReadWritePaths=")][0]
            self.assertEqual(read_write, "ReadWritePaths={} {}".format(config["workspace_root"], Path(library) / "public"))
            self.assertIn("ReadOnlyPaths={} {}".format(root / "data" / "ai-docs-web" / "runtime", library), unit)
            self.assertNotIn("ReadWritePaths= ", read_write)
            self.assertEqual(self.run_json(environment, "status")["status"], "current")

    def test_custom_storage_paths_are_created_escaped_and_preserved_on_upgrade(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            config_path = root / "config/ai-docs-web/server.json"
            config = json.loads(config_path.read_text())
            library = root / 'custom library %name "quoted"'
            workspace = root / "custom workspace"
            public = library / "published docs/nested"
            config.update(library_directory=str(library), workspace_root=str(workspace), public_directory="published docs/nested")
            config["preview"]["write_back"] = False
            config_path.write_text(json.dumps(config))
            self.run_json(environment, "upgrade")
            self.assertTrue(public.is_dir())
            self.assertTrue(workspace.is_dir())
            unit = (root / "config/systemd/user/ai-docs-web.service").read_text()
            escape = self.manager._systemd_path
            self.assertIn("ReadWritePaths={} {}\n".format(escape(workspace), escape(public)), unit)
            self.assertIn("ReadOnlyPaths={} {}\n".format(escape(root / "data/ai-docs-web/runtime"), escape(library)), unit)
            self.assertIn(r'custom\x20library\x20%%name\x20\x22quoted\x22', unit)
            self.assertEqual(self.run_json(environment, "upgrade")["status"], "current")
            status = self.run_json(environment, "status")
            self.assertEqual(status["details"]["paths"]["library"], str(library))
            self.assertEqual(status["details"]["paths"]["public"], str(public))
            self.assertTrue(self.run_json(environment, "doctor")["ok"])
            # Exercise the actual store without starting an HTTP/systemd service.
            from ai_docs_config import ServiceConfig
            from ai_docs_library import LibraryStore, PreviewStore
            from ai_docs_common import ServiceError
            validated = ServiceConfig(config_path)
            store = LibraryStore(validated)
            store.publish("guide/intro.md", "# Published\n")
            self.assertEqual((public / "guide/intro.md").read_text(), "# Published\n")
            with self.assertRaises(ServiceError) as denied:
                PreviewStore(validated, threading.BoundedSemaphore(1), store).save("private.md", "# Private\n")
            self.assertEqual(denied.exception.code, "write_back_disabled")
            self.assertFalse((library / "private.md").exists())
            config["preview"]["write_back"] = True
            config_path.write_text(json.dumps(config))
            self.run_json(environment, "upgrade")
            self.assertIn("ReadWritePaths={} {}\n".format(escape(workspace), escape(library)), (root / "config/systemd/user/ai-docs-web.service").read_text())

    def test_upgrade_rejects_unsafe_storage_before_changing_managed_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            config_path = root / "config/ai-docs-web/server.json"
            original = json.loads(config_path.read_text())
            unit = root / "config/systemd/user/ai-docs-web.service"
            before = unit.read_bytes()
            target = root / "target"
            target.mkdir()
            link = root / "link"
            link.symlink_to(target, target_is_directory=True)
            file_path = root / "file"
            file_path.write_text("not a directory")
            cases = [
                {"library_directory": "relative"},
                {"library_directory": "~/library"},
                {"library_directory": "/"},
                {"library_directory": "//"},
                {"library_directory": "/" + original["workspace_root"]},
                {"library_directory": str(root / "other/../target")},
                {"library_directory": str(root / "bad\nReadWritePaths=/")},
                {"library_directory": str(link)},
                {"library_directory": str(link / "nested")},
                {"library_directory": str(file_path)},
                {"library_directory": str(file_path / "nested")},
                {"library_directory": original["workspace_root"]},
                {"library_directory": str(root / "data/ai-docs-web/runtime")},
                {"public_directory": "../outside"},
                {"public_directory": "/outside"},
                {"public_directory": "."},
                {"public_directory": "part/" * 33 + "end"},
                {"preview": {"write_back": "false"}},
            ]
            public_link = Path(original["library_directory"]) / "linked"
            public_link.symlink_to(target, target_is_directory=True)
            cases.extend([{"public_directory": "linked"}, {"public_directory": "linked/nested"}])
            for changes in cases:
                with self.subTest(changes=changes):
                    config_path.write_text(json.dumps(dict(original, **changes)))
                    config_before = config_path.read_bytes()
                    completed = self.run_raw(environment, "upgrade")
                    self.assertEqual(completed.returncode, 1, completed.stdout)
                    self.assertNotIn("Traceback", completed.stderr)
                    self.assertEqual(unit.read_bytes(), before)
                    self.assertEqual(config_path.read_bytes(), config_before)

    def test_system_scope_custom_storage_uses_safe_mounts_and_new_directory_ownership(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with mock.patch.dict(os.environ, self.environment(root)):
                paths = replace(self.manager.install_paths("user"), scope="system")
            config = {"library_directory": str(root / "custom"), "workspace_root": str(root / "work"),
                      "public_directory": "docs/nested", "preview": {"write_back": False}}
            storage = self.manager._storage_settings(paths, config)
            unit = self.manager._unit_content(paths, Path(sys.executable), storage).decode()
            self.assertIn("User=ai-docs\nGroup=ai-docs\n", unit)
            self.assertIn("ProtectHome=true", unit)
            self.assertIn("ReadWritePaths={} {}\n".format(storage.workspace, storage.public), unit)
            self.assertIn("ReadOnlyPaths={} {}\n".format(paths.runtime, storage.library), unit)
            account = SimpleNamespace(pw_uid=12345, pw_gid=12346)
            with mock.patch.object(self.manager.pwd, "getpwnam", return_value=account), mock.patch.object(self.manager.os, "chown") as chown:
                self.manager._create_directories(paths, storage)
                for directory in (storage.workspace, storage.library, storage.library / "docs", storage.public):
                    self.assertTrue(directory.is_dir())
                    chown.assert_any_call(directory, 12345, 12346)
                chown.reset_mock()
                self.manager._create_directories(paths, storage)
                chown.assert_not_called()
            for forbidden in (str(Path("/root") / "library"), "/home/service/library", "/run/user/123/library"):
                with self.subTest(path=forbidden), self.assertRaisesRegex(self.manager.ManagerError, "outside home"):
                    self.manager._storage_settings(paths, dict(config, library_directory=forbidden))

    def test_storage_settings_permission_error_is_a_clean_rejection(self):
        # 非 root 安装账户对 /root 下路径做 lstat 会 PermissionError（CI 等
        # 环境）；存储路径校验必须把它变成干净的 ManagerError 而非 traceback。
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with mock.patch.dict(os.environ, self.environment(root)):
                paths = replace(self.manager.install_paths("user"), scope="system")
            config = {"library_directory": str(root / "custom"), "workspace_root": str(root / "work"),
                      "public_directory": "docs", "preview": {"write_back": False}}
            with mock.patch.object(self.manager.Path, "is_symlink", side_effect=PermissionError(13, "Permission denied")):
                with self.assertRaisesRegex(self.manager.ManagerError, "not accessible"):
                    self.manager._storage_settings(paths, config)

    def test_v1_derived_custom_library_is_used_on_first_upgrade(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            config_path = root / "config/ai-docs-web/server.json"
            config = json.loads(config_path.read_text())
            config.update(schema_version=1, documents_directory=str(root / "legacy/public/docs"))
            config.pop("library_directory")
            config.pop("public_directory")
            config["preview"]["write_back"] = False
            config_path.write_text(json.dumps(config))
            self.run_json(environment, "upgrade")
            library = root / "legacy/private/library"
            self.assertTrue((library / "public").is_dir())
            self.assertEqual(json.loads(config_path.read_text())["library_directory"], str(library))
            unit = (root / "config/systemd/user/ai-docs-web.service").read_text()
            self.assertIn("ReadWritePaths={} {}\n".format(config["workspace_root"], library / "public"), unit)
            self.assertEqual(self.run_json(environment, "upgrade")["status"], "current")

    def test_purge_removes_the_preview_library(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            library = root / "data" / "ai-docs-web" / "data" / "private" / "library"
            (library / "note.md").write_text("# note\n", encoding="utf-8")
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text("#!/bin/sh\ncase \"$*\" in *is-enabled*) echo disabled; exit 1;; *is-active*) echo inactive; exit 3;; *) exit 0;; esac\n", encoding="utf-8")
            fake_systemctl.chmod(0o755)
            environment["PATH"] = str(fake_bin) + os.pathsep + environment.get("PATH", "")

            self.run_json(environment, "uninstall")
            self.assertTrue((library / "note.md").is_file())
            self.run_json(environment, "install")
            self.run_json(environment, "uninstall", "--purge")
            self.assertFalse(library.exists())

    def test_proxy_login_template_scopes_private_token_to_session_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            config_path = root / "config" / "ai-docs-web" / "server.json"
            config = json.loads(config_path.read_text())
            config["preview"]["login_mode"] = "proxy"
            config_path.write_text(json.dumps(config))
            output = root / "proxy.conf"
            self.run_json(environment, "nginx-template", "--public-scheme", "https", "--public-host", "docs.example.test", "--output", str(output))
            default = output.read_text()
            self.assertIn("location ^~ /preview/ { return 404; }", default)
            self.assertNotIn("location = /preview/session", default)
            self.assertNotIn("ai-docs-session-auth.inc", default)
            output.unlink()
            self.run_json(environment, "nginx-template", "--public-scheme", "https", "--public-host", "docs.example.test", "--output", str(output), "--expose-preview")
            template = output.read_text()
            self.assertIn("location = /preview/session", template)
            self.assertIn('if ($http_origin != "https://docs.example.test")', template)
            self.assertIn('proxy_set_header Authorization "";', template)
            self.assertEqual(template.count("include /etc/nginx/ai-docs-session-auth.inc;"), 1)
            self.assertIn("location = /mcp { return 404; }", template)
            config["preview"]["path"] = "/private-preview"
            config_path.write_text(json.dumps(config))
            output.unlink()
            self.run_json(environment, "nginx-template", "--public-scheme", "https", "--public-host", "docs.example.test", "--output", str(output), "--expose-preview", "--expose-mcp")
            combined = output.read_text()
            self.assertIn("location = /private-preview/session", combined)
            self.assertIn('auth_basic "AI Docs preview";', combined)
            self.assertNotIn("location = /mcp { return 404; }", combined)
            self.assertEqual(combined.count("include /etc/nginx/ai-docs-session-auth.inc;"), 1)
            self.assertEqual(self.run_json(environment, "nginx-template", "--public-scheme", "https", "--public-host", "docs.example.test", "--output", str(output), "--expose-preview", "--expose-mcp")["status"], "current")
            output.unlink()
            self.run_json(environment, "nginx-template", "--public-scheme", "https", "--public-host", "docs.example.test", "--output", str(output), "--expose-mcp")
            self.assertIn("location ^~ /private-preview/ { return 404; }", output.read_text())
            self.assertNotIn("ai-docs-session-auth.inc", output.read_text())

    def test_nginx_template_exposes_mcp_only_with_the_explicit_flag(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            output = root / "public-mcp.conf"
            self.run_json(
                environment, "nginx-template", "--public-scheme", "https",
                "--public-host", "docs.example.test", "--output", str(output), "--expose-mcp",
            )
            template = output.read_text(encoding="utf-8")
            self.assertNotIn("location = /mcp { return 404; }", template)
            self.assertIn("limit_req_zone $binary_remote_addr zone=ai_docs_mcp:10m rate=30r/m;", template)
            self.assertIn("limit_req_status 429;", template)
            self.assertIn("location = /mcp {", template)
            mcp_block = template.split("location = /mcp {", 1)[1].split("}", 1)[0]
            self.assertIn("limit_req zone=ai_docs_mcp burst=10;", mcp_block)
            self.assertIn("proxy_pass http://127.0.0.1:18080;", mcp_block)
            # The backend authenticates Bearer tokens itself; the proxy must
            # not touch Authorization, but alternate auth headers and client
            # controlled forwarding headers are stripped.
            self.assertNotIn('proxy_set_header Authorization', mcp_block)
            self.assertIn('proxy_set_header X-AI-Docs-Token "";', mcp_block)
            self.assertIn('proxy_set_header Forwarded "";', mcp_block)
            self.assertIn("proxy_read_timeout 130s;", mcp_block)
            self.assertIn("location = /healthz { return 404; }", template)
            self.assertIn("location ^~ /v1/ { return 404; }", template)
            self.assertIn("location ^~ /preview/ { return 404; }", template)
            self.assertNotIn("auth_basic", template)

    def test_nginx_template_404s_the_preview_route_by_default_and_proxies_it_with_basic_auth(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            config_path = root / "config" / "ai-docs-web" / "server.json"
            output = root / "ai-docs.conf"

            self.run_json(environment, "install")
            config = json.loads(config_path.read_text(encoding="utf-8"))
            self.run_json(
                environment, "nginx-template", "--public-scheme", "https",
                "--public-host", "docs.example.test", "--output", str(output),
            )
            disabled = output.read_text(encoding="utf-8")
            self.assertIn("location = /preview { return 404; }", disabled)
            self.assertIn("location ^~ /preview/ { return 404; }", disabled)
            self.assertNotIn("auth_basic", disabled)

            config["preview"]["enabled"] = True
            config_path.write_text(json.dumps(config), encoding="utf-8")
            output.unlink()
            # 默认 token 登录模式下拒绝生成：登录页的 Bearer 会被 Basic Auth 先行拒绝，
            # 生成的配置必然无法登录，必须报错而不是产出不可用的模板。
            rejected = self.run_raw(
                environment, "nginx-template", "--public-scheme", "https",
                "--public-host", "docs.example.test", "--output", str(output), "--expose-preview",
            )
            self.assertEqual(rejected.returncode, 1)
            self.assertIn('requires preview.login_mode="proxy"', rejected.stderr)
            self.assertFalse(output.exists())

            config["preview"]["login_mode"] = "proxy"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            self.run_json(
                environment, "nginx-template", "--public-scheme", "https",
                "--public-host", "docs.example.test", "--output", str(output), "--expose-preview",
            )
            enabled = output.read_text(encoding="utf-8")
            self.assertIn("location ^~ /preview/", enabled)
            self.assertIn('auth_basic "AI Docs preview";', enabled)
            self.assertIn("/etc/nginx/ai-docs-preview.htpasswd", enabled)
            self.assertIn("proxy_read_timeout 120s;", enabled)
            self.assertIn("location = /preview/session", enabled)
            preview_block = enabled.split("location ^~ /preview/", 1)[1].split("}", 1)[0]
            self.assertNotIn("X-Forwarded-Proto", preview_block)
            self.assertNotIn("X-Forwarded-For", preview_block)
            self.assertIn("location ^~ /docs/", enabled)
            self.assertIn("location = /mcp { return 404; }", enabled)

    def test_expose_preview_rejects_disabled_or_absent_backend_without_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            output = root / "preview.conf"
            arguments = ("nginx-template", "--public-scheme", "https", "--public-host", "docs.example.test", "--output", str(output), "--expose-preview")
            absent = self.run_raw(environment, *arguments)
            self.assertEqual(absent.returncode, 1)
            self.assertIn("requires backend preview.enabled=true", absent.stderr)
            self.assertFalse(output.exists())
            self.run_json(environment, "install")
            config_path = root / "config/ai-docs-web/server.json"
            config = json.loads(config_path.read_text())
            config["preview"]["enabled"] = False
            config_path.write_text(json.dumps(config))
            disabled = self.run_raw(environment, *arguments, "--expose-mcp")
            self.assertEqual(disabled.returncode, 1)
            self.assertFalse(output.exists())
            self.run_json(environment, *arguments[:-1])
            self.assertIn("location ^~ /preview/ { return 404; }", output.read_text())

    def test_upgrade_refuses_runtime_and_unit_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            runtime_file = root / "data" / "ai-docs-web" / "runtime" / "source" / "ai_docs_web.py"
            runtime_file.write_text(runtime_file.read_text(encoding="utf-8") + "\n# local drift\n", encoding="utf-8")
            completed = self.run_raw(environment, "upgrade")
            self.assertEqual(completed.returncode, 1)
            self.assertIn("runtime has drifted", completed.stderr)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            unit = root / "config" / "systemd" / "user" / "ai-docs-web.service"
            unit.write_text(unit.read_text(encoding="utf-8") + "\n# local drift\n", encoding="utf-8")
            completed = self.run_raw(environment, "upgrade")
            self.assertEqual(completed.returncode, 1)
            self.assertIn("unit is unmanaged or has drifted", completed.stderr)

    def test_upgrade_removes_a_retired_managed_runtime_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            runtime = root / "data" / "ai-docs-web" / "runtime"
            retired = runtime / "scripts" / "vendor" / "viz.js"
            retired.write_text("retired managed vendor\n", encoding="utf-8")
            old_digest = self.runtime_digest(runtime)
            state_path = root / "state" / "ai-docs-web" / "install.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["source_digest"] = old_digest
            state_path.write_text(json.dumps(state), encoding="utf-8")
            manifest_path = runtime / "runtime-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["source_digest"] = old_digest
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            upgraded = self.run_json(environment, "upgrade")

            self.assertEqual(upgraded["status"], "changed")
            self.assertIn("runtime", upgraded["changed"])
            self.assertFalse(retired.exists())
            self.assertEqual(self.run_json(environment, "status")["status"], "current")

    def test_registration_rejects_unsafe_urls_and_managed_name_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            config = root / "config" / "ai-docs-web" / "server.json"
            value = json.loads(config.read_text(encoding="utf-8"))
            value["mcp"]["reference"]["host"] = "https://invalid.example.test"
            config.write_text(json.dumps(value), encoding="utf-8")
            completed = self.run_raw(environment, "register", "--host", "opencode")
            self.assertEqual(completed.returncode, 1)
            self.assertIn("must not contain URL syntax", completed.stderr)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            self.run_json(environment, "register", "--host", "opencode")
            config = root / "config" / "ai-docs-web" / "server.json"
            value = json.loads(config.read_text(encoding="utf-8"))
            value["mcp"]["reference"]["name"] = "renamed-ai-docs"
            config.write_text(json.dumps(value), encoding="utf-8")
            completed = self.run_raw(environment, "register", "--host", "opencode")
            self.assertEqual(completed.returncode, 1)
            self.assertIn("unregister the previous managed entry", completed.stderr)

    def test_https_nginx_template_exposes_dynamic_docs_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            output = root / "review" / "ai-docs.conf"
            payload = self.run_json(
                environment, "nginx-template", "--public-scheme", "https", "--public-host", "docs.example.test", "--output", str(output)
            )
            content = output.read_text(encoding="utf-8")
            self.assertEqual(payload["status"], "changed")
            self.assertIn("location ^~ /docs/", content)
            self.assertIn("limit_req_zone $binary_remote_addr zone=ai_docs_docs:10m rate=120r/m;", content)
            self.assertIn("limit_req zone=ai_docs_docs burst=40;", content)
            self.assertIn("location = /mcp { return 404; }", content)
            # 缓存策略由后端决定：/docs/ 永不缓存，/assets/ 由后端发 immutable，
            # 模板本身不得声明任何 Cache-Control。
            self.assertIn("location ^~ /assets/", content)
            self.assertNotIn("Cache-Control", content)
            self.assertNotIn("static", content)

    def test_nginx_template_uses_the_configured_service_port(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install", "--port", "19090")
            output = root / "ai-docs.conf"
            self.run_json(
                environment, "nginx-template", "--public-scheme", "https", "--public-host", "docs.example.test", "--output", str(output)
            )
            self.assertIn("proxy_pass http://127.0.0.1:19090;", output.read_text(encoding="utf-8"))

    def test_nginx_template_uses_the_configured_ipv4_and_ipv6_bind_hosts(self):
        for bind_host, expected in (("127.0.0.2", "127.0.0.2:18080"), ("::1", "[::1]:18080")):
            with self.subTest(bind_host=bind_host), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                environment = self.environment(root)
                self.run_json(environment, "install", "--bind-host", bind_host)
                output = root / "ai-docs.conf"
                self.run_json(
                    environment, "nginx-template", "--public-scheme", "https",
                    "--public-host", "docs.example.test", "--output", str(output),
                )
                self.assertIn("proxy_pass http://{};".format(expected), output.read_text(encoding="utf-8"))

    def test_nginx_template_uses_the_configured_document_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            config = root / "config" / "ai-docs-web" / "server.json"
            value = json.loads(config.read_text(encoding="utf-8"))
            value["server"]["documents_prefix"] = "/ai-docs/docs/"
            value["preview"]["login_mode"] = "proxy"
            config.write_text(json.dumps(value), encoding="utf-8")
            output = root / "ai-docs.conf"
            self.run_json(
                environment, "nginx-template", "--public-scheme", "https", "--public-host", "docs.example.test", "--output", str(output), "--expose-preview"
            )
            content = output.read_text(encoding="utf-8")
            self.assertIn("location ^~ /ai-docs/docs/", content)
            self.assertNotIn("static", content)
            # 显式公开 preview 时保持 noindex，docs 可索引
            self.assertIn('add_header X-Robots-Tag "noindex, nofollow" always;', content)

    def test_nginx_template_honors_a_non_default_https_port(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            output = root / "ai-docs.conf"
            self.run_json(
                environment, "nginx-template", "--public-scheme", "https", "--public-host", "docs.example.test", "--public-port", "8443", "--output", str(output)
            )
            self.assertIn("listen 8443 ssl http2;", output.read_text(encoding="utf-8"))

    def test_nginx_template_follows_configured_mcp_path_and_render_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            config_path = root / "config" / "ai-docs-web" / "server.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["mcp"]["path"] = "/custom-mcp"
            config["public_docs"] = dict(config.get("public_docs", {}), render_timeout_seconds=120)
            config_path.write_text(json.dumps(config), encoding="utf-8")
            output = root / "ai-docs.conf"

            # 未暴露 MCP 时 404 占位也跟随配置路径；docs 代理读超时为 120+15。
            self.run_json(
                environment, "nginx-template", "--public-scheme", "https",
                "--public-host", "docs.example.test", "--output", str(output),
            )
            template = output.read_text(encoding="utf-8")
            self.assertIn("location = /custom-mcp { return 404; }", template)
            self.assertNotIn("location = /mcp { return 404; }", template)
            self.assertIn("proxy_read_timeout 135s;", template)
            self.assertNotIn("proxy_read_timeout 45s;", template)

            output.unlink()
            self.run_json(
                environment, "nginx-template", "--public-scheme", "https",
                "--public-host", "docs.example.test", "--output", str(output), "--expose-mcp",
            )
            exposed = output.read_text(encoding="utf-8")
            self.assertIn("location = /custom-mcp {", exposed)
            self.assertNotIn("location = /mcp {", exposed)
            self.assertIn("limit_req zone=ai_docs_mcp burst=10;", exposed)

            # 对 Nginx location 不安全的路径值直接拒绝，不产出畸形模板。
            config["mcp"]["path"] = '/mcp"; }'
            config_path.write_text(json.dumps(config), encoding="utf-8")
            rejected = self.run_raw(
                environment, "nginx-template", "--public-scheme", "https",
                "--public-host", "docs.example.test", "--output", str(output),
            )
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("unsafe for an Nginx location", rejected.stderr)

    def test_failed_migration_rollback_restores_config_and_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            config_path = root / "config" / "ai-docs-web" / "server.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            v1 = {
                "schema_version": 1,
                "workspace_root": config["workspace_root"],
                "documents_directory": str(root / "data" / "ai-docs-web" / "data" / "public" / "docs"),
                "static_directory": str(root / "data" / "ai-docs-web" / "data" / "public" / "static"),
                "metadata_directory": str(root / "data" / "ai-docs-web" / "data" / "private" / "metadata"),
                "library_directory": config["library_directory"],
                "server": dict(config["server"], static_prefix="/static/"),
                "preview": dict(config["preview"], **config["library_limits"]),
                "mcp": config["mcp"],
                "renderer": config["renderer"],
            }
            config_path.write_text(json.dumps(v1), encoding="utf-8")
            backup_path = config_path.with_name(config_path.name + ".v1-backup")
            backup_path.write_text('{"legacy": true}\n', encoding="utf-8")

            args = SimpleNamespace(
                bind_host="127.0.0.1", port=18080, public_scheme="http", public_host=None,
                public_port=None, mcp_scheme="http", mcp_host=None, mcp_port=None,
            )

            def migrate_with_injected_failure():
                with mock.patch.dict(os.environ, environment):
                    paths = self.manager.install_paths("user")
                    with mock.patch.object(
                        self.manager, "_apply_system_config_permissions",
                        side_effect=self.manager.ManagerError("injected permission failure"),
                    ):
                        self.manager._install(paths, args)

            # 既有 backup：回滚必须恢复其迁移前内容，而不是留下本次写入。
            with self.assertRaisesRegex(self.manager.ManagerError, "injected permission failure"):
                migrate_with_injected_failure()
            self.assertEqual(json.loads(config_path.read_text(encoding="utf-8"))["schema_version"], 1)
            self.assertEqual(backup_path.read_text(encoding="utf-8"), '{"legacy": true}\n')

            # 无既有 backup：回滚必须删除本次新建的 backup，保持迁移原子性。
            backup_path.unlink()
            with self.assertRaisesRegex(self.manager.ManagerError, "injected permission failure"):
                migrate_with_injected_failure()
            self.assertEqual(json.loads(config_path.read_text(encoding="utf-8"))["schema_version"], 1)
            self.assertFalse(backup_path.exists())

            # 注入解除后迁移可正常完成，backup 记录 v1 内容。
            completed = self.run_json(environment, "upgrade")
            self.assertIn("config_migration", completed["changed"])
            self.assertEqual(json.loads(backup_path.read_text(encoding="utf-8"))["schema_version"], 1)
            self.assertEqual(json.loads(config_path.read_text(encoding="utf-8"))["schema_version"], 2)

    def test_uninstall_preserves_data_unless_purge_is_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            document = root / "data" / "ai-docs-web" / "data" / "private" / "library" / "public" / "saved.md"
            document.write_text("saved", encoding="utf-8")
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text("#!/bin/sh\ncase \"$*\" in *is-enabled*) echo disabled; exit 1;; *is-active*) echo inactive; exit 3;; *) exit 0;; esac\n", encoding="utf-8")
            fake_systemctl.chmod(0o755)
            environment["PATH"] = str(fake_bin) + os.pathsep + environment.get("PATH", "")
            self.run_json(environment, "uninstall")
            self.assertTrue(document.is_file())
            self.assertTrue((root / "config" / "ai-docs-web" / "server.json").is_file())

    def test_uninstall_refuses_runtime_or_unit_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            runtime_file = root / "data" / "ai-docs-web" / "runtime" / "source" / "ai_docs_web.py"
            runtime_file.write_text(runtime_file.read_text(encoding="utf-8") + "\n# local drift\n", encoding="utf-8")
            completed = self.run_raw(environment, "uninstall")
            self.assertEqual(completed.returncode, 1)
            self.assertIn("runtime has drifted", completed.stderr)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            unit = root / "config" / "systemd" / "user" / "ai-docs-web.service"
            unit.write_text(unit.read_text(encoding="utf-8") + "\n# local drift\n", encoding="utf-8")
            completed = self.run_raw(environment, "uninstall")
            self.assertEqual(completed.returncode, 1)
            self.assertIn("unit has drifted", completed.stderr)

    def test_purge_removes_manager_owned_opencode_backups(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            opencode = root / "config" / "opencode" / "opencode.json"
            opencode.parent.mkdir(parents=True)
            opencode.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
            self.run_json(environment, "register", "--host", "opencode")
            backup_root = root / "state" / "ai-docs-web" / "backups"
            self.assertTrue(backup_root.is_dir())
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text("#!/bin/sh\ncase \"$*\" in *is-enabled*) echo disabled; exit 1;; *is-active*) echo inactive; exit 3;; *) exit 0;; esac\n", encoding="utf-8")
            fake_systemctl.chmod(0o755)
            environment["PATH"] = str(fake_bin) + os.pathsep + environment.get("PATH", "")
            self.run_json(environment, "uninstall", "--purge")
            self.assertFalse(backup_root.exists())

    def test_failed_uninstall_restores_original_systemd_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            self.run_json(environment, "install")
            runtime = root / "data" / "ai-docs-web" / "runtime"
            unit = root / "config" / "systemd" / "user" / "ai-docs-web.service"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            log = root / "systemctl.log"
            marker = root / "daemon-reload-failed"
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$*\" >> \"$AI_DOCS_TEST_SYSTEMCTL_LOG\"\n"
                "case \"$*\" in\n"
                "  *is-enabled*|*is-active*) exit 0;;\n"
                "  *daemon-reload*)\n"
                "    if [ ! -e \"$AI_DOCS_TEST_SYSTEMCTL_MARKER\" ]; then\n"
                "      : > \"$AI_DOCS_TEST_SYSTEMCTL_MARKER\"\n"
                "      exit 2\n"
                "    fi;;\n"
                "esac\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)
            environment["PATH"] = str(fake_bin) + os.pathsep + environment.get("PATH", "")
            environment["AI_DOCS_TEST_SYSTEMCTL_LOG"] = str(log)
            environment["AI_DOCS_TEST_SYSTEMCTL_MARKER"] = str(marker)
            completed = self.run_raw(environment, "uninstall")
            self.assertEqual(completed.returncode, 1)
            self.assertTrue(runtime.is_dir())
            self.assertTrue(unit.is_file())
            calls = log.read_text(encoding="utf-8")
            self.assertIn("disable --now ai-docs-web.service", calls)
            self.assertIn("enable ai-docs-web.service", calls)
            self.assertIn("start ai-docs-web.service", calls)


if __name__ == "__main__":
    unittest.main()
