# DVM Management CLI Installation

## Prerequisites

- Python 3.8 or later
- pip3 (Python package installer) - for installing dependencies
- Access to /opt/dvm binaries (tged, etc)

## Installation Methods

The DVM Management CLI can be run directly without installing as a package. This is the quickest way to get started.

#### Step 1: Install Python Dependencies

```bash
cd dvm_mgmt
pip3 install cmd2 textual pydantic psutil rich PyYAML requests fastapi==0.92.0 uvicorn==0.17.6 python-multipart python-pam itsdangerous==2.1.2 jinja2 aiofiles==23.1.0 --break-system-packages
```

Or let the run script handle dependencies:

```bash
cd dvm_mgmt
./install.sh
```

#### Step 2: Run the Tools

```bash
# Option A: Use executable wrappers
./run           # Auto-detect best interface

# Option B: Use Python module syntax
python3 -m dvm_mgmt
python3 -m dvm_mgmt --mode cli
python3 -m dvm_mgmt --mode tui
```

#### Step 3 (Optional): Create Symlinks for System-Wide Access

```bash
sudo ln -s "$(pwd)/run" /usr/local/bin/dvmmgmt

# Now you can run from anywhere
dvmmgmt
```

## Configuration

The tool reads configuration from `/opt/console.conf` (bash-style) by default.

A full example configuration is provided in [config.example.conf](config.example.conf).

Example `/opt/console.conf`:
```bash
# API Configuration
SYSTEM_PORT=9290
SYSTEM_ACL="RPT1234"

# File Paths
SYSTEM_TGID_ACL_FILE="/opt/dvm/talkgroup_rules.yml"

# Log Configuration (for call record querying)
LOG_FILE="/var/log/syslog"
LOG_PREFIX_SYSTEM="SKYN-FNE1-CR1"
```

## Usage

### Running Without Installation

If you're using the direct execution method:

```bash
cd /path/to/dvm_mgmt

# Auto-detect best interface
./run
```

### CLI Examples

```bash
# Start CLI
run --mode cli

# In CLI:
dvm> enable
dvm# show processes
dvm# show logs system --lines 100
dvm# radio inhibit 1234567
dvm# reload rids
dvm# quit
```

## Web UI Behind Nginx (Reverse Proxy)

Use this pattern if you want Nginx to handle TLS and forward traffic to the DVM Management web app.

### 1) Run DVM Management Web on localhost

Bind the app to loopback so it is only reachable from Nginx:

```bash
cd dvm_mgmt
run --mode web --web-host 127.0.0.1 --web-port 8996
```

If you run under systemd, keep the same host and port values in the unit file.

### 2) Nginx site configuration

Create a site config such as `/etc/nginx/sites-available/web.conf`:

```nginx
server {
	listen 80;
	server_name dvmmgmt.example.com;
	return 301 https://$host$request_uri;
}

server {
	listen 443 ssl http2;
	server_name dvmmgmt.example.com;

	ssl_certificate     /etc/letsencrypt/live/dvmmgmt.example.com/fullchain.pem;
	ssl_certificate_key /etc/letsencrypt/live/dvmmgmt.example.com/privkey.pem;

	client_max_body_size 20m;

	# WebSocket endpoint used by the in-browser CLI console.
	# This location must pass Upgrade/Connection headers.
	location /ws/console {
		proxy_pass http://127.0.0.1:8996/ws/console;
		proxy_http_version 1.1;

		proxy_set_header Upgrade $http_upgrade;
		proxy_set_header Connection "upgrade";

		proxy_set_header Host $host;
		proxy_set_header X-Real-IP $remote_addr;
		proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
		proxy_set_header X-Forwarded-Proto $scheme;

		proxy_buffering off;
		proxy_read_timeout 3600;
	}

	# WebSocket endpoint used by the System Watch page.
	# This location must pass Upgrade/Connection headers.
	location /ws/system-watch {
		proxy_pass http://127.0.0.1:8996/ws/system-watch;
		proxy_http_version 1.1;

		proxy_set_header Upgrade $http_upgrade;
		proxy_set_header Connection "upgrade";

		proxy_set_header Host $host;
		proxy_set_header X-Real-IP $remote_addr;
		proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
		proxy_set_header X-Forwarded-Proto $scheme;

		proxy_buffering off;
		proxy_read_timeout 3600;
	}

	location / {
		proxy_pass http://127.0.0.1:8996;
		proxy_http_version 1.1;

		proxy_set_header Host $host;
		proxy_set_header X-Real-IP $remote_addr;
		proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
		proxy_set_header X-Forwarded-Proto $scheme;

		# Required for SSE endpoints under /stream/*
		proxy_buffering off;
		proxy_read_timeout 3600;
	}
}
```

#### Nginx example for non-root URL (`/dvmmgmt/`)

If you want to serve DVM Management under a subpath instead of site root, configure both Nginx and DVM Management root path.

Set environment for the DVM Management web process:

```bash
export WEB_ROOT_PATH=/dvmmgmt
export WEB_SECURE_COOKIE=1
```

Nginx snippet:

```nginx
server {
	listen 443 ssl http2;
	server_name dvmmgmt.example.com;

	ssl_certificate     /etc/letsencrypt/live/dvmmgmt.example.com/fullchain.pem;
	ssl_certificate_key /etc/letsencrypt/live/dvmmgmt.example.com/privkey.pem;

	# Normalize /dvmmgmt to /dvmmgmt/
	location = /dvmmgmt {
		return 301 /dvmmgmt/;
	}

	# Forward /dvmmgmt/* to DVM Management web app
	location /dvmmgmt/ {
		proxy_pass http://127.0.0.1:8996/;
		proxy_http_version 1.1;

		proxy_set_header Host $host;
		proxy_set_header X-Real-IP $remote_addr;
		proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
		proxy_set_header X-Forwarded-Proto $scheme;
		proxy_set_header X-Forwarded-Prefix /dvmmgmt;

		proxy_buffering off;
		proxy_read_timeout 3600;
	}

	# WebSocket endpoint for browser console when hosted under /dvmmgmt
	location /dvmmgmt/ws/console {
		proxy_pass http://127.0.0.1:8996/ws/console;
		proxy_http_version 1.1;

		proxy_set_header Upgrade $http_upgrade;
		proxy_set_header Connection "upgrade";

		proxy_set_header Host $host;
		proxy_set_header X-Real-IP $remote_addr;
		proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
		proxy_set_header X-Forwarded-Proto $scheme;
		proxy_set_header X-Forwarded-Prefix /dvmmgmt;

		proxy_buffering off;
		proxy_read_timeout 3600;
	}

	# WebSocket endpoint for System Watch when hosted under /dvmmgmt
	location /dvmmgmt/ws/system-watch {
		proxy_pass http://127.0.0.1:8996/ws/system-watch;
		proxy_http_version 1.1;

		proxy_set_header Upgrade $http_upgrade;
		proxy_set_header Connection "upgrade";

		proxy_set_header Host $host;
		proxy_set_header X-Real-IP $remote_addr;
		proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
		proxy_set_header X-Forwarded-Proto $scheme;
		proxy_set_header X-Forwarded-Prefix /dvmmgmt;

		proxy_buffering off;
		proxy_read_timeout 3600;
	}
}
```

Note: without the `Upgrade` and `Connection "upgrade"` headers above, websocket routes like `/ws/console` and `/ws/system-watch` will fail behind Nginx even if normal page routes work.

If DVM Management web is launched by systemd, add this to the unit file:

```ini
Environment=WEB_ROOT_PATH=/dvmmgmt
Environment=WEB_SECURE_COOKIE=1
```

Enable and reload:

```bash
sudo ln -s /etc/nginx/sites-available/web.conf /etc/nginx/sites-enabled/web.conf
sudo nginx -t
sudo systemctl reload nginx
```

### 3) Session cookie setting for TLS

When using HTTPS in front of DVM Management, enable secure cookies:

```bash
export WEB_SECURE_COOKIE=1
```

If DVM Management web is launched by systemd, set this in the unit file:

```ini
Environment=WEB_SECURE_COOKIE=1
```

### 4) PAM service selection (optional)

By default, login auth uses PAM service `login`.

To use a custom PAM stack, set:

```bash
export WEB_PAM_SERVICE=login
```

Then restart the DVM Management web service.

### 5) Recommended hardening

- Keep DVM Management web bound to `127.0.0.1`.
- Only expose Nginx 443 to clients.
- Use valid TLS certificates.
- Keep server time synchronized (TLS/session stability).
- Restrict host firewall to required ports only.

## Troubleshooting

### "Configuration file not found"
Create `/opt/console.conf` with required parameters.

### TUI doesn't display correctly
Ensure terminal supports 256 colors and is at least 80x24 characters.

### Permission denied errors
Ensure your user has access to log files and configuration directories.
