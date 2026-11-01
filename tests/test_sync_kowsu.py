"""Run the real sync script against an offline, fault-injected GitHub CLI."""

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNS = "repos/upstream/KernelSU/actions/workflows/123/runs?branch=master&per_page=10"
RELEASE = "repos/example/CI/releases/tags/KowSU_42"
ARTIFACTS = "repos/upstream/KernelSU/actions/runs/42/artifacts?per_page=100"
ZIP = "repos/upstream/KernelSU/actions/artifacts/99/zip"
APK = "KowSU_v3.3.0_32732-release.apk"
APK_CONTENT = "test-apk-content"
NOT_FOUND = {"status": 404, "json": {"message": "Not Found"}}
API_ERROR = {"status": 403, "stderr": "gh: API rate limit exceeded (HTTP 403)"}


def run_record(run_id=42, **fields):
    return {
        "id": run_id,
        "html_url": f"https://example.test/runs/{run_id}",
        "head_sha": "abc123",
        "head_commit": {"message": "manager update\n\nDetails"},
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        **fields,
    }


def release_record(run_id=42, *, draft=False, assets=None):
    return {
        "tag_name": f"KowSU_{run_id}",
        "draft": draft,
        "assets": assets if assets is not None else [
            {"name": APK, "state": "uploaded", "size": len(APK_CONTENT)}
        ],
    }


def publish_routes():
    return {
        RUNS: [{"json": {"workflow_runs": [run_record()]}}],
        RELEASE: [copy.deepcopy(NOT_FOUND), {"json": release_record()}],
        "graphql": [{"json": {"data": {"repository": {"release": None}}}}],
        ARTIFACTS: [{"json": {"artifacts": [
            {"id": 99, "name": "manager", "expired": False}
        ]}}],
        ZIP: [{"zip": {APK: APK_CONTENT}}],
        "release create KowSU_42": [{}],
    }


class SyncKowSUTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for command in ("bash", "jq", "unzip"):
            if shutil.which(command) is None:
                raise RuntimeError(f"Tests require {command}")

    def run_sync(self, routes, *, script=".github/scripts/sync-kowsu.sh", env_overrides=None):
        with tempfile.TemporaryDirectory(prefix="kowsu-test-") as directory:
            root = Path(directory)
            (root / "bin").mkdir()
            (root / "scratch").mkdir()
            fake_gh = root / "bin/gh"
            shutil.copyfile(ROOT / "tests/fixtures/gh.py", fake_gh)
            fake_gh.chmod(0o755)
            state_file = root / "state.json"
            state_file.write_text(json.dumps({"routes": routes, "calls": []}))
            summary = root / "summary.md"
            env = {
                "PATH": str(root / "bin") + os.pathsep + os.defpath,
                "TMPDIR": str(root / "scratch"),
                "KOWSU_TEST_STATE": str(state_file),
                "GITHUB_STEP_SUMMARY": str(summary),
                "GITHUB_REPOSITORY": "example/CI",
                "TARGET_REPO": "upstream/KernelSU",
                "TARGET_BRANCH": "master",
                "TARGET_WORKFLOW_ID": "123",
                "N_LATEST_RUNS": "10",
            }
            env.update(env_overrides or {})
            result = subprocess.run(
                ["bash", str(ROOT / script)],
                cwd=root, env=env, text=True, capture_output=True, timeout=15,
            )
            state = json.loads(state_file.read_text())
            self.assertNotIn("Unexpected gh request", result.stderr, result.stderr)
            self.assertEqual(list((root / "scratch").iterdir()), [], "Temporary files leaked")
            return result, state["calls"], summary.read_text()

    def assert_failed(self, routes, message=None, *, before_publish=True):
        result, calls, summary = self.run_sync(routes)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("KowSU sync: failure", summary)
        if message:
            self.assertIn(message, result.stdout + result.stderr)
        if before_publish:
            self.assertFalse(any(call[0] == "release" for call in calls))

    def test_existing_apks_are_skipped_and_counted(self):
        routes = {
            RUNS: [{"json": {"workflow_runs": [run_record(43), run_record()]}}],
            RELEASE: [{"json": release_record()}],
            RELEASE.replace("_42", "_43"): [{"json": release_record(43)}],
        }
        result, calls, summary = self.run_sync(routes)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 3)
        self.assertIn("| 2 | 0 | 0 | 2 | 0 |", summary)

    def test_new_apk_is_published_and_verified(self):
        result, calls, summary = self.run_sync(publish_routes())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        create = next(call for call in calls if call[:2] == ["release", "create"])
        self.assertEqual(create[create.index("--repo") + 1], "example/CI")
        self.assertIn("--latest=false", create)
        self.assertIn("--notes-file", create)
        self.assertIn("| 1 | 1 | 0 | 0 | 0 |", summary)
        self.assertEqual(calls[-1], ["api", "--include", RELEASE])

    def test_nested_apk_and_paginated_manager_are_supported(self):
        routes = publish_routes()
        routes[ARTIFACTS] = [{"pages": [
            {"artifacts": [{"id": 98, "name": "manager-gradle", "expired": False}]},
            {"artifacts": [{"id": 99, "name": "manager", "expired": False}]},
        ]}]
        routes[ZIP] = [{"zip": {"apk output/release/" + APK: APK_CONTENT}}]
        result, _, summary = self.run_sync(routes)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("| 1 | 1 | 0 | 0 | 0 |", summary)

    def test_runs_api_failure_is_not_reported_as_no_updates(self):
        self.assert_failed({RUNS: [API_ERROR]}, "API rate limit")

    def test_invalid_runs_response_fails(self):
        self.assert_failed({RUNS: [{"stdout": "invalid JSON"}]})

    def test_release_permission_error_is_not_treated_as_missing(self):
        routes = publish_routes()
        routes[RELEASE] = [API_ERROR]
        self.assert_failed(routes, "Cannot check release")

    def test_artifact_api_failure_is_fatal(self):
        routes = publish_routes()
        routes[ARTIFACTS] = [API_ERROR]
        self.assert_failed(routes, "API rate limit")

    def test_draft_lookup_error_does_not_create_another_release(self):
        routes = publish_routes()
        routes["graphql"] = [API_ERROR]
        self.assert_failed(routes, "API rate limit")

    def test_successful_run_without_manager_fails(self):
        routes = publish_routes()
        routes[ARTIFACTS] = [{"json": {"artifacts": [
            {"id": 98, "name": "manager-gradle", "expired": False}
        ]}}]
        self.assert_failed(routes, "has no unexpired manager artifact")

    def test_expired_manager_is_not_downloaded(self):
        routes = publish_routes()
        routes[ARTIFACTS][0]["json"]["artifacts"][0]["expired"] = True
        self.assert_failed(routes, "has no unexpired manager artifact")

    def test_failed_upstream_without_manager_is_explicitly_skipped(self):
        routes = publish_routes()
        routes[RUNS] = [{"json": {"workflow_runs": [run_record(conclusion="failure")]}}]
        routes[ARTIFACTS] = [{"json": {"artifacts": []}}]
        result, calls, summary = self.run_sync(routes)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("::warning::", result.stdout)
        self.assertFalse(any(call[0] == "release" for call in calls))
        self.assertIn("| 1 | 0 | 0 | 0 | 1 |", summary)

    def test_manager_can_be_synced_when_an_unrelated_upstream_job_fails(self):
        routes = publish_routes()
        routes[RUNS] = [{"json": {"workflow_runs": [run_record(conclusion="failure")]}}]
        result, _, _ = self.run_sync(routes)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pr_and_unfinished_runs_are_ignored(self):
        routes = {RUNS: [{"json": {"workflow_runs": [
            run_record(event="pull_request"),
            run_record(event="pull_request_target"),
            run_record(status="in_progress"),
        ]}}]}
        result, calls, summary = self.run_sync(routes)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 1)
        self.assertIn("| 0 | 0 | 0 | 0 | 0 |", summary)

    def test_empty_or_renamed_apk_fails(self):
        for entries in ({APK: ""}, {"OtherManager-release.apk": APK_CONTENT}):
            with self.subTest(entries=entries):
                routes = publish_routes()
                routes[ZIP] = [{"zip": entries}]
                self.assert_failed(routes, "Expected one non-empty KowSU release APK")

    def test_ambiguous_apks_fail_instead_of_picking_arbitrarily(self):
        routes = publish_routes()
        routes[ZIP][0]["zip"][APK.replace("32732", "32733")] = APK_CONTENT
        self.assert_failed(routes, "found 2")

    def test_download_failure_is_fatal(self):
        routes = publish_routes()
        routes[ZIP] = [API_ERROR]
        self.assert_failed(routes, "API rate limit")

    def test_invalid_zip_is_fatal(self):
        routes = publish_routes()
        routes[ZIP] = [{"stdout": "not a zip archive"}]
        self.assert_failed(routes)

    def test_incomplete_release_is_repaired(self):
        routes = publish_routes()
        routes[RELEASE][0] = {"json": release_record(assets=[])}
        del routes["release create KowSU_42"]
        routes["release upload KowSU_42"] = [{}]
        result, calls, summary = self.run_sync(routes)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        upload = next(call for call in calls if call[:2] == ["release", "upload"])
        self.assertIn("--clobber", upload)
        self.assertIn("| 1 | 0 | 1 | 0 | 0 |", summary)

    def test_draft_release_is_finished(self):
        routes = publish_routes()
        routes["graphql"] = [{"json": {"data": {"repository": {"release": {"databaseId": 777}}}}}]
        routes["repos/example/CI/releases/777"] = [{"json": release_record(draft=True)}]
        del routes["release create KowSU_42"]
        routes["release upload KowSU_42"] = [{}]
        routes["release edit KowSU_42"] = [{}]
        result, calls, summary = self.run_sync(routes)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        edit = next(call for call in calls if call[:2] == ["release", "edit"])
        self.assertIn("--draft=false", edit)
        self.assertIn("--latest=false", edit)
        self.assertIn("| 1 | 0 | 1 | 0 | 0 |", summary)

    def test_release_upload_failure_is_fatal(self):
        routes = publish_routes()
        routes["release create KowSU_42"] = [{"exit": 1, "stderr": "upload failed"}]
        self.assert_failed(routes, "upload failed", before_publish=False)

    def test_uploaded_asset_is_verified_after_publish(self):
        for assets in (
            [],
            [{"name": APK, "state": "uploaded", "size": 1}],
            [{"name": APK, "state": "new", "size": len(APK_CONTENT)}],
        ):
            with self.subTest(assets=assets):
                routes = publish_routes()
                routes[RELEASE][1] = {"json": release_record(assets=assets)}
                self.assert_failed(routes, "missing the uploaded APK", before_publish=False)


if __name__ == "__main__":
    unittest.main()
