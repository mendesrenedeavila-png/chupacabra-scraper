#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/scraper/.venv"
REQUIREMENTS="$SCRIPT_DIR/scraper/requirements.txt"

echo "=== Chupacabra Scraper ==="
echo ""

# Check python3
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] python3 not found. Please install Python 3.10+."
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "[OK] Python $PYTHON_VERSION found."

# Create virtual environment
if [ ! -d "$VENV_DIR" ]; then
    echo "[INFO] Creating virtual environment at scraper/.venv ..."
    python3 -m venv "$VENV_DIR"
    echo "[OK] Virtual environment created."
else
    echo "[INFO] Virtual environment already exists, skipping creation."
fi

# Activate and install dependencies
echo "[INFO] Installing dependencies..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$REQUIREMENTS"
echo "[OK] Dependencies installed."

echo ""
echo "=== Setup complete! ==="
echo ""
echo "To run the scraper:"
echo "  cd scraper"
echo "  ../.venv/bin/python scrape.py"
echo ""
echo "Or using the venv directly:"
echo "  source scraper/.venv/bin/activate"
echo "  cd scraper && python scrape.py"
