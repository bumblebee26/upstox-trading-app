"""AWS Lambda that starts a GitHub workflow at the scheduled time (EventBridge Scheduler calls it).

GitHub's own cron can run hours late, so time-critical runs start here; the workflows' cron stays as a backup.
Event: {"workflow": "trading-session.yml", "inputs": {"phase": "morning"}}
"""
import json
import logging

from core import http, ssm

log = logging.getLogger("upx")
log.setLevel(logging.INFO)

REPO = "bumblebee26/upstox-trading-app"
TOKEN_PARAM = "/upx/github-dispatch-token"
WORKFLOWS = {"trading-session.yml", "pools.yml", "shadows.yml"}


def handler(event, context):
    workflow, inputs = event.get("workflow"), event.get("inputs") or {}
    if workflow not in WORKFLOWS:
        raise ValueError(f"unknown workflow {workflow!r}")
    url = f"https://api.github.com/repos/{REPO}/actions/workflows/{workflow}/dispatches"
    http.request("POST", url, data=json.dumps({"ref": "main", "inputs": inputs}).encode(), log_url=url,
                 headers={"Authorization": f"Bearer {ssm.get(TOKEN_PARAM)}", "Accept": "application/vnd.github+json",
                          "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
    log.info("dispatched %s %s", workflow, inputs)
    return {"dispatched": workflow, "inputs": inputs}
