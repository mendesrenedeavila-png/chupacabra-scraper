#!/bin/bash
set -e
rm -rf /home/renem/CHUPACABRA/output
cd /home/renem/CHUPACABRA/scraper
for fmt in md txt html csv pdf; do
  echo "=== $fmt ==="
  .venv/bin/python scrape.py --depth 1 --workers 3 --flat --format "$fmt" --force 2>&1 | grep -E 'Done|Error|error'
done
echo "--- files ---"
find /home/renem/CHUPACABRA/output -type f | sort
