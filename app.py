from flask import Flask, request, jsonify, render_template
import threading
import datetime
import re
import logging
import json
import os

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("pulse_check.log")
    ]
)
logger = logging.getLogger(__name__)

monitors = {}

RETRY_WAIT_SECONDS = 60
MONITORS_FILE = "monitors.json"


def save_monitors():
    data = {
        device_id: {k: v for k, v in monitor.items() if k != "timer"}
        for device_id, monitor in monitors.items()
    }
    with open(MONITORS_FILE, "w") as f:
        json.dump(data, f)


def load_monitors():
    if not os.path.exists(MONITORS_FILE):
        return
    with open(MONITORS_FILE, "r") as f:
        data = json.load(f)
    for device_id, monitor_data in data.items():
        monitors[device_id] = {**monitor_data, "timer": None}
        status = monitor_data["status"]
        if status == "active":
            start_timer(device_id, monitor_data["timeout_seconds"])
            logger.info(f"Restored active monitor '{device_id}' from disk.")
        elif status == "down":
            retry_timer = threading.Timer(RETRY_WAIT_SECONDS, retry_monitor, args=[device_id])
            retry_timer.daemon = True
            retry_timer.start()
            logger.info(f"Restored down monitor '{device_id}', retry scheduled in {RETRY_WAIT_SECONDS}s.")

UNIT_TO_SECONDS = {
    "seconds": 1,
    "minutes": 60,
    "hours":   3600,
    "days":    86400,
    "weeks":   604800
}


def is_valid_email(email):
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}$"
    return re.match(pattern, email) is not None


def convert_to_seconds(value, unit):
    unit = unit.lower()
    if unit not in UNIT_TO_SECONDS:
        return None
    return value * UNIT_TO_SECONDS[unit]


def retry_monitor(device_id):
    if device_id not in monitors:
        return
    monitor = monitors[device_id]
    if monitor["status"] == "down":
        logger.info(f"Retrying monitor for '{device_id}'...")
        monitor["status"] = "active"
        monitor["last_heartbeat"] = datetime.datetime.now(datetime.timezone.utc).timestamp()
        start_timer(device_id, monitor["timeout_seconds"])
        save_monitors()


def trigger_alert(device_id):
    if device_id not in monitors:
        return
    monitors[device_id]["timer"] = None
    monitors[device_id]["failure_count"] = monitors[device_id].get("failure_count", 0) + 1
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z"

    if monitors[device_id]["failure_count"] >= 2:
        monitors[device_id]["status"] = "critical"
        logger.warning(f"CRITICAL - Device '{device_id}' failed twice. Permanently down. Time: {timestamp}")
        logger.warning(f"Manual restart required: POST /monitors/{device_id}/restart")
        save_monitors()
    else:
        monitors[device_id]["status"] = "down"
        logger.warning(f"ALERT - Device '{device_id}' is DOWN! Time: {timestamp}")
        save_monitors()
        retry_timer = threading.Timer(RETRY_WAIT_SECONDS, retry_monitor, args=[device_id])
        retry_timer.daemon = True
        retry_timer.start()
        logger.info(f"Retry scheduled for '{device_id}' in {RETRY_WAIT_SECONDS} seconds.")


def start_timer(device_id, timeout_seconds):
    if monitors[device_id].get("timer"):
        monitors[device_id]["timer"].cancel()
    timer = threading.Timer(timeout_seconds, trigger_alert, args=[device_id])
    timer.daemon = True
    timer.start()
    monitors[device_id]["timer"] = timer


@app.route("/")
def dashboard():
    return render_template("index.html")


@app.route("/monitors", methods=["POST"])
def create_monitor():
    data = request.get_json()

    if not data or "id" not in data or "timeout" not in data:
        return jsonify({"error": "Missing required fields: 'id' and 'timeout'"}), 400

    device_id    = data["id"]
    timeout      = data["timeout"]
    timeout_unit = data.get("timeout_unit", "seconds")
    alert_email  = data.get("alert_email", "")

    if alert_email and not is_valid_email(alert_email):
        return jsonify({"error": f"'{alert_email}' is not a valid email address."}), 400

    timeout_seconds = convert_to_seconds(timeout, timeout_unit)
    if timeout_seconds is None:
        return jsonify({"error": f"Invalid timeout_unit '{timeout_unit}'. Use: seconds, minutes, hours, days, or weeks."}), 400

    if timeout_seconds <= 0:
        return jsonify({"error": "Timeout must be greater than zero."}), 400

    if device_id in monitors:
        return jsonify({"error": f"Monitor '{device_id}' already exists."}), 409

    monitors[device_id] = {
        "id":              device_id,
        "timeout":         timeout,
        "timeout_unit":    timeout_unit,
        "timeout_seconds": timeout_seconds,
        "alert_email":     alert_email,
        "status":          "active",
        "failure_count":   0,
        "last_heartbeat":  datetime.datetime.now(datetime.timezone.utc).timestamp(),
        "timer":           None
    }

    start_timer(device_id, timeout_seconds)
    save_monitors()
    logger.info(f"Monitor created for '{device_id}' | Timeout: {timeout} {timeout_unit} | Email: {alert_email}")

    return jsonify({
        "message": f"Monitor for {device_id} created.",
        "timeout": f"{timeout} {timeout_unit}",
        "status":  "active"
    }), 201


@app.route("/monitors/<device_id>/heartbeat", methods=["POST"])
def heartbeat(device_id):
    if device_id not in monitors:
        return jsonify({"error": f"Monitor '{device_id}' not found."}), 404

    monitor = monitors[device_id]

    if monitor["status"] == "critical":
        return jsonify({"error": f"Monitor '{device_id}' is critically down. Use POST /monitors/{device_id}/restart to bring it back online."}), 409

    if monitor["status"] == "paused":
        monitor["status"] = "active"
        logger.info(f"Monitor '{device_id}' unpaused by heartbeat.")

    if monitor["status"] == "down":
        monitor["status"] = "active"
        logger.info(f"Monitor '{device_id}' recovered via heartbeat.")

    monitor["failure_count"]  = 0
    monitor["last_heartbeat"] = datetime.datetime.now(datetime.timezone.utc).timestamp()
    start_timer(device_id, monitor["timeout_seconds"])
    save_monitors()
    logger.info(f"Heartbeat received for '{device_id}'. Timer reset.")

    return jsonify({
        "message":          "Heartbeat received. Timer reset.",
        "status":           "active",
        "next_expected_in": f"{monitor['timeout']} {monitor['timeout_unit']}"
    }), 200


@app.route("/monitors/<device_id>/pause", methods=["POST"])
def pause_monitor(device_id):
    if device_id not in monitors:
        return jsonify({"error": f"Monitor '{device_id}' not found."}), 404

    monitor = monitors[device_id]

    if monitor["status"] == "paused":
        return jsonify({"message": f"Monitor '{device_id}' is already paused."}), 200

    if monitor.get("timer"):
        monitor["timer"].cancel()
        monitor["timer"] = None

    monitor["status"] = "paused"
    save_monitors()
    logger.info(f"Monitor '{device_id}' paused.")

    return jsonify({
        "message": f"Monitor '{device_id}' paused. No alerts will fire.",
        "status":  "paused"
    }), 200


@app.route("/monitors/<device_id>/restart", methods=["POST"])
def restart_monitor(device_id):
    if device_id not in monitors:
        return jsonify({"error": f"Monitor '{device_id}' not found."}), 404

    monitor = monitors[device_id]

    if monitor["status"] != "critical":
        return jsonify({"error": f"Monitor '{device_id}' is not in critical state. Current status: {monitor['status']}."}), 400

    monitor["status"]         = "active"
    monitor["failure_count"]  = 0
    monitor["last_heartbeat"] = datetime.datetime.now(datetime.timezone.utc).timestamp()
    start_timer(device_id, monitor["timeout_seconds"])
    save_monitors()
    logger.info(f"Monitor '{device_id}' manually restarted after critical failure.")

    return jsonify({
        "message": f"Monitor '{device_id}' restarted successfully.",
        "status":  "active"
    }), 200


@app.route("/monitors/<device_id>", methods=["GET"])
def get_monitor(device_id):
    if device_id not in monitors:
        return jsonify({"error": f"Monitor '{device_id}' not found."}), 404

    monitor = monitors[device_id]

    return jsonify({
        "id":              monitor["id"],
        "status":          monitor["status"],
        "timeout":         f"{monitor['timeout']} {monitor['timeout_unit']}",
        "timeout_seconds": monitor["timeout_seconds"],
        "last_heartbeat":  monitor.get("last_heartbeat"),
        "alert_email":     monitor["alert_email"]
    }), 200


@app.route("/monitors", methods=["GET"])
def list_monitors():
    all_monitors = [
        {
            "id":              m["id"],
            "status":          m["status"],
            "timeout":         f"{m['timeout']} {m['timeout_unit']}",
            "timeout_seconds": m["timeout_seconds"],
            "last_heartbeat":  m.get("last_heartbeat"),
            "alert_email":     m["alert_email"]
        }
        for m in monitors.values()
    ]

    return jsonify({
        "total":    len(all_monitors),
        "monitors": all_monitors
    }), 200


if __name__ == "__main__":
    logger.info("Pulse Check API starting up...")
    logger.info("Dashboard: http://127.0.0.1:5000")
    logger.info("Available endpoints:")
    logger.info("  POST  http://127.0.0.1:5000/monitors")
    logger.info("  POST  http://127.0.0.1:5000/monitors/<id>/heartbeat")
    logger.info("  POST  http://127.0.0.1:5000/monitors/<id>/pause")
    logger.info("  POST  http://127.0.0.1:5000/monitors/<id>/restart")
    logger.info("  GET   http://127.0.0.1:5000/monitors")
    logger.info("  GET   http://127.0.0.1:5000/monitors/<id>")
    load_monitors()
    app.run(debug=True)