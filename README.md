# Distributed Linux Fleet Management

A centralized web application for registering, monitoring, and performing
approved remote operations on multiple Linux machines.

## 1. Overview

Managing several Linux machines individually can be time-consuming.
This project provides a central Fleet Manager interface to register Linux
nodes, monitor their availability, view system metrics, and execute
predefined remote commands over SSH.

The project is developed as part of the Zoho SETU project pathway.

## 2. Problem Statement

Administrators need a convenient way to monitor multiple Linux systems
without manually checking each machine. This project demonstrates centralized
node registration, automated monitoring discovery, availability tracking,
and controlled remote operations.

## 3. Objectives

- Register Linux nodes using their names and IP addresses.
- Store registered node information in SQLite.
- Establish SSH connections for approved remote operations.
- Monitor node availability using Prometheus.
- Collect CPU, memory, and other system metrics using node_exporter.
- Update Prometheus targets through file-based service discovery.
- Display node status in a centralized web interface.
- Execute predefined remote commands using an allowlist.
- Visualize monitoring information using Grafana.

## 4. Technology Stack

| Component | Technology |
|---|---|
| Backend | Python, Flask |
| Frontend | HTML rendered by Flask |
| Database | SQLite |
| Remote access | SSH, Paramiko |
| Monitoring | Prometheus |
| Metrics exporter | Prometheus node_exporter |
| Dashboards | Grafana |
| Containers | Docker, Docker Compose |
| Operating system | Ubuntu Linux |
| Version control | Git, GitHub |

## 5. Architecture

```text
                 User / Administrator
                          |
                          v
                 Fleet Manager UI
                    Flask :5000
                          |
              +-----------+-----------+
              |           |           |
              v           v           v
           SQLite      SSH/Paramiko  targets.json
              |           |           |
              |      +----+----+      v
              |      v    v    v  Prometheus :9090
              |    node1 node2 node3      |
              |      |    |    |          v
              |      +----+----+       Grafana :3000
              |           |
              |     node_exporter :9100
              |           |
              +-----------+
```

Prometheus discovers monitored nodes from `prometheus/targets.json`.
The Fleet Manager regenerates this file from registered database entries.
Prometheus refreshes file-based service discovery every 15 seconds.

Grafana queries Prometheus to display monitoring dashboards.

## 6. Project Structure

```text
distributed-linux-fleet-manager/
├── app.py
├── README.md
├── .gitignore
├── docker-compose.yml
└── prometheus/
    ├── prometheus.yml
    └── targets.json
```

The SQLite database and generated Python files are local runtime files
and are excluded from Git.

## 7. Prerequisites

- Ubuntu Linux or an equivalent Linux environment.
- Python 3 and pip.
- Docker Engine and Docker Compose.
- Three reachable Linux nodes for the demonstration.
- SSH access configured for the nodes.
- node_exporter installed and running on each monitored node.

The example deployment uses a Fleet Manager running on node1.

## 8. Installation and Setup

### Step 1: Obtain the repository

```bash
git clone https://github.com/asthaawari/distributed-linux-fleet-manager.git
cd distributed-linux-fleet-manager
```

If you already have the repository, navigate to its directory instead.

### Step 2: Install Python dependencies

Create a virtual environment and install the required packages:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install Flask requests paramiko
```

If virtual environment creation fails because the venv package is missing,
install the appropriate Python venv package for your Ubuntu version.

### Step 3: Start Prometheus and Grafana

From the repository root, run:

```bash
docker compose up -d
```

Check the container status:

```bash
docker compose ps
```

### Step 4: Configure SSH access

The current application expects the SSH private key at:

`/home/ubuntu/.ssh/id_ed25519`

Ensure the key exists and its matching public key is authorized on every
registered node. Use appropriate permissions for the private key and
authorized_keys file.

The application uses the Ubuntu account for SSH connections. Adjust the
application configuration if your environment uses a different account
or key location.

Never commit private keys, passwords, or access tokens.

### Step 5: Start the Fleet Manager

Activate the virtual environment if it is not already active:

```bash
source .venv/bin/activate
python app.py
```

The application listens on port 5000.

When starting the application, the database tables are initialized and
the Prometheus targets file is regenerated from the saved registrations.

## 9. Access the Services

Replace the example address with the actual IP address of your Fleet Manager.

| Service | URL |
|---|---|
| Fleet Manager | `http://<FLEET_MANAGER_IP>:5000` |
| Prometheus | `http://<FLEET_MANAGER_IP>:9090` |
| Grafana | `http://<FLEET_MANAGER_IP>:3000` |

Ensure the relevant ports are reachable from your browser.

For Grafana, configure a Prometheus data source using
`http://prometheus:9090` when Grafana is running in the provided
Docker Compose network.

## 10. Node Monitoring Setup

On each monitored Linux node:

1. Install node_exporter using the appropriate package or official release.
2. Ensure it listens on port 9100.
3. Enable and start its service.
4. Ensure the Fleet Manager and Prometheus host can reach that port.

Prometheus uses the `fleet-nodes` job to scrape the registered nodes.

The target file is generated automatically by the application.
A newly cloned repository starts without the original machine's
registered nodes; register the nodes again in that environment.

## 11. Features and Demonstration

### Node registration
Register a node using its name and IP address through the web interface.
Duplicate IP addresses are rejected.

### Availability monitoring
Prometheus uses the `up` metric to determine whether a node exporter
is reachable. The interface displays the node status using Prometheus data.

### Remote commands
The application supports predefined operations such as:

- Hostname
- Disk usage
- System uptime

Commands are selected from an allowlist rather than accepting arbitrary
shell commands from the web form.

### Grafana dashboards
Grafana can visualize CPU usage, memory usage, and node availability
using data collected by Prometheus.

### Suggested demonstration sequence

1. Start the Fleet Manager and monitoring containers.
2. Open the web interface.
3. Register the demonstration nodes.
4. Confirm their targets appear in Prometheus.
5. Run the hostname, disk usage, and uptime commands.
6. Open Grafana and review CPU, memory, and availability panels.
7. Stop node_exporter on one test node and observe its status change.
8. Restart node_exporter and verify that monitoring recovers.

## 12. Security Considerations

- Never commit private SSH keys or authentication tokens.
- Restrict SSH access to trusted accounts and hosts.
- Keep remote commands restricted to the predefined allowlist.
- Validate and restrict node registration to trusted users.
- Do not expose the development application directly to untrusted networks.
- Configure authentication, authorization, network restrictions, and
  appropriate secret management before any production deployment.

The current project is a learning and demonstration prototype, not a
production-hardened fleet management platform.

## 13. Limitations and Future Improvements

- Add authentication and role-based authorization.
- Improve IP address validation and access controls.
- Make SSH key paths and connection settings configurable.
- Add node editing and removal functionality.
- Improve handling of unreachable or unregistered Prometheus targets.
- Add automated tests and structured logging.
- Improve deployment documentation and monitoring alerts.

## 14. Conclusion

The Distributed Linux Fleet Management project demonstrates how Flask,
SQLite, SSH, Prometheus, node_exporter, Docker Compose, and Grafana can
work together to manage and monitor a small fleet of Linux machines
through a centralized interface.

## 15. Repository

GitHub:
https://github.com/asthaawari/distributed-linux-fleet-manager
