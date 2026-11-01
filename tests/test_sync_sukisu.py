"""Exercise SukiSU's artifact selection and publishing through the real script."""

import copy
import unittest

import test_sync_kowsu as kowsu


RUNS = "repos/SukiSU-Ultra/SukiSU-Ultra/actions/workflows/152806636/runs?branch=main&per_page=10"
RELEASE = "repos/example/CI/releases/tags/SukiSU_42"
ARTIFACTS = "repos/SukiSU-Ultra/SukiSU-Ultra/actions/runs/42/artifacts?per_page=100"
ZIP = "repos/SukiSU-Ultra/SukiSU-Ultra/actions/artifacts/99/zip"
APK = "SukiSU_v4.3.0_41120-release.apk"


def release_record(*, draft=False, assets=None):
    return {
        "tag_name": "SukiSU_42",
        "draft": draft,
        "assets": assets if assets is not None else [
            {"name": APK, "state": "uploaded", "size": len(kowsu.APK_CONTENT)}
        ],
    }


def publish_routes():
    return {
        RUNS: [{"json": {"workflow_runs": [kowsu.run_record()]}}],
        RELEASE: [copy.deepcopy(kowsu.NOT_FOUND), {"json": release_record()}],
        "graphql": [{"json": {"data": {"repository": {"release": None}}}}],
        ARTIFACTS: [{"json": {"artifacts": [
            {"id": 97, "name": "Manager-spoofed", "expired": False},
            {"id": 98, "name": "Manager-gradle", "expired": False},
            {"id": 99, "name": "Manager", "expired": False},
        ]}}],
        ZIP: [{"zip": {APK: kowsu.APK_CONTENT}}],
        "release create SukiSU_42": [{}],
    }


class SyncSukiSUTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        kowsu.SyncKowSUTest.setUpClass()

    def run_sync(self, routes):
        return kowsu.SyncKowSUTest.run_sync(
            self, routes, script=".github/scripts/sync-sukisu.sh",
            env_overrides={
                "TARGET_REPO": "SukiSU-Ultra/SukiSU-Ultra",
                "TARGET_BRANCH": "main",
                "TARGET_WORKFLOW_ID": "152806636",
            },
        )

    def test_full_manager_is_published_with_separate_tag_and_verified(self):
        result, calls, summary = self.run_sync(publish_routes())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        create = next(call for call in calls if call[:2] == ["release", "create"])
        self.assertEqual(create[2], "SukiSU_42")
        self.assertEqual(create[create.index("--repo") + 1], "example/CI")
        self.assertEqual(create[create.index("--title") + 1], "SukiSU-Ultra v4.3.0_41120")
        self.assertIn("--latest=false", create)
        self.assertEqual(calls[-1], ["api", "--include", RELEASE])
        self.assertIn("SukiSU-Ultra sync: success", summary)
        self.assertIn("| 1 | 1 | 0 | 0 | 0 |", summary)

    def test_paginated_manager_and_nested_apk_are_supported(self):
        routes = publish_routes()
        routes[ARTIFACTS] = [{"pages": [
            {"artifacts": [{"id": 98, "name": "Manager-gradle", "expired": False}]},
            {"artifacts": [{"id": 99, "name": "Manager", "expired": False}]},
        ]}]
        routes[ZIP] = [{"zip": {"apk output/release/" + APK: kowsu.APK_CONTENT}}]
        result, _, summary = self.run_sync(routes)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("| 1 | 1 | 0 | 0 | 0 |", summary)

    def test_existing_sukisu_release_is_skipped(self):
        routes = {
            RUNS: [{"json": {"workflow_runs": [kowsu.run_record()]}}],
            RELEASE: [{"json": release_record()}],
        }
        result, calls, summary = self.run_sync(routes)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 2)
        self.assertIn("| 1 | 0 | 0 | 1 | 0 |", summary)

    def test_incomplete_sukisu_release_is_repaired(self):
        routes = publish_routes()
        routes[RELEASE][0] = {"json": release_record(assets=[])}
        del routes["release create SukiSU_42"]
        routes["release upload SukiSU_42"] = [{}]
        result, calls, summary = self.run_sync(routes)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        upload = next(call for call in calls if call[:2] == ["release", "upload"])
        self.assertIn("--clobber", upload)
        self.assertIn("| 1 | 0 | 1 | 0 | 0 |", summary)

    def test_alternative_artifacts_do_not_replace_missing_manager(self):
        routes = publish_routes()
        routes[ARTIFACTS][0]["json"]["artifacts"].pop()
        result, calls, summary = self.run_sync(routes)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("has no unexpired Manager artifact", result.stderr)
        self.assertFalse(any(call[0] == "release" for call in calls))
        self.assertIn("SukiSU-Ultra sync: failure", summary)

    def test_api_failure_cannot_report_success(self):
        result, calls, summary = self.run_sync({RUNS: [kowsu.API_ERROR]})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)
        self.assertIn("SukiSU-Ultra sync: failure", summary)

    def test_pr_and_unfinished_builds_are_ignored(self):
        routes = {RUNS: [{"json": {"workflow_runs": [
            kowsu.run_record(event="pull_request"),
            kowsu.run_record(event="pull_request_target"),
            kowsu.run_record(status="in_progress"),
        ]}}]}
        result, calls, summary = self.run_sync(routes)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 1)
        self.assertIn("| 0 | 0 | 0 | 0 | 0 |", summary)

    def test_wrong_or_spoofed_apk_names_are_not_published(self):
        for name in (kowsu.APK, "SukiSU_v4.3.0_41120-release-spoofed.apk"):
            with self.subTest(name=name):
                routes = publish_routes()
                routes[ZIP] = [{"zip": {name: kowsu.APK_CONTENT}}]
                result, calls, _ = self.run_sync(routes)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(call[0] == "release" for call in calls))


if __name__ == "__main__":
    unittest.main()
