
# Distributed Linux Fleet Management

## Overview
A system for centrally managing and monitoring multiple Linux machines (nodes) from a Fleet Manager.

## Problem Statement
Managing several Linux machines individually can be time-consuming. This project aims to provide a central interface to register nodes, monitor their availability, and perform approved remote operations.

## Objectives
- Register Linux nodes using their IP address and hostname.
- Establish secure remote access using SSH.
- Monitor node availability using Prometheus.
- Collect system metrics using node_exporter.
- Update Prometheus targets through file-based service discovery.
- Display online/offline status in a central interface.
- Support approved remote commands using an allowlist.

## Planned Architecture
1. The Fleet Manager stores registered node information.
2. SSH provides secure remote access to nodes.
3. node_exporter exposes system metrics.
4. Prometheus collects metrics and monitors node availability.
5. File-based service discovery updates the Prometheus target list.
6. The Fleet Manager interface displays node status.

## Technology Stack
- Operating System: Linux (Ubuntu/Debian)
- Remote Access: SSH
- Monitoring: Prometheus
- Metrics Exporter: node_exporter
- Version Control: Git and GitHub

## Project Status
Currently in the learning and setup phase. Features will be implemented incrementally.

## Security
Private SSH keys and credentials must never be committed to the repository. Remote commands will be restricted to an allowlist.
