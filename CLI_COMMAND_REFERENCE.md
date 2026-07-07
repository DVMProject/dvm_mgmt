# DVM Management CLI Command Reference

Complete reference for all commands available in the DVM Management CLI.

## Mode System

The CLI uses a two-level mode system similar to Cisco IOS:

- **User Mode** (`dvmmgmt>`) - Basic commands only
- **Privileged Mode** (`dvmmgmt#`) - Full access to all commands

### Mode Commands

```
enable              - Enter privileged mode (required for most commands)
disable             - Exit privileged mode
exit                - Exit CLI
quit                - Alias for exit
```

## Show Commands

Display system information (available in privileged mode):

### System Information

```bash
show version                            # Display software version
show processes                          # Show running DVM processes
show processes --threads                # Show processes with thread information
show processes --workers                # Show processes with worker threads
show processes --all                    # Show all processes (including watchdog/grep)
show stats                              # Display FNE statistics
```

### Logs

```bash
show logs system                        # Show system log
show logs fne                           # Show FNE log

# Log options:
show logs <type> --lines 100            # Show last 100 lines
show logs <type> --colorize             # Colorize log output
```

### Peers

```bash
show peers                              # Show all peers
show peers --system system              # Show system peers only
show peers --system public              # Show public peers only
```

### Network Topology

```bash
show spanning-tree                      # Display network spanning tree topology (sorted by peer ID)
```

## Radio Commands

Radio ID operations (requires privileged mode):

```bash
radio inhibit <RID>                     # Inhibit a radio ID
radio inhibit <RID> --peer-id <ID>      # Inhibit on specific peer
radio inhibit <RID> --system issi       # Inhibit on ISSI system

radio uninhibit <RID>                   # Uninhibit a radio ID
radio uninhibit <RID> --peer-id <ID>    # Uninhibit on specific peer

radio page <RID>                        # Page a radio ID
radio page <RID> --peer-id <ID>         # Page on specific peer

radio check <RID>                       # Check radio ID status
radio check <RID> --peer-id <ID>        # Check on specific peer
```

## FNE Management Commands

FNE-specific system operations (requires privileged mode):

```bash
fne version                             # Display FNE version
fne peerlist                            # List all connected peers
fne peercount                           # Display count of connected peers
fne tgidlist                            # List all configured talkgroups
fne affiliations                        # Show active radio affiliations
fne force-update                        # Force immediate update to all peers
fne reload-tgs                          # Reload talkgroup rules from disk
fne reload-rids                         # Reload radio IDs from disk
fne reload-peerlist                     # Reload authorized peer list from disk
fne reload-crypto                       # Reload cryptographic keys from disk
fne reset-peer <peer-id>                # Reset connection for specific peer
fne rid-commit                          # Save RID ACL changes to disk
fne tgid-commit                         # Save TGID ACL changes to disk
fne peer-commit                         # Save peer ACL changes to disk
```

**Notes:**
- Commands prefixed with `reload-` discard in-memory changes and reload from disk
- Commands prefixed with `-commit` save in-memory changes to disk persistence
- Network topology: use `show spanning-tree` instead

## Reload Commands

Restart services and reload configuration (requires privileged mode):

```bash
reload service fne                      # Restart FNE service

reload rids                             # Reload radio IDs
reload rids --system system             # Reload system RIDs only
reload rids --system issi               # Reload ISSI RIDs only

reload talkgroups                       # Reload talkgroups
reload talkgroups --system system       # Reload system TGs only
```

## Peer Commands

Peer connection management (requires privileged mode):

**Note**: Peer ACL files are CSV format with the following fields:
- `peer_id,password,replica,peer_name,require_key,can_inhibit,call_priority,jitter,max_size,max_wait`

```bash
peer list                               # List all peers

peer add <ID> <password> [options]

# Peer add options:
  --name NAME           Peer name/description
  --replica {0,1}       Replica flag (default: 0)
  --require-key {0,1}   Require encryption key (default: 0)
  --can-inhibit {0,1}   Can inhibit flag (default: 0)

peer remove <ID>                        # Remove peer

peer enable <ID>                        # Enable peer

peer disable <ID>                       # Disable peer

peer edit                               # Edit peers interactively (opens peered/nano/vi)
```

## Examples

### Common Workflows

#### Check System Status

```bash
dvmmgmt> enable
dvmmgmt# show version
dvmmgmt# show processes
dvmmgmt# show stats
dvmmgmt# show network
```

#### Manage Radio IDs

```bash
dvmmgmt# radio inhibit 1234567
dvmmgmt# radio check 1234567
dvmmgmt# radio uninhibit 1234567
```

#### Manage Peers

```bash
dvmmgmt# show peers
dvmmgmt# peer add 1001 MyPassword --name "Site1"
dvmmgmt# peer list
```

## Keyboard Shortcuts

- `Tab` - Command completion
- `?` - Context-sensitive help
- `Ctrl+D` - Exit CLI
- `Ctrl+C` - Interrupt current command
- `Up/Down` - Command history
- `Ctrl+R` - Reverse search history

## Tips

1. Use Tab completion to discover available commands
2. Add `?` after any command to see available options
3. Most commands support `--help` for detailed usage
4. Use `show` commands to verify changes before reloading
5. Create backups before making significant changes
6. Use `--watch` flags for real-time monitoring
7. Combine filters with log commands for targeted troubleshooting

## Command Categories

### Monitoring

- `show processes` - Process status
- `show stats` - FNE statistics  

### Configuration

- `peer add/remove` - Peer management

### Operations

- `reload service` - Service control
- `reload rids/talkgroups` - Config reloads

### Troubleshooting

- `show logs` - Log viewing
- `radio check` - Radio status
