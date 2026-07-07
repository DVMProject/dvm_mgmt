#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#/*
#* Digital Voice Modem - Management CLI
#* GPLv2 Open Source. Use is subject to license terms.
#* DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS FILE HEADER.
#*
#*  Copyright (C) 2026 DVMProject Authors
#*
#*/
"""
Quick verification script for DVM Management CLI installation
"""

import sys
from pathlib import Path

def check_imports():
    """Verify all required modules can be imported."""
    print("Checking module imports...")
    
    modules = [
        ('cmd2', 'CLI framework'),
        ('textual', 'TUI framework'),
        ('rich', 'Rich output'),
        ('pydantic', 'Configuration validation'),
        ('psutil', 'Process management'),
        ('yaml', 'YAML parsing'),
        ('requests', 'HTTP client'),
        ('fastapi', 'API framework'),
        ('uvicorn', 'ASGI server'),
        ('python_multipart', 'Multipart form parsing'),
        ('pam', 'PAM authentication'),
    ]

    all_ok = True
    for module_name, description in modules:
        try:
            __import__(module_name)
            print(f"  ✓ {module_name:15} - {description}")
        except ImportError:
            print(f"  ✗ {module_name:15} - {description} [MISSING]")
            all_ok = False
    
    return all_ok


def check_modules():
    """Verify DVM Management modules can be imported."""
    print("\nChecking DVM Management modules...")
    
    modules = [
        'dvm_mgmt',
        'dvm_mgmt.core.config',
        'dvm_mgmt.core.api_client',
        'dvm_mgmt.core.process_manager',
        'dvm_mgmt.core.log_manager',
        'dvm_mgmt.operations.radio_ids',
        'dvm_mgmt.operations.talkgroups',
        'dvm_mgmt.cli.cisco_cli',
        'dvm_mgmt.tui.app',
    ]
    
    all_ok = True
    for module_name in modules:
        try:
            __import__(module_name)
            short_name = module_name.replace('dvm_mgmt.', '')
            print(f"  ✓ {short_name}")
        except ImportError as e:
            print(f"  ✗ {module_name} [ERROR: {e}]")
            all_ok = False
    
    return all_ok


def check_config():
    """Try loading configuration."""
    print("\nChecking configuration...")
    
    try:
        from dvm_mgmt.core.config import ConsoleConfig
        
        # Try default config
        config = ConsoleConfig()
        print(f"  ✓ Default configuration loaded")
        print(f"    - System Port: {config.system_port}")
        print(f"    - API Host: {config.api_host}")
        
        # Check if /opt/console.conf exists
        config_file = Path('/opt/console.conf')
        if config_file.exists():
            config = ConsoleConfig.load(config_file)
            print(f"  ✓ Loaded /opt/console.conf")
        else:
            print(f"  ⚠ /opt/console.conf not found (will use defaults)")
        
        return True
    
    except Exception as e:
        print(f"  ✗ Configuration error: {e}")
        return False


def check_api_client():
    """Verify API client can be created."""
    print("\nChecking API client...")
    
    try:
        from dvm_mgmt.core.api_client import DVMAPIClient
        from dvm_mgmt.core.config import ConsoleConfig
        
        config = ConsoleConfig()
        client = DVMAPIClient(
            host=config.api_host,
            port=config.system_port,
            password=config.system_acl,
        )
        
        print(f"  ✓ API client created")
        print(f"    - Endpoint: {client.host}:{client.port}")
                
        return True
    
    except Exception as e:
        print(f"  ✗ API client error: {e}")
        return False


def check_managers():
    """Verify operation managers can be created."""
    print("\nChecking operation managers...")
    
    try:
        from dvm_mgmt.core.config import ConsoleConfig
        from dvm_mgmt.operations.radio_ids import RadioIDManager
        from dvm_mgmt.operations.talkgroups import TalkgroupManager
        
        config = ConsoleConfig()
        
        managers = [
            ('RadioIDManager', RadioIDManager(config)),
            ('TalkgroupManager', TalkgroupManager(config)),
        ]
        
        for name, mgr in managers:
            print(f"  ✓ {name} initialized")
        
        return True
    
    except Exception as e:
        print(f"  ✗ Manager initialization error: {e}")
        return False


def print_summary(results):
    """Print summary of checks."""
    print("\n" + "=" * 70)
    print("VERIFICATION SUMMARY")
    print("=" * 70)
    
    all_passed = all(results.values())
    
    for check, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status:8} {check}")
    
    print("=" * 70)
    
    if all_passed:
        print("\n✓ All checks passed! DVM Management CLI is ready to use.")
    else:
        print("\n✗ Some checks failed. Please review the errors above.")
        print("\nTroubleshooting:")
        print("  1. Install dependencies: pip install -e .")
        print("  2. Check Python version: python3 --version (need 3.8+)")
        print("  3. Verify installation: pip show dvm_mgmt")
    
    return all_passed


def main():
    """Run all verification checks."""
    print("=" * 70)
    print("DVM Management - Installation Verification")
    print("=" * 70)
    print()
    
    results = {
        'Dependencies': check_imports(),
        'Modules': check_modules(),
        'Configuration': check_config(),
        'API Client': check_api_client(),
        'Operation Managers': check_managers(),
    }
    
    all_passed = print_summary(results)
    
    return 0 if all_passed else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nVerification interrupted.")
        sys.exit(130)
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
