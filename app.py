from flask import Flask, request, jsonify
import threading
import datetime
import re
import logging

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
        start_timer(device_id, monitor["timeout_seconds"])


def trigger_alert(device_id):
    if device_id not in monitors:
        return
    monitors[device_id]["status"] = "down"
    monitors[device_id]["timer"] = None
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"
    logger.warning(f"ALERT - Device '{device_id}' is DOWN! Time: {timestamp}")
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
        "timer":           None
    }

    start_timer(device_id, timeout_seconds)
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

    if monitor["status"] == "paused":
        monitor["status"] = "active"
        logger.info(f"Monitor '{device_id}' unpaused by heartbeat.")

    if monitor["status"] == "down":
        monitor["status"] = "active"
        logger.info(f"Monitor '{device_id}' recovered via heartbeat.")

    start_timer(device_id, monitor["timeout_seconds"])
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
    logger.info(f"Monitor '{device_id}' paused.")

    return jsonify({
        "message": f"Monitor '{device_id}' paused. No alerts will fire.",
        "status":  "paused"
    }), 200


@app.route("/monitors/<device_id>", methods=["GET"])
def get_monitor(device_id):
    if device_id not in monitors:
        return jsonify({"error": f"Monitor '{device_id}' not found."}), 404

    monitor = monitors[device_id]

    return jsonify({
        "id":          monitor["id"],
        "status":      monitor["status"],
        "timeout":     f"{monitor['timeout']} {monitor['timeout_unit']}",
        "alert_email": monitor["alert_email"]
    }), 200


@app.route("/monitors", methods=["GET"])
def list_monitors():
    all_monitors = [
        {
            "id":          m["id"],
            "status":      m["status"],
            "timeout":     f"{m['timeout']} {m['timeout_unit']}",
            "alert_email": m["alert_email"]
        }
        for m in monitors.values()
    ]

    return jsonify({
        "total":    len(all_monitors),
        "monitors": all_monitors
    }), 200


if __name__ == "__main__":
    logger.info("Pulse Check API starting up...")
    app.run(debug=True)