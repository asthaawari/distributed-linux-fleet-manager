import hmac
import ipaddress
import json
import math
import os
import re
import socket
import sqlite3
import time
from datetime import datetime, timezone

import paramiko
import requests
from flask import Flask, Response, redirect, render_template_string, request

app = Flask(__name__)

DB_NAME = "fleet.db"
TARGETS_FILE = "prometheus/targets.json"
PROMETHEUS_URL = "http://127.0.0.1:9090/api/v1/query"
KNOWN_HOSTS = "fleet_known_hosts"          # host keys pinned at onboarding
SSH_USER = os.environ.get("FLEET_SSH_USER", "ubuntu")
SSH_KEY = os.environ.get("FLEET_SSH_KEY", "/home/ubuntu/.ssh/id_ed25519")
ADMIN_PASSWORD = os.environ.get("FLEET_ADMIN_PASSWORD")
EXPORTER_PORT = 9100
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,30}$")

ALLOWED_COMMANDS = {
    "hostname": "hostname",
    "disk": "df -h /",
    "uptime": "uptime",
    "memory": "free -m",
    "failed_services": "systemctl --failed --no-pager",
}
INSTALL_EXPORTER = ("sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive "
                    "apt-get install -y prometheus-node-exporter")

QUERIES = {
    "cpu": '100 - avg by(instance)(rate(node_cpu_seconds_total{job="fleet-nodes",mode="idle"}[2m])) * 100',
    "mem": '(1 - node_memory_MemAvailable_bytes{job="fleet-nodes"} / node_memory_MemTotal_bytes{job="fleet-nodes"}) * 100',
    "disk": '(1 - node_filesystem_avail_bytes{job="fleet-nodes",mountpoint="/",fstype!="tmpfs"} / node_filesystem_size_bytes{job="fleet-nodes",mountpoint="/",fstype!="tmpfs"}) * 100',
}


# ---------- access control ----------
@app.before_request
def require_login():
    if not ADMIN_PASSWORD:
        return None
    auth = request.authorization
    if auth and hmac.compare_digest((auth.password or "").encode(), ADMIN_PASSWORD.encode()):
        return None
    return Response("Login required", 401, {"WWW-Authenticate": 'Basic realm="Fleet Manager"'})


# ---------- database ----------
def db():
    return sqlite3.connect(DB_NAME, timeout=10)


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                ip TEXT NOT NULL UNIQUE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS command_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                node TEXT NOT NULL,
                command TEXT NOT NULL,
                status TEXT NOT NULL,
                duration_ms INTEGER,
                source_ip TEXT,
                detail TEXT
            )
        """)
    open(KNOWN_HOSTS, "a").close()
    os.makedirs(os.path.dirname(TARGETS_FILE), exist_ok=True)


def log_event(node, command, status, duration_ms=None, detail=""):
    """Audit trail. Never pass keys, passwords or full command output here."""
    with db() as conn:
        conn.execute(
            "INSERT INTO command_log (ts, node, command, status, duration_ms, source_ip, detail) "
            "VALUES (?,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), node, command,
             status, duration_ms, request.remote_addr, (detail or "")[:200]),
        )


def update_targets():
    with db() as conn:
        nodes = conn.execute("SELECT name, ip FROM nodes ORDER BY id").fetchall()
    targets = [
        {"targets": [f"{ip}:{EXPORTER_PORT}"], "labels": {"instance": name}}
        for name, ip in nodes
    ]
    with open(TARGETS_FILE, "w") as file:   # written in place on purpose (keeps Docker mounts working)
        json.dump(targets, file, indent=2)


# ---------- validation ----------
def check_ip(ip):
    try:
        addr = ipaddress.IPv4Address(ip)
    except ValueError:
        return "Invalid IPv4 address."
    if addr.is_loopback or addr.is_unspecified or addr.is_multicast:
        return "That IP address is not allowed."
    return None


def error_page(message, code=400):
    return render_template_string(
        "<h2>Error</h2><p>{{ m }}</p><a href='/'>Back to Fleet Manager</a>", m=message), code


# ---------- SSH ----------
def ssh_exec(ip, command, pin=False, cmd_timeout=10):
    """Run one command. pin=True trusts the host key on FIRST contact and saves it;
    afterwards a changed key is rejected."""
    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.load_host_keys(KNOWN_HOSTS)
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy() if pin else paramiko.RejectPolicy())
    try:
        ssh.connect(hostname=ip, username=SSH_USER, key_filename=SSH_KEY,
                    timeout=5, banner_timeout=5, auth_timeout=5)
        # Persist a newly trusted host key so later connections can reject changes.
        if pin:
            ssh.save_host_keys(KNOWN_HOSTS)
        _, stdout, stderr = ssh.exec_command(command, timeout=cmd_timeout)
        out = stdout.read().decode(errors="replace")[:5000]
        err = stderr.read().decode(errors="replace")[:2000]
        return stdout.channel.recv_exit_status() == 0, out, err
    except Exception as e:
        return False, "", f"SSH error: {e}"
    finally:
        ssh.close()


def exporter_reachable(ip):
    for _ in range(5):
        try:
            r = requests.get(f"http://{ip}:{EXPORTER_PORT}/metrics", timeout=2, stream=True)
            r.close()
            if r.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False


def port_open(ip, port=22, timeout=1.0):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


# ---------- Prometheus ----------
def prom_query(expr):
    """{instance_name: float}; empty dict if Prometheus is unreachable (graceful degradation)."""
    try:
        response = requests.get(PROMETHEUS_URL, params={"query": expr}, timeout=3)
        response.raise_for_status()
        return {item["metric"]["instance"]: float(item["value"][1])
                for item in response.json()["data"]["result"]}
    except (requests.RequestException, ValueError, KeyError):
        return {}


def fmt(value):
    return "-" if value is None or math.isnan(value) else f"{value:.1f}%"


HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Linux Fleet Manager</title>
    <style>
        body{font-family:sans-serif;margin:24px}
        table{border-collapse:collapse;margin-bottom:16px}
        td,th{border:1px solid #bbb;padding:6px 10px;text-align:left}
        .up{color:#1b7f3b;font-weight:bold}.down{color:#c62828;font-weight:bold}
        .degraded{color:#b26a00;font-weight:bold}.unknown{color:#666}
    </style>
</head>
<body>
    <h1>Distributed Linux Fleet Manager</h1>
    <p><b>Total:</b> {{ total }} &nbsp; <b>Up:</b> {{ n_up }} &nbsp;
       <b>Degraded:</b> {{ n_deg }} &nbsp; <b>Down:</b> {{ n_down }}</p>

    <h2>Register a Linux Machine</h2>
    <form method="POST" action="/register">
        <label>Machine Name:</label> <input name="name" required maxlength="31">
        <label>IP Address:</label> <input name="ip" required>
        <button type="submit">Register Node</button>
    </form>
    <p><small>Registration connects over SSH, installs node_exporter and starts monitoring (up to a minute).</small></p>

    <h2>Registered Machines</h2>
    <table>
        <tr><th>Name</th><th>IP Address</th><th>Status</th><th>CPU</th><th>Memory</th><th>Disk /</th>
            <th>Remote Commands</th><th>Update IP</th><th></th></tr>
        {% for n in nodes %}
        <tr>
            <td>{{ n.name }}</td>
            <td>{{ n.ip }}</td>
            <td class="{{ n.css }}">{{ n.status }}</td>
            <td>{{ n.cpu }}</td><td>{{ n.mem }}</td><td>{{ n.disk }}</td>
            <td>
                <form method="POST" action="/command">
                    <input type="hidden" name="ip" value="{{ n.ip }}">
                    {% for key in commands %}<button name="command" value="{{ key }}">{{ key }}</button> {% endfor %}
                </form>
            </td>
            <td>
                <form method="POST" action="/update_ip">
                    <input type="hidden" name="id" value="{{ n.id }}">
                    <input name="ip" size="14" placeholder="new IP" required>
                    <button>Update</button>
                </form>
            </td>
            <td>
                <form method="POST" action="/delete" onsubmit="return confirm('Remove {{ n.name }}?')">
                    <input type="hidden" name="id" value="{{ n.id }}">
                    <button>Remove</button>
                </form>
            </td>
        </tr>
        {% else %}
        <tr><td colspan="9">No machines registered.</td></tr>
        {% endfor %}
    </table>

    <h2>Audit Log (last 15 actions)</h2>
    <table>
        <tr><th>Time (UTC)</th><th>Node</th><th>Action</th><th>Result</th><th>ms</th><th>Detail</th></tr>
        {% for l in logs %}
        <tr><td>{{ l[0] }}</td><td>{{ l[1] }}</td><td>{{ l[2] }}</td><td>{{ l[3] }}</td>
            <td>{{ l[4] if l[4] is not none else '' }}</td><td>{{ l[5] }}</td></tr>
        {% else %}
        <tr><td colspan="6">No actions yet.</td></tr>
        {% endfor %}
    </table>
    <p>Refresh the page to check the latest status.</p>
</body>
</html>
"""


@app.route("/")
def home():
    with db() as conn:
        rows = conn.execute("SELECT id, name, ip FROM nodes ORDER BY id").fetchall()
        logs = conn.execute(
            "SELECT ts, node, command, status, duration_ms, detail "
            "FROM command_log ORDER BY id DESC LIMIT 15").fetchall()

    up = prom_query('up{job="fleet-nodes"}')
    cpu, mem, disk = (prom_query(QUERIES[k]) for k in ("cpu", "mem", "disk"))

    nodes = []
    for node_id, name, ip in rows:
        if name not in up:
            status = "UNKNOWN"
        elif up[name] == 1:
            status = "UP"
        elif port_open(ip):
            status = "DEGRADED (exporter down, SSH reachable)"
        else:
            status = "DOWN (machine unreachable)"
        nodes.append({"id": node_id, "name": name, "ip": ip, "status": status,
                      "css": status.split()[0].lower(),
                      "cpu": fmt(cpu.get(name)), "mem": fmt(mem.get(name)), "disk": fmt(disk.get(name))})

    count = lambda word: sum(1 for n in nodes if n["status"].startswith(word))
    return render_template_string(
        HTML, nodes=nodes, logs=logs, commands=list(ALLOWED_COMMANDS), total=len(nodes),
        n_up=count("UP"), n_deg=count("DEGRADED"), n_down=count("DOWN"))


@app.route("/register", methods=["POST"])
def register():
    name = request.form.get("name", "").strip()
    ip = request.form.get("ip", "").strip()

    if not NAME_RE.match(name):
        return error_page("Name must be 1-31 characters: letters, digits, '-' or '_'.")
    problem = check_ip(ip)
    if problem:
        return error_page(problem)
    with db() as conn:
        if conn.execute("SELECT 1 FROM nodes WHERE name = ? OR ip = ?", (name, ip)).fetchone():
            return error_page("This name or IP address is already registered.")

    ok, _, err = ssh_exec(ip, INSTALL_EXPORTER, pin=True, cmd_timeout=180)
    if not ok:
        log_event(name, "onboard", "failed", detail=err)
        return error_page(f"Onboarding failed: {err or 'could not install node_exporter'}", 502)
    if not exporter_reachable(ip):
        log_event(name, "onboard", "failed", detail="exporter not reachable on 9100")
        return error_page("node_exporter is installed but port 9100 is not reachable.", 502)

    try:
        with db() as conn:
            conn.execute("INSERT INTO nodes (name, ip) VALUES (?, ?)", (name, ip))
    except sqlite3.IntegrityError:
        return error_page("This name or IP address is already registered.")

    update_targets()
    log_event(name, "onboard", "success")
    return redirect("/")


@app.route("/update_ip", methods=["POST"])
def update_ip():
    try:
        node_id = int(request.form.get("id", ""))
    except ValueError:
        return error_page("Invalid node.")
    new_ip = request.form.get("ip", "").strip()
    problem = check_ip(new_ip)
    if problem:
        return error_page(problem)
    with db() as conn:
        node = conn.execute("SELECT name FROM nodes WHERE id = ?", (node_id,)).fetchone()
        taken = conn.execute("SELECT 1 FROM nodes WHERE ip = ? AND id != ?", (new_ip, node_id)).fetchone()
    if not node:
        return error_page("Node not found.", 404)
    if taken:
        return error_page("That IP is already used by another node.")

    ok, _, err = ssh_exec(new_ip, "hostname", pin=True)
    if not ok or not exporter_reachable(new_ip):
        log_event(node[0], "update_ip", "failed", detail=err or "exporter not reachable")
        return error_page(f"Could not verify the node at {new_ip}: {err or 'exporter not reachable'}", 502)

    with db() as conn:
        conn.execute("UPDATE nodes SET ip = ? WHERE id = ?", (new_ip, node_id))
    update_targets()
    log_event(node[0], "update_ip", "success", detail=new_ip)
    return redirect("/")


@app.route("/delete", methods=["POST"])
def delete():
    try:
        node_id = int(request.form.get("id", ""))
    except ValueError:
        return error_page("Invalid node.")
    with db() as conn:
        node = conn.execute("SELECT name FROM nodes WHERE id = ?", (node_id,)).fetchone()
        conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
    update_targets()
    if node:
        log_event(node[0], "remove", "success")
    return redirect("/")


@app.route("/command", methods=["POST"])
def command():
    node_ip = request.form.get("ip", "")
    command_key = request.form.get("command", "")

    with db() as conn:
        node = conn.execute("SELECT name FROM nodes WHERE ip = ?", (node_ip,)).fetchone()
    if not node:
        log_event(node_ip[:40] or "?", command_key[:40], "rejected", detail="node not registered")
        return error_page("Node not registered.")
    name = node[0]
    if command_key not in ALLOWED_COMMANDS:
        log_event(name, command_key[:40], "rejected", detail="command not in allowlist")
        return error_page("Command not allowed.")

    started = time.monotonic()
    ok, out, err = ssh_exec(node_ip, ALLOWED_COMMANDS[command_key])
    elapsed = int((time.monotonic() - started) * 1000)
    log_event(name, command_key, "success" if ok else "failed", elapsed, "" if ok else err)

    output = out if ok else (err or out or "Command failed.")
    return render_template_string(
        "<h2>Command Output</h2><pre>{{ output }}</pre><a href='/'>Back to Fleet Manager</a>",
        output=output)


if __name__ == "__main__":
    init_db()
    update_targets()
    if not ADMIN_PASSWORD:
        print("WARNING: FLEET_ADMIN_PASSWORD is not set; the web UI has no login.")
    app.run(host="0.0.0.0", port=5000, debug=False)