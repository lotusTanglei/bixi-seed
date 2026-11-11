"""Real local HTTP proof. Reads disposable credentials from a private file.

Run from repository root with --credentials PATH. Never prints credentials,
cookies, prompts or response bodies. No model provider or HTTP call is mocked.
"""
import argparse
from collections import Counter
from http.cookiejar import CookieJar
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:8000"
events = []


class Browser:
    def __init__(self, name):
        self.name = name
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))

    def request(self, label, method, path, payload=None, expected=200):
        headers = {"Referer": BASE + "/"}
        if method not in {"GET", "HEAD"}:
            headers["Content-Type"] = "application/json"
            for cookie in self.cookies:
                if cookie.name == "csrftoken":
                    headers["X-CSRFToken"] = cookie.value
        body = json.dumps(payload).encode() if payload is not None else None
        request = Request(BASE + path, data=body, headers=headers, method=method)
        try:
            response = self.opener.open(request, timeout=15)
        except HTTPError as error:
            response = error
        raw = response.read()
        status = response.code
        events.append({"check": label, "actor": self.name, "method": method,
                       "path": path, "expected": expected, "actual": status,
                       "passed": status == expected})
        assert status == expected, f"{label}: expected HTTP {expected}, got {status}"
        if response.headers.get("Content-Type", "").startswith("application/json"):
            return json.loads(raw)
        return raw

    def login(self, credentials):
        self.request("csrf", "GET", "/api/auth/csrf/")
        payload = self.request("login", "POST", "/api/auth/login/", {
            "username": credentials["username"], "password": credentials["password"],
        })
        assert payload["user"]["id"] == credentials["user_id"]
        assert payload["active_organization"] == credentials["organization_id"]


def command(name, arguments):
    result = subprocess.run(arguments, cwd=ROOT, capture_output=True, text=True)
    (EVIDENCE / name).write_text("COMMAND: " + " ".join(arguments) + "\nEXIT_CODE: " + str(result.returncode)
                               + "\n" + result.stdout + result.stderr)
    return result.returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials", required=True)
    args = parser.parse_args()
    credentials = json.loads(Path(args.credentials).read_text())
    owner, foreign = Browser("fixture-owner"), Browser("fixture-foreign-owner")
    summary = {"transport": "real loopback HTTP", "model_mocked": False, "passed": False}
    try:
        assert command("start-command.txt", ["./start.sh"]) == 0
        time.sleep(0.5)
        assert command("running-status.txt", ["./status.sh"]) == 0
        health = owner.request("health", "GET", "/api/health/")
        assert health["status"] == "ok" and health["service"] == "bixi-seed-core"
        index = owner.request("frontend-index", "GET", "/").decode()
        assets = re.findall(r'(?:src|href)="(/static/[^\"]+)"', index)
        assert len(assets) >= 2
        for asset in assets:
            assert owner.request("frontend-static-asset", "GET", asset)
        owner.login(credentials["owner"])
        foreign.login(credentials["foreign"])
        owner.request("authenticated-me", "GET", "/api/auth/me/")

        # E7 review/confirmation is a catalog operation. Draft text is never run.
        assert owner.request("extension-catalog-empty", "GET", "/api/extensions/drafts/") == []
        draft = owner.request("extension-create", "POST", "/api/extensions/drafts/", {
            "key": "runtime-catalog-proof", "name": "本机目录验收",
            "files": {"extension.py": "raise RuntimeError('must never execute')\n"},
            "dependencies": ["packaging>=24,<27"], "permission_manifest": ["feature.read"],
        }, expected=201)
        draft_path = f'/api/extensions/drafts/{draft["id"]}'
        assert draft["status"] == "validated"
        draft = owner.request("extension-validate", "POST", draft_path + "/validate/", {})
        assert draft["static_checks"]["passed"] and len(draft["validated_hash"]) == 64
        owner.request("extension-confirmation-required", "POST", draft_path + "/enable/", {
            "content_hash": draft["validated_hash"],
        }, expected=409)
        owner.request("extension-stale-hash-denied", "POST", draft_path + "/enable/", {
            "confirmed": True, "content_hash": "stale",
        }, expected=409)
        assert foreign.request("foreign-catalog-is-empty", "GET", "/api/extensions/drafts/") == []
        foreign.request("foreign-extension-validate-denied", "POST", draft_path + "/validate/", {}, expected=404)
        foreign.request("foreign-extension-enable-denied", "POST", draft_path + "/enable/", {
            "confirmed": True, "content_hash": draft["validated_hash"],
        }, expected=404)
        enabled = owner.request("extension-confirm-enable", "POST", draft_path + "/enable/", {
            "confirmed": True, "content_hash": draft["validated_hash"],
        })
        assert enabled["status"] == "enabled" and enabled["enabled_hash"] == draft["validated_hash"]
        assert enabled["execution_status"] == "not_loaded_or_executed"
        owner.request("extension-repeat-enable-denied", "POST", draft_path + "/enable/", {
            "confirmed": True, "content_hash": draft["validated_hash"],
        }, expected=409)
        assert owner.request("extension-catalog-enabled", "GET", "/api/extensions/drafts/")[0]["status"] == "enabled"

        # E6 fixed record operations use the same real Session/CSRF HTTP flow.
        feature = owner.request("feature-create", "POST", "/api/features/", {
            "key": "runtime-record-proof", "name": "本机记录验收",
            "manifest": {"version": 1, "fields": [
                {"key": "name", "label": "名称", "type": "text", "required": True},
                {"key": "amount", "label": "数量", "type": "number"},
            ]},
        }, expected=201)
        feature_path = f'/api/features/{feature["id"]}'
        owner.request("feature-publish", "POST", feature_path + "/publish/", {})
        tools = owner.request("tool-catalog", "GET", "/api/ai/tools/")
        assert {tool["name"] for tool in tools} == {"feature.record.create", "feature.record.update", "feature.record.delete"}

        def propose(action, record_id=None, data=None):
            arguments = {"feature_id": feature["id"]}
            if record_id is not None:
                arguments["record_id"] = int(record_id)
            if action != "delete":
                arguments["data"] = data
            result = owner.request("tool-propose-" + action, "POST", "/api/ai/tool-proposals/", {
                "tool": "feature.record." + action, "arguments": arguments,
            }, expected=201)
            assert result["status"] == "proposed" and all(key in result["diff"] for key in ("fields", "permissions", "data"))
            return f'/api/ai/tool-proposals/{result["id"]}'

        proposal_path = propose("create", data={"name": "Runtime proof", "amount": 1})
        assert owner.request("no-execution-before-confirm", "GET", feature_path + "/records/")["pagination"]["total"] == 0
        owner.request("tool-confirmation-required", "POST", proposal_path + "/confirm/", {}, expected=400)
        foreign.request("foreign-tool-detail-denied", "GET", proposal_path + "/", expected=404)
        foreign.request("foreign-tool-confirm-denied", "POST", proposal_path + "/confirm/", {"confirm": True}, expected=404)
        foreign.request("foreign-tool-revoke-denied", "POST", proposal_path + "/revoke/", {"confirm": True}, expected=404)
        result = owner.request("tool-confirm-create", "POST", proposal_path + "/confirm/", {"confirm": True})
        assert result["status"] == "confirmed" and "undo" not in result["result"]
        owner.request("tool-repeat-confirm-denied", "POST", proposal_path + "/confirm/", {"confirm": True}, expected=400)
        owner.request("tool-revoke-create", "POST", proposal_path + "/revoke/", {"confirm": True})
        assert owner.request("tool-create-compensated", "GET", feature_path + "/records/")["pagination"]["total"] == 0
        record = owner.request("fixture-record-create", "POST", feature_path + "/records/", {
            "data": {"name": "Runtime proof", "amount": 1},
        }, expected=201)
        record_path = feature_path + f'/records/{record["id"]}/'
        update_path = propose("update", record_id=record["id"], data={"amount": 2})
        owner.request("tool-confirm-update", "POST", update_path + "/confirm/", {"confirm": True})
        assert owner.request("tool-updated-data", "GET", record_path)["data"]["amount"] == 2
        owner.request("tool-revoke-update", "POST", update_path + "/revoke/", {"confirm": True})
        assert owner.request("tool-update-compensated", "GET", record_path)["data"]["amount"] == 1
        delete_path = propose("delete", record_id=record["id"])
        owner.request("tool-confirm-delete", "POST", delete_path + "/confirm/", {"confirm": True})
        owner.request("tool-deleted-data", "GET", record_path, expected=404)
        owner.request("tool-revoke-delete", "POST", delete_path + "/revoke/", {"confirm": True})
        assert owner.request("tool-delete-compensated", "GET", record_path)["data"]["amount"] == 1
        stale_path = propose("update", record_id=record["id"], data={"amount": 2})
        owner.request("tool-confirm-before-concurrent-change", "POST", stale_path + "/confirm/", {"confirm": True})
        owner.request("later-record-write", "PATCH", record_path, {"data": {"amount": 3}})
        owner.request("tool-cannot-overwrite-later-write", "POST", stale_path + "/revoke/", {"confirm": True}, expected=409)
        assert owner.request("later-record-write-preserved", "GET", record_path)["data"]["amount"] == 3
        owner.request("real-model-not-configured", "POST", "/api/ai/tool-plan/", {
            "feature_id": feature["id"], "requirement": "创建一条名称为本机验收的记录",
        }, expected=422)
        audit = owner.request("organization-audit", "GET", "/api/organizations/audit-logs/?page_size=100")
        action_counts = Counter(item["action"] for item in audit["items"])
        expected_actions = {"extension.draft.created", "extension.draft.validated", "extension.draft.enabled",
                            "extension.draft.enable_denied", "ai.tool.proposed", "ai.tool.confirmed",
                            "ai.tool.reverted", "ai.tool.revert_failed", "ai.tool.plan_failed", "feature.record.reverted"}
        assert expected_actions.issubset(action_counts)
        assert any(item["action"] == "ai.tool.plan_failed" and not item["success"] for item in audit["items"])
        summary.update({"passed": True, "http_check_count": len(events), "audit_action_counts": dict(action_counts),
                        "e7_status": "enabled_in_catalog_only_not_loaded_or_executed",
                        "e6_fixed_operations": ["create", "update", "delete"],
                        "real_model_status": "BLOCKED_no_organization_model_configuration_HTTP_422"})
    except Exception as error:
        summary.update({"error_type": type(error).__name__, "error": str(error)})
    finally:
        for browser in (owner, foreign):
            try:
                browser.request("fixture-logout", "POST", "/api/auth/logout/", {})
            except Exception:
                pass
        summary["running_status_exit"] = command("final-running-status.txt", ["./status.sh"])
        summary["stop_exit"] = command("stop-command.txt", ["./stop.sh"])
        summary["stopped_status_exit"] = command("stopped-status.txt", ["./status.sh"])
        summary["http_check_count"] = len(events)
        summary["events"] = events
        (EVIDENCE / "http-results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({key: value for key, value in summary.items() if key != "events"}, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] and summary["stop_exit"] == 0 and summary["stopped_status_exit"] == 1 else 1


if __name__ == "__main__":
    sys.exit(main())
