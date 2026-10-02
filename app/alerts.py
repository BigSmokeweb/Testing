import requests

from app.config import load_config


def send_alert(run_id: int, engine: str, failed_flows: list, report_base_url: str = "http://127.0.0.1:8000") -> None:
    """Send Slack webhook alert if run has failed flows.

    Does nothing if alert.type is 'none' or slack_webhook is empty.
    """
    config = load_config()
    alert_cfg = config.alert

    if alert_cfg.get("type", "none") != "slack":
        return

    webhook_url = alert_cfg.get("slack_webhook", "").strip()
    if not webhook_url:
        return

    if not failed_flows:
        return

    # Build summary message
    lines = [f"*AutoQA Alert* — Run #{run_id} on `{engine}` has {len(failed_flows)} failure(s):"]
    for name in failed_flows:
        lines.append(f"  • {name}")
    lines.append(f"Report: {report_base_url}/report/{run_id}")

    payload = {"text": "\n".join(lines)}

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        if resp.status_code != 200:
            print(f"[Alert] Slack webhook returned {resp.status_code}: {resp.text}")
        else:
            print(f"[Alert] Slack notification sent for run #{run_id}.")
    except Exception as e:
        print(f"[Alert] Failed to send Slack notification: {e}")
