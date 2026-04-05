"""Built-in script templates for quick-start task creation."""

from typing import TypedDict


class ScriptTemplate(TypedDict):
    id: str
    name: str
    description: str
    category: str
    icon: str
    code: str
    dependencies: str
    cron_expression: str
    python_version: str
    environment_vars: str
    timeout: int


_TEMPLATES: list[ScriptTemplate] = [
    # ------------------------------------------------------------------
    # Monitoring
    # ------------------------------------------------------------------
    {
        "id": "api-health-check",
        "name": "api-health-check",
        "description": "Ping one or more HTTP endpoints and alert when any return an error or time out.",
        "category": "monitoring",
        "icon": "check_circle",
        "cron_expression": "*/5 * * * *",
        "python_version": "3.12",
        "timeout": 60,
        "dependencies": "",
        "environment_vars": "ENDPOINTS=https://example.com/health\nREQUEST_TIMEOUT=10",
        "code": (
            "import os\n"
            "import urllib.request\n"
            "from cronator_lib import get_logger, notify, timer\n"
            "\n"
            "logger = get_logger()\n"
            "\n"
            "# Comma-separated list of URLs to check\n"
            'ENDPOINTS = [u.strip() for u in os.environ.get("ENDPOINTS", "https://httpbin.org/status/200").split(",")]\n'
            'TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "10"))\n'
            "\n"
            "\n"
            "def check(url: str) -> dict:\n"
            "    try:\n"
            '        req = urllib.request.Request(url, method="GET")\n'
            '        req.add_header("User-Agent", "Cronator-HealthCheck/1.0")\n'
            "        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:\n"
            '            return {"url": url, "status": resp.status, "ok": resp.status < 400}\n'
            "    except Exception as exc:\n"
            '        return {"url": url, "status": None, "ok": False, "error": str(exc)}\n'
            "\n"
            "\n"
            "def main():\n"
            "    failures = []\n"
            "\n"
            "    for url in ENDPOINTS:\n"
            "        with timer(url):\n"
            "            result = check(url)\n"
            "\n"
            '        if result["ok"]:\n'
            "            logger.info(f\"OK  {result['url']} -> {result['status']}\")\n"
            "        else:\n"
            "            err = result.get(\"error\", f\"HTTP {result['status']}\")\n"
            "            logger.error(f\"FAIL {result['url']} -> {err}\")\n"
            '            failures.append(result["url"])\n'
            "\n"
            "    if failures:\n"
            "        notify(f\"{len(failures)} endpoint(s) down: {', '.join(failures)}\")\n"
            "        raise RuntimeError(f\"Health check failed: {', '.join(failures)}\")\n"
            "\n"
            '    logger.info(f"All {len(ENDPOINTS)} endpoint(s) healthy")\n'
            "\n"
            "\n"
            'if __name__ == "__main__":\n'
            "    main()\n"
        ),
    },
    {
        "id": "disk-monitor",
        "name": "disk-monitor",
        "description": "Check disk usage on one or more mount points and alert when thresholds are exceeded.",
        "category": "monitoring",
        "icon": "exclamation_triangle",
        "cron_expression": "*/30 * * * *",
        "python_version": "3.12",
        "timeout": 60,
        "dependencies": "",
        "environment_vars": "MONITOR_PATHS=/\nWARN_PERCENT=80\nCRITICAL_PERCENT=90",
        "code": (
            "import os\n"
            "import shutil\n"
            "from cronator_lib import get_logger, notify\n"
            "\n"
            "logger = get_logger()\n"
            "\n"
            'PATHS = [p.strip() for p in os.environ.get("MONITOR_PATHS", "/").split(",")]\n'
            'WARN_THRESHOLD = int(os.environ.get("WARN_PERCENT", "80"))\n'
            'CRITICAL_THRESHOLD = int(os.environ.get("CRITICAL_PERCENT", "90"))\n'
            "\n"
            "\n"
            "def check(path: str) -> dict:\n"
            "    try:\n"
            "        total, used, free = shutil.disk_usage(path)\n"
            "        pct = used / total * 100\n"
            "        return {\n"
            '            "path": path,\n'
            "            \"total_gb\": total / 1e9,\n"
            "            \"used_gb\": used / 1e9,\n"
            "            \"free_gb\": free / 1e9,\n"
            '            "pct": pct,\n'
            "        }\n"
            "    except Exception as exc:\n"
            '        return {"path": path, "error": str(exc)}\n'
            "\n"
            "\n"
            "def main():\n"
            "    critical, warn = [], []\n"
            "\n"
            "    for path in PATHS:\n"
            "        info = check(path)\n"
            "\n"
            '        if "error" in info:\n'
            "            logger.error(f\"{info['path']}: {info['error']}\")\n"
            "            continue\n"
            "\n"
            "        msg = f\"{info['path']}: {info['pct']:.1f}% used ({info['free_gb']:.1f} GB free)\"\n"
            "\n"
            '        if info["pct"] >= CRITICAL_THRESHOLD:\n'
            '            logger.error(f"CRITICAL -- {msg}")\n'
            '            critical.append(info["path"])\n'
            '        elif info["pct"] >= WARN_THRESHOLD:\n'
            '            logger.warning(f"WARNING -- {msg}")\n'
            '            warn.append(info["path"])\n'
            "        else:\n"
            '            logger.info(f"OK -- {msg}")\n'
            "\n"
            "    if critical:\n"
            "        notify(f\"CRITICAL: disk full on {', '.join(critical)}\")\n"
            "        raise RuntimeError(f\"Disk usage critical: {', '.join(critical)}\")\n"
            "    elif warn:\n"
            "        notify(f\"Disk {WARN_THRESHOLD}%+ on {', '.join(warn)}\")\n"
            "\n"
            "\n"
            'if __name__ == "__main__":\n'
            "    main()\n"
        ),
    },
    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    {
        "id": "pg-backup",
        "name": "pg-backup",
        "description": "Dump a PostgreSQL database with pg_dump, compress it, and save as an artifact.",
        "category": "data",
        "icon": "archive_box",
        "cron_expression": "0 2 * * *",
        "python_version": "3.12",
        "timeout": 3600,
        "dependencies": "",
        "environment_vars": "DB_HOST=localhost\nDB_PORT=5432\nDB_NAME=mydb\nDB_USER=postgres\nPGPASSWORD=secret",
        "code": (
            "import gzip\n"
            "import os\n"
            "import subprocess\n"
            "from datetime import datetime\n"
            "from cronator_lib import get_logger, notify, save_artifact, timer\n"
            "\n"
            "logger = get_logger()\n"
            "\n"
            'DB_HOST = os.environ.get("DB_HOST", "localhost")\n'
            'DB_PORT = os.environ.get("DB_PORT", "5432")\n'
            'DB_NAME = os.environ.get("DB_NAME", "mydb")\n'
            'DB_USER = os.environ.get("DB_USER", "postgres")\n'
            "# Set PGPASSWORD in environment variables for passwordless auth\n"
            "\n"
            "\n"
            "def main():\n"
            '    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")\n'
            '    gz_file = f"/tmp/backup_{DB_NAME}_{timestamp}.sql.gz"\n'
            "\n"
            '    logger.info(f"Backing up {DB_NAME} on {DB_HOST}:{DB_PORT}")\n'
            "\n"
            '    with timer("pg_dump"):\n'
            "        result = subprocess.run(\n"
            '            ["pg_dump", "-h", DB_HOST, "-p", DB_PORT, "-U", DB_USER, "--no-password", DB_NAME],\n'
            "            capture_output=True,\n"
            "            # Pass only DB credentials; do not inherit the full process environment\n"
            "            env={k: v for k, v in os.environ.items() if k in (\n"
            '                "PGPASSWORD", "PGPASSFILE", "PATH", "HOME", "LANG",\n'
            '                "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER",\n'
            "            )},\n"
            "        )\n"
            "\n"
            "    if result.returncode != 0:\n"
            '        err = result.stderr.decode(errors="replace").strip()\n'
            '        logger.error(f"pg_dump failed (exit {result.returncode})")\n'
            "        logger.error(err)\n"
            '        raise RuntimeError(f"Backup failed (exit code {result.returncode})")\n'
            "\n"
            '    with timer("compress"):\n'
            '        with gzip.open(gz_file, "wb") as f:\n'
            "            f.write(result.stdout)\n"
            "\n"
            "    size_mb = os.path.getsize(gz_file) / 1024 / 1024\n"
            '    logger.info(f"Compressed size: {size_mb:.1f} MB")\n'
            "\n"
            '    save_artifact(gz_file, f"backup_{DB_NAME}_{timestamp}.sql.gz")\n'
            '    notify(f"Backup complete -- {size_mb:.1f} MB")\n'
            "\n"
            "\n"
            'if __name__ == "__main__":\n'
            "    main()\n"
        ),
    },
    {
        "id": "csv-export",
        "name": "csv-export",
        "description": "Fetch JSON data from an HTTP API and export it as a CSV artifact.",
        "category": "data",
        "icon": "clipboard",
        "cron_expression": "0 6 * * 1-5",
        "python_version": "3.12",
        "timeout": 300,
        "dependencies": "",
        "environment_vars": "API_URL=https://jsonplaceholder.typicode.com/posts\nAPI_TOKEN=\nOUTPUT_FILENAME=export.csv",
        "code": (
            "import csv\n"
            "import json\n"
            "import os\n"
            "import urllib.request\n"
            "from cronator_lib import get_logger, save_artifact, timer\n"
            "\n"
            "logger = get_logger()\n"
            "\n"
            'API_URL = os.environ.get("API_URL", "https://jsonplaceholder.typicode.com/posts")\n'
            'API_TOKEN = os.environ.get("API_TOKEN", "")\n'
            'OUTPUT_FILENAME = os.environ.get("OUTPUT_FILENAME", "export.csv")\n'
            "\n"
            "\n"
            "def fetch(url: str, token: str = \"\") -> list:\n"
            "    req = urllib.request.Request(url)\n"
            "    if token:\n"
            '        req.add_header("Authorization", f"Bearer {token}")\n'
            '    req.add_header("Accept", "application/json")\n'
            "    with urllib.request.urlopen(req, timeout=30) as resp:\n"
            "        data = json.loads(resp.read().decode())\n"
            "    if not isinstance(data, list):\n"
            '        raise ValueError(f"Expected JSON array, got {type(data).__name__}")\n'
            "    return data\n"
            "\n"
            "\n"
            "def main():\n"
            '    logger.info(f"Fetching data from {API_URL}")\n'
            "\n"
            '    with timer("fetch"):\n'
            "        data = fetch(API_URL, API_TOKEN)\n"
            "\n"
            "    if not data:\n"
            '        logger.warning("API returned no records")\n'
            "        return\n"
            "\n"
            '    logger.info(f"Fetched {len(data)} records")\n'
            "\n"
            '    tmp_path = f"/tmp/{OUTPUT_FILENAME}"\n'
            "    fieldnames = list(data[0].keys())\n"
            "\n"
            '    with timer("write csv"):\n'
            '        with open(tmp_path, "w", newline="", encoding="utf-8") as f:\n'
            "            writer = csv.DictWriter(f, fieldnames=fieldnames)\n"
            "            writer.writeheader()\n"
            "            writer.writerows(data)\n"
            "\n"
            "    save_artifact(tmp_path, OUTPUT_FILENAME)\n"
            '    logger.info(f"Exported {len(data)} rows -> {OUTPUT_FILENAME}")\n'
            "\n"
            "\n"
            'if __name__ == "__main__":\n'
            "    main()\n"
        ),
    },
    {
        "id": "http-data-sync",
        "name": "http-data-sync",
        "description": "Fetch records from a source API, optionally transform them, and push to a target webhook or API.",
        "category": "data",
        "icon": "arrow_path",
        "cron_expression": "0 * * * *",
        "python_version": "3.12",
        "timeout": 300,
        "dependencies": "",
        "environment_vars": "SOURCE_URL=https://jsonplaceholder.typicode.com/todos?_limit=10\nSOURCE_TOKEN=\nTARGET_URL=\nTARGET_TOKEN=",
        "code": (
            "import json\n"
            "import os\n"
            "import urllib.request\n"
            "from datetime import datetime\n"
            "from cronator_lib import get_logger, notify, timer\n"
            "\n"
            "logger = get_logger()\n"
            "\n"
            'SOURCE_URL = os.environ.get("SOURCE_URL", "https://jsonplaceholder.typicode.com/todos?_limit=5")\n'
            'SOURCE_TOKEN = os.environ.get("SOURCE_TOKEN", "")\n'
            'TARGET_URL = os.environ.get("TARGET_URL", "")\n'
            'TARGET_TOKEN = os.environ.get("TARGET_TOKEN", "")\n'
            "\n"
            "\n"
            "def fetch(url: str, token: str = \"\") -> list | dict:\n"
            "    req = urllib.request.Request(url)\n"
            "    if token:\n"
            '        req.add_header("Authorization", f"Bearer {token}")\n'
            '    req.add_header("Accept", "application/json")\n'
            "    with urllib.request.urlopen(req, timeout=30) as resp:\n"
            "        return json.loads(resp.read().decode())\n"
            "\n"
            "\n"
            "def push(url: str, data: list | dict, token: str = \"\") -> dict:\n"
            "    payload = json.dumps(data).encode()\n"
            '    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})\n'
            "    if token:\n"
            '        req.add_header("Authorization", f"Bearer {token}")\n'
            "    with urllib.request.urlopen(req, timeout=30) as resp:\n"
            "        return json.loads(resp.read().decode())\n"
            "\n"
            "\n"
            "def transform(data: list | dict) -> list | dict:\n"
            '    """Add your transformation logic here."""\n'
            "    if isinstance(data, list):\n"
            "        for item in data:\n"
            '            item["_synced_at"] = datetime.now().isoformat()\n'
            "    return data\n"
            "\n"
            "\n"
            "def main():\n"
            '    logger.info(f"Fetching from {SOURCE_URL}")\n'
            "\n"
            '    with timer("fetch"):\n'
            "        data = fetch(SOURCE_URL, SOURCE_TOKEN)\n"
            "\n"
            "    count = len(data) if isinstance(data, list) else 1\n"
            '    logger.info(f"Fetched {count} record(s)")\n'
            "\n"
            "    data = transform(data)\n"
            "\n"
            "    if not TARGET_URL:\n"
            '        logger.info("TARGET_URL not set -- dry run, showing sample")\n'
            "        sample = data[:2] if isinstance(data, list) else data\n"
            "        logger.info(json.dumps(sample, indent=2))\n"
            "        return\n"
            "\n"
            '    with timer("push"):\n'
            "        result = push(TARGET_URL, data, TARGET_TOKEN)\n"
            "\n"
            '    logger.info(f"Push response: {result}")\n'
            '    notify(f"Synced {count} record(s)")\n'
            "\n"
            "\n"
            'if __name__ == "__main__":\n'
            "    main()\n"
        ),
    },
    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------
    {
        "id": "file-cleanup",
        "name": "file-cleanup",
        "description": "Delete files older than N days from a directory. Supports dry-run mode.",
        "category": "maintenance",
        "icon": "trash",
        "cron_expression": "0 3 * * *",
        "python_version": "3.12",
        "timeout": 600,
        "dependencies": "",
        "environment_vars": "CLEANUP_DIR=/tmp/old_files\nMAX_AGE_DAYS=30\nFILE_PATTERN=*.log\nDRY_RUN=false",
        "code": (
            "import os\n"
            "import time\n"
            "from pathlib import Path\n"
            "from cronator_lib import get_logger, notify, timer\n"
            "\n"
            "logger = get_logger()\n"
            "\n"
            'DIRECTORY = os.environ.get("CLEANUP_DIR", "/tmp/old_files")\n'
            'MAX_AGE_DAYS = int(os.environ.get("MAX_AGE_DAYS", "30"))\n'
            'PATTERN = os.environ.get("FILE_PATTERN", "*.log")\n'
            'DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"\n'
            "\n"
            "\n"
            "def main():\n"
            "    directory = Path(DIRECTORY)\n"
            "    if not directory.exists():\n"
            '        logger.warning(f"Directory does not exist: {directory}")\n'
            "        return\n"
            "\n"
            "    cutoff = time.time() - MAX_AGE_DAYS * 86400\n"
            "    deleted, freed_bytes = 0, 0\n"
            "\n"
            '    with timer("scan"):\n'
            "        candidates = list(directory.rglob(PATTERN))\n"
            "\n"
            "    logger.info(f\"Found {len(candidates)} files matching '{PATTERN}'\")\n"
            "\n"
            "    for path in candidates:\n"
            "        if not path.is_file():\n"
            "            continue\n"
            "        stat = path.stat()\n"
            "        if stat.st_mtime < cutoff:\n"
            "            freed_bytes += stat.st_size\n"
            "            if DRY_RUN:\n"
            '                logger.info(f"[dry-run] would delete: {path}")\n'
            "            else:\n"
            "                path.unlink()\n"
            '                logger.info(f"Deleted: {path}")\n'
            "            deleted += 1\n"
            "\n"
            "    freed_mb = freed_bytes / 1024 / 1024\n"
            '    mode = "dry-run" if DRY_RUN else "deleted"\n'
            '    logger.info(f"Done: {mode} {deleted} file(s), freed {freed_mb:.1f} MB")\n'
            "\n"
            "    if deleted > 0:\n"
            '        notify(f"Cleaned {deleted} file(s) ({freed_mb:.1f} MB freed)")\n'
            "\n"
            "\n"
            'if __name__ == "__main__":\n'
            "    main()\n"
        ),
    },
    # ------------------------------------------------------------------
    # Notification
    # ------------------------------------------------------------------
    {
        "id": "telegram-notify",
        "name": "telegram-notify",
        "description": "Send a Telegram message via Bot API on a schedule or as a notification step.",
        "category": "notification",
        "icon": "envelope",
        "cron_expression": "0 9 * * 1-5",
        "python_version": "3.12",
        "timeout": 30,
        "dependencies": "",
        "environment_vars": "TELEGRAM_BOT_TOKEN=\nTELEGRAM_CHAT_ID=\nMESSAGE=Cronator: scheduled report at {time}",
        "code": (
            "import json\n"
            "import os\n"
            "import urllib.request\n"
            "from datetime import datetime\n"
            "from cronator_lib import get_logger, timer\n"
            "\n"
            "logger = get_logger()\n"
            "\n"
            'BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")\n'
            'CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")\n'
            'MESSAGE_TPL = os.environ.get("MESSAGE", "Cronator: scheduled report at {time}")\n'
            "\n"
            "\n"
            "def send(token: str, chat_id: str, text: str) -> dict:\n"
            '    url = f"https://api.telegram.org/bot{token}/sendMessage"\n'
            '    payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()\n'
            '    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})\n'
            "    with urllib.request.urlopen(req, timeout=15) as resp:\n"
            "        return json.loads(resp.read().decode())\n"
            "\n"
            "\n"
            "def main():\n"
            "    if not BOT_TOKEN or not CHAT_ID:\n"
            '        raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")\n'
            "\n"
            '    text = MESSAGE_TPL.format(time=datetime.now().strftime("%Y-%m-%d %H:%M"))\n'
            '    logger.info(f"Sending message to chat {CHAT_ID}")\n'
            "\n"
            '    with timer("send"):\n'
            "        result = send(BOT_TOKEN, CHAT_ID, text)\n"
            "\n"
            '    if result.get("ok"):\n'
            "        logger.info(f\"Sent (message_id={result['result']['message_id']})\")\n"
            "    else:\n"
            '        logger.error(f"API error: {result}")\n'
            "        raise RuntimeError(f\"Telegram error: {result.get('description', 'unknown')}\")\n"
            "\n"
            "\n"
            'if __name__ == "__main__":\n'
            "    main()\n"
        ),
    },
    # ------------------------------------------------------------------
    # Notification (continued)
    # ------------------------------------------------------------------
    {
        "id": "slack-notify",
        "name": "slack-notify",
        "description": "Post a message to a Slack (or Discord / Teams) channel via an incoming webhook URL.",
        "category": "notification",
        "icon": "bolt",
        "cron_expression": "0 9 * * 1-5",
        "python_version": "3.12",
        "timeout": 30,
        "dependencies": "",
        "environment_vars": (
            "SLACK_WEBHOOK_URL=https://hooks.slack.com/services/XXX/YYY/ZZZ\n"
            "MESSAGE=Cronator: scheduled report at {time}\n"
            "SLACK_USERNAME=Cronator\n"
            "SLACK_ICON_EMOJI=:robot_face:\n"
            "SLACK_CHANNEL="
        ),
        "code": '''\
import json
import os
import urllib.request
from datetime import datetime
from cronator_lib import get_logger, timer

logger = get_logger()

WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
MESSAGE_TPL = os.environ.get("MESSAGE", "Cronator: scheduled report at {time}")
USERNAME = os.environ.get("SLACK_USERNAME", "Cronator")
ICON_EMOJI = os.environ.get("SLACK_ICON_EMOJI", ":robot_face:")
CHANNEL = os.environ.get("SLACK_CHANNEL", "")  # leave empty to use the webhook default


def send_webhook(webhook_url: str, payload: dict) -> str:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode()


def main():
    if not WEBHOOK_URL:
        raise ValueError("SLACK_WEBHOOK_URL must be set in environment variables")

    text = MESSAGE_TPL.format(time=datetime.now().strftime("%Y-%m-%d %H:%M"))
    preview = text[:80] + ("..." if len(text) > 80 else "")
    logger.info(f"Sending Slack message: {preview}")

    payload: dict = {
        "text": text,
        "username": USERNAME,
        "icon_emoji": ICON_EMOJI,
    }
    if CHANNEL:
        payload["channel"] = CHANNEL

    with timer("send"):
        response = send_webhook(WEBHOOK_URL, payload)

    # Slack returns plain "ok" on success; Discord / Teams return JSON
    if response.strip() in ("ok", "") or response.strip().startswith("{"):
        logger.info(f"Sent (response: {response.strip()[:40]})")
    else:
        logger.error(f"Unexpected webhook response: {response}")
        raise RuntimeError(f"Webhook returned: {response}")


if __name__ == "__main__":
    main()
''',
    },
    {
        "id": "email-report",
        "name": "email-report",
        "description": "Send an HTML email report via SMTP. Customize build_report_html() with your own data.",
        "category": "notification",
        "icon": "envelope",
        "cron_expression": "0 8 * * 1",
        "python_version": "3.12",
        "timeout": 60,
        "dependencies": "",
        "environment_vars": (
            "SMTP_HOST=smtp.gmail.com\n"
            "SMTP_PORT=587\n"
            "SMTP_TLS=starttls\n"
            "SMTP_USER=you@gmail.com\n"
            "SMTP_PASSWORD=app-password-here\n"
            "SMTP_FROM=you@gmail.com\n"
            "SMTP_TO=recipient@example.com\n"
            "SUBJECT=Cronator Report - {date}"
        ),
        "code": '''\
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from cronator_lib import get_logger, timer

logger = get_logger()

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_TLS = os.environ.get("SMTP_TLS", "starttls")  # "starttls" | "ssl" | "none"
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "") or SMTP_USER
SMTP_TO = os.environ.get("SMTP_TO", "")
SUBJECT_TPL = os.environ.get("SUBJECT", "Cronator Report - {date}")


def build_report_html() -> str:
    """Build the HTML email body. Customize this with your own data and metrics."""
    now = datetime.now()

    # ---- Put your data rows here ----
    rows = [
        ("Status", '<span style="color:green;font-weight:bold">OK</span>'),
        ("Generated", now.strftime("%Y-%m-%d %H:%M:%S")),
        # ("New orders", "42"),
        # ("Revenue", "$1,234"),
    ]
    # ---------------------------------

    row_html = "".join(
        f"<tr>"
        f"<td style='padding:8px 14px;border:1px solid #e5e7eb'>{k}</td>"
        f"<td style='padding:8px 14px;border:1px solid #e5e7eb'>{v}</td>"
        f"</tr>"
        for k, v in rows
    )

    return (
        "<html><body style='font-family:sans-serif;color:#111827;margin:0;padding:24px'>"
        "<h2 style='color:#1d4ed8;margin-top:0'>Cronator Scheduled Report</h2>"
        "<table style='border-collapse:collapse;min-width:320px'>"
        "<tr style='background:#f3f4f6'>"
        "<th style='padding:8px 14px;border:1px solid #e5e7eb;text-align:left'>Metric</th>"
        "<th style='padding:8px 14px;border:1px solid #e5e7eb;text-align:left'>Value</th>"
        "</tr>"
        + row_html
        + "</table>"
        "<p style='color:#6b7280;font-size:12px;margin-top:28px'>Sent by Cronator</p>"
        "</body></html>"
    )


def send_email(subject: str, html_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = SMTP_TO
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if SMTP_TLS == "ssl":
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.sendmail(SMTP_FROM, SMTP_TO, msg.as_string())
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            if SMTP_TLS == "starttls":
                smtp.starttls()
            if SMTP_USER:
                smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.sendmail(SMTP_FROM, SMTP_TO, msg.as_string())


def main():
    if not SMTP_TO:
        raise ValueError("SMTP_TO must be set in environment variables")
    if not SMTP_USER:
        raise ValueError("SMTP_USER must be set in environment variables")

    now = datetime.now()
    subject = SUBJECT_TPL.format(
        date=now.strftime("%Y-%m-%d"),
        time=now.strftime("%H:%M"),
    )

    logger.info(f"Sending report to {SMTP_TO} via {SMTP_HOST}:{SMTP_PORT} ({SMTP_TLS})")

    html_body = build_report_html()

    with timer("send"):
        send_email(subject, html_body)

    logger.info(f"Sent: {subject}")


if __name__ == "__main__":
    main()
''',
    },
    # ------------------------------------------------------------------
    # Monitoring (continued)
    # ------------------------------------------------------------------
    {
        "id": "ssl-cert-check",
        "name": "ssl-cert-check",
        "description": "Check SSL certificate expiry for one or more hosts and alert before they expire.",
        "category": "monitoring",
        "icon": "lock_closed",
        "cron_expression": "0 9 * * *",
        "python_version": "3.12",
        "timeout": 60,
        "dependencies": "",
        "environment_vars": (
            "HOSTS=example.com,api.example.com\n"
            "PORT=443\n"
            "WARN_DAYS=30\n"
            "CRITICAL_DAYS=7"
        ),
        "code": '''\
import os
import socket
import ssl
from datetime import datetime, timezone
from cronator_lib import get_logger, notify, timer

logger = get_logger()

HOSTS = [h.strip() for h in os.environ.get("HOSTS", "example.com").split(",") if h.strip()]
PORT = int(os.environ.get("PORT", "443"))
WARN_DAYS = int(os.environ.get("WARN_DAYS", "30"))
CRITICAL_DAYS = int(os.environ.get("CRITICAL_DAYS", "7"))


def get_cert_expiry(host: str, port: int) -> datetime:
    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=10) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            cert = tls.getpeercert()
    # ssl.cert_time_to_seconds handles the "Apr  5 ..." format including double-space padding
    expiry_ts = ssl.cert_time_to_seconds(cert["notAfter"])
    return datetime.fromtimestamp(expiry_ts, tz=timezone.utc)


def main():
    now = datetime.now(timezone.utc)
    critical, warn = [], []

    for host in HOSTS:
        with timer(host):
            try:
                expiry = get_cert_expiry(host, PORT)
                days_left = (expiry - now).days
                expiry_str = expiry.strftime("%Y-%m-%d")

                msg = f"{host}: expires {expiry_str} ({days_left}d left)"

                if days_left <= CRITICAL_DAYS:
                    logger.error(f"CRITICAL -- {msg}")
                    critical.append(host)
                elif days_left <= WARN_DAYS:
                    logger.warning(f"WARNING -- {msg}")
                    warn.append(host)
                else:
                    logger.info(f"OK -- {msg}")

            except ssl.SSLCertVerificationError as exc:
                logger.error(f"CERT ERROR -- {host}: {exc}")
                critical.append(host)
            except (socket.timeout, ConnectionRefusedError, OSError) as exc:
                logger.error(f"CONNECT ERROR -- {host}: {exc}")
                critical.append(host)

    if critical:
        notify(f"SSL CRITICAL: {', '.join(critical)}")
        raise RuntimeError(f"SSL cert critical for: {', '.join(critical)}")
    elif warn:
        notify(f"SSL expiring soon: {', '.join(warn)}")


if __name__ == "__main__":
    main()
''',
    },
    # ------------------------------------------------------------------
    # Monitoring (continued)
    # ------------------------------------------------------------------
    {
        "id": "port-check",
        "name": "port-check",
        "description": "TCP-check remote host:port combinations (Redis, MySQL, any service) and alert on failures.",
        "category": "monitoring",
        "icon": "signal",
        "cron_expression": "*/5 * * * *",
        "python_version": "3.12",
        "timeout": 60,
        "dependencies": "",
        "environment_vars": "TARGETS=redis-host:6379,db-host:5432\nTIMEOUT=5",
        "code": '''\
import os
import socket
from cronator_lib import get_logger, notify, timer

logger = get_logger()

# Comma-separated list of host:port targets
TARGETS_RAW = os.environ.get("TARGETS", "localhost:6379")
TIMEOUT = float(os.environ.get("TIMEOUT", "5"))


def check_port(host: str, port: int) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=TIMEOUT):
            pass
        return True, ""
    except socket.timeout:
        return False, "timeout"
    except ConnectionRefusedError:
        return False, "connection refused"
    except OSError as exc:
        return False, str(exc)


def parse_targets(raw: str) -> list[tuple[str, int]]:
    targets = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        host, _, port_str = item.rpartition(":")
        if not host or not port_str:
            logger.warning(f"Skipping invalid target (expected host:port): {item}")
            continue
        try:
            targets.append((host, int(port_str)))
        except ValueError:
            logger.warning(f"Skipping target with non-numeric port: {item}")
    return targets


def main():
    targets = parse_targets(TARGETS_RAW)
    if not targets:
        raise ValueError("No valid targets found in TARGETS env var")

    failures = []

    for host, port in targets:
        with timer(f"{host}:{port}"):
            ok, err = check_port(host, port)

        if ok:
            logger.info(f"OK   {host}:{port}")
        else:
            logger.error(f"FAIL {host}:{port} -- {err}")
            failures.append(f"{host}:{port}")

    if failures:
        notify(f"Port check failed: {', '.join(failures)}")
        raise RuntimeError(f"Unreachable: {', '.join(failures)}")

    logger.info(f"All {len(targets)} port(s) reachable")


if __name__ == "__main__":
    main()
''',
    },
    {
        "id": "dns-check",
        "name": "dns-check",
        "description": "Verify DNS resolution for a list of domains. Optionally alert if resolved IPs change.",
        "category": "monitoring",
        "icon": "globe_alt",
        "cron_expression": "*/15 * * * *",
        "python_version": "3.12",
        "timeout": 60,
        "dependencies": "",
        "environment_vars": "HOSTS=example.com,api.example.com\nEXPECTED_IP=",
        "code": '''\
import os
import socket
from cronator_lib import get_logger, notify, timer

logger = get_logger()

HOSTS = [h.strip() for h in os.environ.get("HOSTS", "example.com").split(",") if h.strip()]
# Optional: alert if none of the resolved IPs match (comma-separated)
EXPECTED_IP = os.environ.get("EXPECTED_IP", "").strip()


def resolve(host: str) -> list[str]:
    results = socket.getaddrinfo(host, None)
    return sorted({r[4][0] for r in results})


def main():
    expected = [ip.strip() for ip in EXPECTED_IP.split(",") if ip.strip()]
    failures = []

    for host in HOSTS:
        with timer(host):
            try:
                ips = resolve(host)
            except socket.gaierror as exc:
                logger.error(f"FAIL {host}: {exc}")
                failures.append(host)
                continue

        ip_str = ", ".join(ips)

        if expected and not any(ip in expected for ip in ips):
            logger.warning(f"WARN {host}: resolved to {ip_str}, expected one of {', '.join(expected)}")
            failures.append(host)
        else:
            logger.info(f"OK   {host} -> {ip_str}")

    if failures:
        notify(f"DNS check failed: {', '.join(failures)}")
        raise RuntimeError(f"DNS failures: {', '.join(failures)}")

    logger.info(f"All {len(HOSTS)} host(s) resolved OK")


if __name__ == "__main__":
    main()
''',
    },
    {
        "id": "heartbeat",
        "name": "heartbeat",
        "description": "Run your job logic and ping a watchdog URL (healthchecks.io / Uptime Kuma) on success or failure.",
        "category": "monitoring",
        "icon": "heart",
        "cron_expression": "*/10 * * * *",
        "python_version": "3.12",
        "timeout": 120,
        "dependencies": "",
        "environment_vars": "PING_URL=https://hc-ping.com/YOUR-UUID\nPING_ON_START=true",
        "code": '''\
import os
import urllib.request
from cronator_lib import get_logger, timer

logger = get_logger()

# healthchecks.io: https://hc-ping.com/UUID
# Uptime Kuma push:  https://uptime.example.com/api/push/UUID?status=up&msg=OK
PING_URL = os.environ.get("PING_URL", "")
PING_ON_START = os.environ.get("PING_ON_START", "true").lower() == "true"


def ping(url: str) -> None:
    """Send GET request to watchdog URL. Ignores non-critical errors."""
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            logger.info(f"Heartbeat -> {resp.status} {url}")
    except Exception as exc:
        logger.warning(f"Heartbeat ping failed (non-fatal): {exc}")


def job() -> None:
    """
    ---- Put your actual job logic here ----
    This function is called between the start and success pings.
    Raise an exception to trigger the failure ping.
    """
    logger.info("Job running...")
    # Example: check something, process data, etc.
    logger.info("Job complete")


def main():
    if not PING_URL:
        raise ValueError("PING_URL must be set (e.g. https://hc-ping.com/your-uuid)")

    base_url = PING_URL.rstrip("/")

    if PING_ON_START:
        ping(f"{base_url}/start")

    with timer("job"):
        try:
            job()
        except Exception as exc:
            logger.error(f"Job failed: {exc}")
            ping(f"{base_url}/fail")
            raise

    ping(base_url)


if __name__ == "__main__":
    main()
''',
    },
    # ------------------------------------------------------------------
    # Data (continued)
    # ------------------------------------------------------------------
    {
        "id": "mysql-backup",
        "name": "mysql-backup",
        "description": "Dump a MySQL/MariaDB database with mysqldump, compress it, and save as an artifact.",
        "category": "data",
        "icon": "archive_box",
        "cron_expression": "0 2 * * *",
        "python_version": "3.12",
        "timeout": 3600,
        "dependencies": "",
        "environment_vars": "DB_HOST=localhost\nDB_PORT=3306\nDB_NAME=mydb\nDB_USER=root\nMYSQL_PWD=secret",
        "code": '''\
import gzip
import os
import subprocess
from datetime import datetime
from cronator_lib import get_logger, notify, save_artifact, timer

logger = get_logger()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "3306")
DB_NAME = os.environ.get("DB_NAME", "mydb")
DB_USER = os.environ.get("DB_USER", "root")
# Set MYSQL_PWD in environment variables — mysqldump reads it automatically


def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    gz_file = f"/tmp/backup_{DB_NAME}_{timestamp}.sql.gz"

    logger.info(f"Backing up {DB_NAME} on {DB_HOST}:{DB_PORT}")

    with timer("mysqldump"):
        result = subprocess.run(
            [
                "mysqldump",
                f"--host={DB_HOST}",
                f"--port={DB_PORT}",
                f"--user={DB_USER}",
                "--single-transaction",
                "--routines",
                "--triggers",
                "--set-gtid-purged=OFF",
                DB_NAME,
            ],
            capture_output=True,
            # Pass only DB credentials; do not inherit the full process environment
            env={k: v for k, v in os.environ.items() if k in (
                "MYSQL_PWD", "PATH", "HOME", "LANG",
                "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER",
            )},
        )

    if result.returncode != 0:
        err = result.stderr.decode(errors="replace").strip()
        logger.error(f"mysqldump failed (exit {result.returncode})")
        logger.error(err)
        raise RuntimeError(f"Backup failed (exit code {result.returncode})")

    with timer("compress"):
        with gzip.open(gz_file, "wb") as f:
            f.write(result.stdout)

    size_mb = os.path.getsize(gz_file) / 1024 / 1024
    logger.info(f"Compressed size: {size_mb:.1f} MB")

    save_artifact(gz_file, f"backup_{DB_NAME}_{timestamp}.sql.gz")
    notify(f"MySQL backup complete -- {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
''',
    },
    {
        "id": "s3-upload",
        "name": "s3-upload",
        "description": "Fetch data from a URL and upload it to S3-compatible storage (AWS S3, MinIO, Cloudflare R2).",
        "category": "data",
        "icon": "arrow_up_tray",
        "cron_expression": "0 * * * *",
        "python_version": "3.12",
        "timeout": 300,
        "dependencies": "boto3",
        "environment_vars": "SOURCE_URL=https://jsonplaceholder.typicode.com/posts\nS3_BUCKET=my-bucket\nS3_KEY_PREFIX=cronator/\nS3_ENDPOINT=\nAWS_REGION=us-east-1\nAWS_ACCESS_KEY_ID=\nAWS_SECRET_ACCESS_KEY=",
        "code": '''\
import json
import os
import urllib.request
from datetime import datetime

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from cronator_lib import get_logger, notify, timer

logger = get_logger()

SOURCE_URL = os.environ.get("SOURCE_URL", "")
S3_BUCKET = os.environ.get("S3_BUCKET", "")
S3_KEY_PREFIX = os.environ.get("S3_KEY_PREFIX", "cronator/")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "")  # e.g. https://s3.example.com for MinIO/R2
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
# AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are read by boto3 automatically


def fetch(url: str) -> tuple[bytes, str]:
    """Returns (content_bytes, guessed_filename)."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Cronator-S3-Upload/1.0")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    filename = url.rstrip("/").split("/")[-1] or "export"
    return data, filename


def s3_client():
    kwargs: dict = {"region_name": AWS_REGION}
    if S3_ENDPOINT:
        kwargs["endpoint_url"] = S3_ENDPOINT
    return boto3.client("s3", **kwargs)


def upload(data: bytes, bucket: str, key: str) -> None:
    client = s3_client()
    try:
        client.put_object(Bucket=bucket, Key=key, Body=data)
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError(f"S3 upload error: {exc}") from exc


def main():
    if not S3_BUCKET:
        raise ValueError("S3_BUCKET must be set")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if SOURCE_URL:
        logger.info(f"Fetching {SOURCE_URL}")
        with timer("fetch"):
            data, filename = fetch(SOURCE_URL)
        logger.info(f"Fetched {len(data):,} bytes")
    else:
        # Default: upload a JSON status record
        filename = "status.json"
        data = json.dumps({
            "timestamp": datetime.now().isoformat(),
            "status": "ok",
            "source": "cronator",
        }).encode()
        logger.info("No SOURCE_URL set — uploading status record")

    s3_key = f"{S3_KEY_PREFIX}{timestamp}_{filename}"
    endpoint_tag = f" ({S3_ENDPOINT})" if S3_ENDPOINT else ""

    with timer("s3 upload"):
        upload(data, S3_BUCKET, s3_key)

    size_kb = len(data) / 1024
    logger.info(f"Uploaded {size_kb:.1f} KB -> s3://{S3_BUCKET}/{s3_key}{endpoint_tag}")
    notify(f"S3 upload complete: {s3_key}")


if __name__ == "__main__":
    main()
''',
    },
    {
        "id": "db-query-report",
        "name": "db-query-report",
        "description": "Run a SQL query on a remote PostgreSQL database, export results as CSV, and save as artifact.",
        "category": "data",
        "icon": "document",
        "cron_expression": "0 7 * * 1-5",
        "python_version": "3.12",
        "timeout": 300,
        "dependencies": "psycopg2-binary",
        "environment_vars": "DB_HOST=localhost\nDB_PORT=5432\nDB_NAME=mydb\nDB_USER=postgres\nDB_PASSWORD=\nQUERY=SELECT id, name, created_at FROM users ORDER BY created_at DESC LIMIT 100\nOUTPUT_FILENAME=report.csv",
        "code": '''\
import csv
import os
from datetime import datetime

import psycopg2
import psycopg2.extras

from cronator_lib import get_logger, notify, save_artifact, timer

logger = get_logger()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "mydb")
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
QUERY = os.environ.get("QUERY", "SELECT current_timestamp AS ts, 'ok' AS status")
OUTPUT_FILENAME = os.environ.get("OUTPUT_FILENAME", "report.csv")


def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = f"/tmp/{timestamp}_{OUTPUT_FILENAME}"

    logger.info(f"Connecting to {DB_NAME} on {DB_HOST}:{DB_PORT}")

    with timer("query"):
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            connect_timeout=10,
        )
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(QUERY)
                rows = cur.fetchall()
                colnames = [desc.name for desc in cur.description] if cur.description else []
        finally:
            conn.close()

    logger.info(f"Query returned {len(rows)} row(s)")

    if not rows:
        logger.warning("No rows returned — skipping artifact")
        notify("db-query-report: query returned 0 rows")
        return

    with timer("write csv"):
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=colnames)
            writer.writeheader()
            writer.writerows([dict(r) for r in rows])

    artifact_name = f"{timestamp}_{OUTPUT_FILENAME}"
    save_artifact(output_path, artifact_name)
    notify(f"Query report ready: {len(rows)} rows -> {artifact_name}")
    logger.info(f"Saved artifact: {artifact_name}")


if __name__ == "__main__":
    main()
''',
    },
    # ------------------------------------------------------------------
    # Maintenance (continued)
    # ------------------------------------------------------------------
    {
        "id": "db-vacuum",
        "name": "db-vacuum",
        "description": "Run VACUUM ANALYZE on a remote PostgreSQL database to reclaim storage and update planner stats.",
        "category": "maintenance",
        "icon": "cog",
        "cron_expression": "0 4 * * 0",
        "python_version": "3.12",
        "timeout": 3600,
        "dependencies": "psycopg2-binary",
        "environment_vars": "DB_HOST=localhost\nDB_PORT=5432\nDB_NAME=mydb\nDB_USER=postgres\nDB_PASSWORD=\nTABLES=\nANALYZE=true",
        "code": '''\
import os

import psycopg2

from cronator_lib import get_logger, timer

logger = get_logger()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "mydb")
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
# Comma-separated table names; leave empty to vacuum the entire database
TABLES = [t.strip() for t in os.environ.get("TABLES", "").split(",") if t.strip()]
DO_ANALYZE = os.environ.get("ANALYZE", "true").lower() == "true"


def main():
    verb = "VACUUM ANALYZE" if DO_ANALYZE else "VACUUM"

    logger.info(f"Connecting to {DB_NAME} on {DB_HOST}:{DB_PORT}")

    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=10,
    )
    # VACUUM must run outside a transaction block
    conn.autocommit = True

    try:
        with conn.cursor() as cur:
            if TABLES:
                for table in TABLES:
                    # Table names come from env var, not user input; validated to be non-empty strings
                    sql = f"{verb} {table}"  # nosec
                    logger.info(f"Running: {sql}")
                    with timer(table):
                        cur.execute(sql)
                    logger.info(f"Done: {table}")
            else:
                logger.info(f"Running: {verb} (all tables in {DB_NAME})")
                with timer("all tables"):
                    cur.execute(verb)
                logger.info("Done")
    finally:
        conn.close()

    logger.info("VACUUM complete")


if __name__ == "__main__":
    main()
''',
    },
    # ------------------------------------------------------------------
    # Notification (continued)
    # ------------------------------------------------------------------
    {
        "id": "ntfy-notify",
        "name": "ntfy-notify",
        "description": "Send a push notification via ntfy.sh (or self-hosted ntfy server). No SDK required.",
        "category": "notification",
        "icon": "bell",
        "cron_expression": "0 9 * * 1-5",
        "python_version": "3.12",
        "timeout": 30,
        "dependencies": "",
        "environment_vars": "NTFY_URL=https://ntfy.sh\nNTFY_TOPIC=my-topic\nNTFY_TOKEN=\nMESSAGE=Cronator: scheduled report at {time}\nTITLE=Cronator\nPRIORITY=default\nTAGS=white_check_mark",
        "code": '''\
import os
import urllib.request
from datetime import datetime
from cronator_lib import get_logger, timer

logger = get_logger()

NTFY_URL = os.environ.get("NTFY_URL", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_TOKEN = os.environ.get("NTFY_TOKEN", "")  # For private/authenticated topics
MESSAGE_TPL = os.environ.get("MESSAGE", "Cronator: scheduled report at {time}")
TITLE = os.environ.get("TITLE", "Cronator")
# Priority: min | low | default | high | urgent
PRIORITY = os.environ.get("PRIORITY", "default")
# Tags: comma-separated emoji shortcodes, e.g. "white_check_mark,tada"
TAGS = os.environ.get("TAGS", "white_check_mark")


def main():
    if not NTFY_TOPIC:
        raise ValueError("NTFY_TOPIC must be set")

    text = MESSAGE_TPL.format(time=datetime.now().strftime("%Y-%m-%d %H:%M"))
    url = f"{NTFY_URL}/{NTFY_TOPIC}"

    headers = {
        "Title": TITLE,
        "Priority": PRIORITY,
        "Tags": TAGS,
        "Content-Type": "text/plain; charset=utf-8",
    }
    if NTFY_TOKEN:
        headers["Authorization"] = f"Bearer {NTFY_TOKEN}"

    logger.info(f"Sending ntfy notification to topic '{NTFY_TOPIC}'")

    req = urllib.request.Request(url, data=text.encode(), headers=headers)
    with timer("send"):
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status

    logger.info(f"Sent (HTTP {status}, topic={NTFY_TOPIC})")


if __name__ == "__main__":
    main()
''',
    },
    {
        "id": "pushover-notify",
        "name": "pushover-notify",
        "description": "Send a push notification to iOS/Android via the Pushover API.",
        "category": "notification",
        "icon": "device_phone_mobile",
        "cron_expression": "0 9 * * 1-5",
        "python_version": "3.12",
        "timeout": 30,
        "dependencies": "",
        "environment_vars": "PUSHOVER_TOKEN=\nPUSHOVER_USER=\nMESSAGE=Cronator: scheduled report at {time}\nTITLE=Cronator\nPRIORITY=0\nSOUND=",
        "code": '''\
import json
import os
import urllib.request
from datetime import datetime
from cronator_lib import get_logger, timer

logger = get_logger()

PUSHOVER_TOKEN = os.environ.get("PUSHOVER_TOKEN", "")  # App token from pushover.net
PUSHOVER_USER = os.environ.get("PUSHOVER_USER", "")   # User/group key
MESSAGE_TPL = os.environ.get("MESSAGE", "Cronator: scheduled report at {time}")
TITLE = os.environ.get("TITLE", "Cronator")
# Priority: -2 (silent) | -1 (quiet) | 0 (normal) | 1 (high) | 2 (emergency)
PRIORITY = int(os.environ.get("PRIORITY", "0"))
SOUND = os.environ.get("SOUND", "")  # e.g. "magic", "cashregister", "none"

PUSHOVER_API = "https://api.pushover.net/1/messages.json"


def main():
    if not PUSHOVER_TOKEN or not PUSHOVER_USER:
        raise ValueError("PUSHOVER_TOKEN and PUSHOVER_USER must be set")

    text = MESSAGE_TPL.format(time=datetime.now().strftime("%Y-%m-%d %H:%M"))
    preview = text[:60] + ("..." if len(text) > 60 else "")
    logger.info(f"Sending Pushover notification: {preview}")

    payload: dict = {
        "token": PUSHOVER_TOKEN,
        "user": PUSHOVER_USER,
        "message": text,
        "title": TITLE,
        "priority": PRIORITY,
    }
    if SOUND:
        payload["sound"] = SOUND

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        PUSHOVER_API,
        data=data,
        headers={"Content-Type": "application/json"},
    )

    with timer("send"):
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())

    if result.get("status") == 1:
        logger.info(f"Sent (request={result.get('request')})")
    else:
        errors = result.get("errors", ["unknown error"])
        logger.error(f"Pushover error: {errors}")
        raise RuntimeError(f"Pushover failed: {errors}")


if __name__ == "__main__":
    main()
''',
    },
]


def get_templates() -> list[ScriptTemplate]:
    return _TEMPLATES


def get_template(template_id: str) -> ScriptTemplate | None:
    return next((t for t in _TEMPLATES if t["id"] == template_id), None)
