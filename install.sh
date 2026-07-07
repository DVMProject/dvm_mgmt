#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
#/*
#* Digital Voice Modem - Management CLI
#* GPLv2 Open Source. Use is subject to license terms.
#* DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS FILE HEADER.
#*
#*  Copyright (C) 2026 DVMProject Authors
#*
#*/

set -e

echo "═══════════════════════════════════════════════════════════════════════"
echo "  DVM Management - Installation Script (Direct Execution)"
echo "  Copyright (C) 2026 DVMProject Authors"
echo "═══════════════════════════════════════════════════════════════════════"
echo

# Check Python version
echo "Checking Python version..."
python3 --version || { echo "Error: Python 3 not found"; exit 1; }

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')

if ! python3 -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)"; then
    echo "Error: Python 3.8+ required, found $PYTHON_VERSION"
    exit 1
fi

echo "✓ Python $PYTHON_VERSION detected"
echo

cd "$(dirname "$0")"

echo "Installing dependencies for direct execution..."
pip3 install cmd2==3.1.2 textual pydantic psutil rich PyYAML requests fastapi==0.92.0 uvicorn==0.17.6 uvicorn[standard]==0.17.6 python-multipart python-pam itsdangerous==2.1.2 jinja2 aiofiles==23.1.0 websockets==12.0 --break-system-packages || { 
    echo "Error: Dependency installation failed"; 
    exit 1; 
}
echo "✓ Dependencies installed"

# Make wrapper scripts executable
echo
echo "Making scripts executable..."
chmod +x run
echo "✓ Scripts are now executable"
echo

# Run verification
echo "Running verification checks..."
python3 verify_installation.py

VERIFY_RESULT=$?

echo

if [ $VERIFY_RESULT -eq 0 ]; then
    echo "═══════════════════════════════════════════════════════════════════════"
    echo "  ✓ Installation and verification successful!"
    echo "═══════════════════════════════════════════════════════════════════════"
else
    echo "═══════════════════════════════════════════════════════════════════════"
    echo "  ✗ Verification failed - please check errors above"
    echo "═══════════════════════════════════════════════════════════════════════"
    echo
    echo "Common issues:"
    echo "  - Missing dependencies: pip3 install cmd2 textual pydantic psutil rich PyYAML requests fastapi uvicorn python-multipart python3-pam itsdangerous jinja2 aiofiles"
    echo "  - Wrong Python version: need Python 3.8+"
    echo "  - Missing system tools: tged, etc"
    echo
    exit 1
fi
