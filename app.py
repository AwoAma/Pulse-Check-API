from flask import Flask, request, jsonify
import threading
import time

app = Flask(__name__)

# Storage dictionary to mimic a database
monitors = {}

import json
from datetime import datetime

def trigger_alert(device_id):
    """Runs automatically when the countdown timer hits 0"""
    if device_id in monitors:
        monitors[device_id]["status"] = "down"
        
        # This formats the data perfectly into the required JSON style
        alert_payload = {
            "ALERT": f"Device {device_id} is down",
            "time": datetime.utcnow().isoformat()
        }
        print(json.dumps(alert_payload))

@app.route('/monitors', methods=['POST'])
def register_monitor():
    """User Story 1: Register a new monitor with a countdown"""
    data = request.get_json()
    device_id = data.get("id")
    timeout = data.get("timeout")
    email = data.get("alert_email")
    
    if device_id in monitors and monitors[device_id]["timer"]:
        monitors[device_id]["timer"].cancel()
        
    t = threading.Timer(timeout, trigger_alert, args=[device_id])
    t.start()
    
    monitors[device_id] = {
        "timeout": timeout,
        "email": email,
        "status": "active",
        "timer": t
    }
    return jsonify({"message": f"Monitor for {device_id} started successfully."}), 201

@app.route('/monitors/<device_id>/heartbeat', methods=['POST'])
def heartbeat(device_id):
    """User Story 2: Heartbeat reset"""
    if device_id not in monitors:
        return jsonify({"error": "Monitor not found"}), 404
        
    monitors[device_id]["timer"].cancel()
    
    original_timeout = monitors[device_id]["timeout"]
    t = threading.Timer(original_timeout, trigger_alert, args=[device_id])
    t.start()
    
    monitors[device_id]["timer"] = t
    monitors[device_id]["status"] = "active"
    return jsonify({"message": "Heartbeat received, timer reset."}), 200

@app.route('/monitors/<device_id>/pause', methods=['POST'])
def pause_monitor(device_id):
    """User Story 6: Pause monitoring (The Snooze Button)"""
    if device_id not in monitors:
        return jsonify({"error": "Monitor not found"}), 404
        
    monitors[device_id]["timer"].cancel()
    monitors[device_id]["status"] = "paused"
    return jsonify({"message": f"Monitor for {device_id} paused."}), 200

@app.route('/monitors', methods=['GET'])
def get_all_monitors():
    """Developer's Choice: View status of all devices"""
    summary = {}
    for dev_id, info in monitors.items():
        summary[dev_id] = {
            "status": info["status"],
            "alert_email": info["email"],
            "timeout_seconds": info["timeout"]
        }
    return jsonify(summary), 200

if __name__ == '__main__':
    app.run(debug=True, port=5000)