
from flask import Flask, request, redirect, render_template_string
import paramiko
import sqlite3
import json
import requests

app = Flask(__name__)
ALLOWED_COMMANDS = {
    "hostname": "hostname",
    "disk": "df -h /",
    "uptime": "uptime"
}

def run_remote_command(node_ip, command_key):
    if command_key not in ALLOWED_COMMANDS:
        return "Command not allowed."

    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())

    try:
        ssh.connect(
            hostname=node_ip,
            username="ubuntu",
            key_filename="/home/ubuntu/.ssh/id_ed25519",
            timeout=5
        )

        stdin, stdout, stderr = ssh.exec_command(
            ALLOWED_COMMANDS[command_key],
            timeout=10
        )

        output = stdout.read().decode()
        error = stderr.read().decode()
        return output if output else error

    except Exception as e:
        return f"SSH error: {e}"

    finally:
        ssh.close()

DB_NAME = "fleet.db"
TARGETS_FILE = "prometheus/targets.json"
PROMETHEUS_URL = "http://127.0.0.1:9090/api/v1/query"


def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                ip TEXT NOT NULL UNIQUE
            )
        """)


def update_targets():
    with sqlite3.connect(DB_NAME) as conn:
        nodes = conn.execute(
            "SELECT name, ip FROM nodes ORDER BY id"
        ).fetchall()

    targets = [
        {
            "targets": [f"{ip}:9100"],
            "labels": {"instance": name}
        }
        for name, ip in nodes
    ]

    with open(TARGETS_FILE, "w") as file:
        json.dump(targets, file, indent=2)


def get_node_status():
    try:
        response = requests.get(
            PROMETHEUS_URL,
            params={"query": 'up{job="fleet-nodes"}'},
            timeout=3
        )
        response.raise_for_status()
        results = response.json()["data"]["result"]

        return {
            item["metric"]["instance"]: (
                "UP" if item["value"][1] == "1" else "DOWN"
            )
            for item in results
        }
    except (requests.RequestException, ValueError, KeyError):
        return {}


HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Linux Fleet Manager</title>
</head>
<body>
    <h1>Distributed Linux Fleet Manager</h1>

    <h2>Register a Linux Machine</h2>
    <form method="POST" action="/register">
        <label>Machine Name:</label>
        <input name="name" required>

        <label>IP Address:</label>
        <input name="ip" required>

        <button type="submit">Register Node</button>
    </form>

    <h2>Registered Machines</h2>
    <table border="1" cellpadding="8">
        <tr><th>Name</th><th>IP Address</th><th>Status</th><th>Remote Commands</th></tr>
        {% for node in nodes %}
        <tr>
            <td>{{ node[1] }}</td>
            <td>{{ node[2] }}</td>
            <td>{{ status.get(node[1], "UNKNOWN") }}</td>
<td>
    <form method="POST" action="/command">
        <input type="hidden" name="ip" value="{{ node[2] }}">
        <button name="command" value="hostname">Hostname</button>
        <button name="command" value="disk">Disk Usage</button>
        <button name="command" value="uptime">Uptime</button>
    </form>
</td>
        </tr>
        {% else %}
        <tr><td colspan="4">No machines registered.</td></tr>
        {% endfor %}
    </table>

    <p>Refresh the page to check the latest status.</p>
</body>
</html>
"""


@app.route("/")
def home():
    with sqlite3.connect(DB_NAME) as conn:
        nodes = conn.execute(
            "SELECT * FROM nodes ORDER BY id"
        ).fetchall()

    status = get_node_status()
    return render_template_string(HTML, nodes=nodes, status=status)


@app.route("/register", methods=["POST"])
def register():
    name = request.form["name"].strip()
    ip = request.form["ip"].strip()

    if not name or not ip:
        return "Name and IP are required.", 400

    try:
        with sqlite3.connect(DB_NAME, timeout=10) as conn:
            conn.execute(
                "INSERT INTO nodes (name, ip) VALUES (?, ?)",
                (name, ip)
            )
    except sqlite3.IntegrityError:
        return "This IP address is already registered.", 400

    update_targets()
    return redirect("/")


@app.route("/command", methods=["POST"])
def command():
    node_ip = request.form.get("ip", "")
    command_key = request.form.get("command", "")

    with sqlite3.connect(DB_NAME) as conn:
        node = conn.execute(
            "SELECT name FROM nodes WHERE ip = ?",
            (node_ip,)
        ).fetchone()

    if not node:
        return "Node not registered.", 400

    output = run_remote_command(node_ip, command_key)

    return render_template_string(
        "<h2>Command Output</h2><pre>{{ output }}</pre><a href='/'>Back to Fleet Manager</a>",
        output=output
    )
if __name__ == "__main__":
    init_db()
    update_targets()
    app.run(host="0.0.0.0", port=5000, debug=False)
