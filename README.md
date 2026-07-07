# DVM Management CLI - Digital Repeater System Management Tools

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

## Overview

DVM Management CLI provides unified management tools for the DVM FNE with a Cisco IOS-like command-line interface, and a browser-based web UI.

Run directly without pip install. See [Quick Start](#quick-start) below.

## Features

- **Cisco IOS-style CLI**: Familiar command structure with tab completion, command history, and hierarchical modes
- **Web UI**: Browser-based management interface built on FastAPI and HTMX with PAM authentication
- **Unified Operations**: Single codebase for all management operations
- **REST API Integration**: Direct communication with dvmhost/fne services
- **Radio Operations**: RID inhibit/uninhibit, paging, and status checks
- **Log Management**: System and public log viewing with filtering
- **Talkgroup Management**: System and public talkgroup configuration
- **No Installation Required**: Run directly with `./run` or install as package

## Quick Start

```bash
cd dvm_mgmt

# Install dependencies (one-time)
./install.sh

# Run directly
./run            # Auto-detect best mode
```

## Usage

### CLI Mode (Cisco IOS-style)

```bash
run --mode cli
```

Example commands:
```
dvmmgmt> enable
dvmmgmt# show logs system
dvmmgmt# show radio status
dvmmgmt# radio inhibit 1234567
dvmmgmt# reload service fne
```

### Web UI Mode

```bash
# Start on default port 8080, bound to all interfaces
run --mode web

# Custom host and port
run --mode web --web-host 127.0.0.1 --web-port 9090

# Use a custom config file
run --mode web --config /opt/console.conf
```

Open `http://<host>:8080` in a browser. Log in with a local Linux system account
(authentication is handled via PAM).

#### Web UI Pages

| Path | Description |
|---|---|
| `/` | Dashboard — system overview |
| `/peers` | Peer configuration |
| `/connected-peers` | Live connected peer status |
| `/system-watch` | Live system watch peer status tiles |
| `/edit-peers` | Edit peer entries |
| `/talkgroups` | Talkgroup configuration |
| `/radio-ids` | Configured radio ID ACL viewer |
| `/radio` | Radio operations (RID inhibit/uninhibit, paging, status) |
| `/services` | Service control (start, stop, reload) |
| `/logs` | System and public log viewer |
| `/console` | Live CLI terminal via WebSocket |

#### Web UI Environment Variables

| Variable | Default | Description |
|---|---|---|
| `WEB_SESSION_SECRET` | auto-derived | Session signing key (≥ 32 characters recommended) |
| `WEB_ROOT_PATH` | *(empty)* | URL prefix when hosted behind a reverse proxy (e.g. `/dvmmgmt`) |
| `WEB_PAM_SERVICE` | `login` | PAM service name used for authentication |
| `WEB_SECURE_COOKIE` | `0` | Set to `1` to mark session cookies as HTTPS-only |

Sessions expire after 12 hours of inactivity.

### Quick Launcher

```bash
# Auto-detect best mode (TUI if terminal supports it, CLI otherwise)
run

# Force specific mode
run --mode cli
run --mode web
```

## Configuration

- `/opt/console.conf` - Main console configuration (override with `--config`)
- `SYSTEM_WATCH_WEBSOCKET_URL` in `/opt/console.conf` - Upstream websocket endpoint consumed by the System Watch page
- `SYSTEM_WATCH_ENABLED` in `/opt/console.conf` - Set to `0` to disable the System Watch page and websocket endpoint

### Federation (Single Pane of Glass)

Federation keeps the browser connected to the local web/API instance only. When a remote target is selected,
the local server proxies `/api/*`, `/stream/*`, and browser console websocket traffic to the selected remote node.

Add these keys in `/opt/console.conf`:

- `FEDERATION_ENABLED=1`
- `FEDERATION_NODE_ID="local"`
- `FEDERATION_SHARED_SECRET="<long-random-secret>"`
- `FEDERATION_TIMEOUT_SEC=8`
- `FEDERATION_AUTH_WINDOW_SEC=30`
- `FEDERATION_TLS_VERIFY=1`

Define remote targets using indexed blocks:

- `FEDERATION_NODE_1_ID="site-a"`
- `FEDERATION_NODE_1_NAME="Site A"`
- `FEDERATION_NODE_1_URL="https://10.0.1.10:8080"`
- `FEDERATION_NODE_1_ENABLED=1`

Notes:

- Federation server-to-server authentication uses a single global shared secret with signed request headers.
- In federated mode, mutating actions are intentionally limited to radio commands, service management, and backup operations.
- Navigation visibility (full vs subprime pages) follows the selected target deployment type.

## Architecture

```
dvm_mgmt/
├── core/           # Core functionality (API client, config, process mgmt)
├── cli/            # Cisco IOS-style CLI implementation
├── web/            # FastAPI + HTMX web interface
│   ├── app.py      # Application factory, routes, PAM auth
│   ├── routes/     # HTMX API endpoints and streaming
│   ├── templates/  # Jinja2 HTML templates
│   └── static/     # CSS, JS, and other static assets
├── operations/     # Business logic (profiles, RIDs, TGs, logs)
└── utils/          # Utilities (network, formatting, shell)
```

## License

This project is licensed under the GPLv2 License - see the [LICENSE](LICENSE) file for details. Use of this project is intended, for amateur and/or educational use ONLY. Any other use is at the risk of user and all commercial purposes is strictly discouraged.

**THIS SOFTWARE MUST NEVER BE USED IN PUBLIC SAFETY OR LIFE SAFETY CRITICAL APPLICATIONS! This software project is provided solely for personal, non-commercial, hobbyist use; any commercial, professional, governmental, or other non-hobbyist use is strictly discouraged, fully unsupported and expressly disclaimed by the authors.**

By using this software, you agree to indemnify, defend, and hold harmless the authors, contributors, and affiliated  parties from and against any and all claims, liabilities, damages, losses, or expenses (including reasonable  attorneys’ fees) arising out of or relating to any unlawful, unauthorized, or improper use of the software.
