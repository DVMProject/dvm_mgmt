# DVM Management CLI - One-Page Cheat Sheet

## 🚀 Direct Execution (No Installation)

```bash
# ONE-TIME SETUP
cd dvm_mgmt
./install.sh

# RUN IT
./run            # Auto-detect
```

## 💻 Common CLI Commands

```bash
# Start CLI
./run --mode cli

# Basic navigation
dvmmgmt> enable              # Enter privileged mode
dvmmgmt# disable             # Return to user mode

# Show commands
show processes              # Service status
show stats                  # FNE statistics
show logs system            # View system log
show spanning-tree          # Network topology (sorted by peer ID)

# FNE management
fne version                 # FNE version
fne peerlist                # List peers
fne force-update            # Force peer updates
fne reload-rids             # Reload radio IDs
fne reload-tgs              # Reload talkgroups
fne reload-peerlist         # Reload peer list
fne reset-peer 10001        # Reset peer connection

# Radio operations
radio inhibit 1234567       # Inhibit radio
radio uninhibit 1234567     # Uninhibit radio
radio page 1234567 --peer-id 310001     # Page radio
radio check 1234567         # Check status

# Service management
reload rids                 # Reload radio IDs
reload talkgroups          # Reload talkgroups
```

## 📁 File Structure

```
dvm_mgmt/
├── run                 # DVM Management CLI launcher
├── README.md           # 
├── CHEATSHEET.md       # 
├── CLI_COMMAND_REFERENCE.md # 
├── dvm_mgmt/           # Python package
│   ├── __main__.py     # Entry point
│   ├── core/           # Config, API, process, logs
│   ├── operations/     # RIDs, TGs, profiles, sync
│   ├── cli/            # Cisco CLI implementation
│   ├── web/            # Web UI implementation
└── └── utils/          # Helpers
```

## 📖 Documentation

| File | Purpose |
|------|---------|
| **README.md** | Project overview |
| **CHEATSHEET.md** | CLI cheetsheet |
| **CLI_COMMAND_REFERENCE.md** | CLI command reference |

## ⚡ Quick Examples

### Check System Status
```bash
./run --mode cli
> enable
# show processes
# show stats
```

### Inhibit a Radio
```bash
./run --mode cli
> enable
# radio inhibit 1234567
```

### View Logs
```bash
./run --mode cli
> enable
# show logs system --lines 50 --filter ERROR
```

### Restart Service
```bash
./run --mode cli
> enable
# reload service fne
```

---

**Copyright (C) 2026 DVMProject Authors**
