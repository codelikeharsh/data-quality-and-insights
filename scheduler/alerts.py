"""
Slack alerting: posts a run summary to a webhook when the health score drops
below the configured threshold, or any high-severity issue is flagged.

If SLACK_WEBHOOK_URL isn't set, alerts are logged instead of sent — the
brief asks for this to be mockable when no real webhook is provided, so a
demo/interview run doesn't need real Slack credentials to show the alerting
logic working.
"""
import logging

import requests

from config import ALERT_HEALTH_SCORE_THRESHOLD, SLACK_WEBHOOK_URL

logger = logging.getLogger("scheduler.alerts")


def should_alert(result: dict) -> bool:
    """A run needs an alert if its health score is below threshold, or it
    flagged at least one high-severity issue — either condition alone is
    reason enough to page someone."""
    score = result["health_score"]["score"]
    if score < ALERT_HEALTH_SCORE_THRESHOLD:
        return True
    return any(issue["severity"] == "high" for issue in result["issues"])


def build_alert_message(result: dict) -> str:
    score = result["health_score"]["score"]
    high_severity = [i for i in result["issues"] if i["severity"] == "high"]

    lines = [
        f":rotating_light: *Data Quality Alert* — run `{result['run_id']}`",
        f"*Source:* {result['source_file']}",
        f"*Health score:* {score}/100 (alert threshold: {ALERT_HEALTH_SCORE_THRESHOLD})",
        f"*Rows processed:* {result['rows_processed']} · *Rows flagged:* {result['rows_flagged']}",
    ]

    if high_severity:
        lines.append(f"\n*{len(high_severity)} high-severity issue(s):*")
        for issue in high_severity[:10]:
            lines.append(f"  • [{issue['issue_type']}] {issue['description']}")
        if len(high_severity) > 10:
            lines.append(f"  … and {len(high_severity) - 10} more")

    return "\n".join(lines)


def send_slack_alert(result: dict) -> bool:
    """Send (or, with no webhook configured, log) an alert for one pipeline
    run. Returns True if an alert was actually dispatched/logged, False if
    the run didn't meet the alert conditions."""
    if not should_alert(result):
        return False

    message = build_alert_message(result)

    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL not configured — alert logged instead of sent:\n%s", message)
        return True

    try:
        response = requests.post(SLACK_WEBHOOK_URL, json={"text": message}, timeout=10)
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("Failed to post Slack alert for run %s", result["run_id"])
        return False

    return True
