#!/usr/bin/env bash
# Run JATAYU Core regression test suite

set -e

echo "🧪 Running JATAYU Core v1.0 Permanent Regression Suite..."
export PYTHONPATH=.
python3 -m unittest discover -s tests -p "test_*.py" -v
echo "✅ All regression tests passed!"
