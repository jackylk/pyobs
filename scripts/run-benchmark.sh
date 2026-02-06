#!/bin/bash
# Run benchmarks and generate reports
#
# Usage:
#   ./scripts/run-benchmark.sh              # Normal mode
#   ./scripts/run-benchmark.sh --quick      # Quick mode
#   ./scripts/run-benchmark.sh --full       # Full mode
#   ./scripts/run-benchmark.sh --with-obs   # Include OBS tests

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Default options
MODE="normal"
WITH_OBS=""
REPORT_ONLY=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --quick)
            MODE="quick"
            shift
            ;;
        --full)
            MODE="full"
            shift
            ;;
        --with-obs)
            WITH_OBS="--with-obs"
            shift
            ;;
        --report)
            REPORT_ONLY="true"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Load environment variables if .env exists
if [[ -f ".env" ]]; then
    set -a
    source .env
    set +a
fi

# Create perf directory
mkdir -p perf

if [[ -z "$REPORT_ONLY" ]]; then
    echo "Running benchmarks in $MODE mode..."

    # Build pytest options
    PYTEST_OPTS="-v"
    if [[ "$MODE" == "quick" ]]; then
        PYTEST_OPTS="$PYTEST_OPTS --quick"
    elif [[ "$MODE" == "full" ]]; then
        PYTEST_OPTS="$PYTEST_OPTS --full"
    fi

    if [[ -n "$WITH_OBS" ]]; then
        PYTEST_OPTS="$PYTEST_OPTS --with-obs"
    fi

    # Run benchmarks
    python -m pytest tests/benchmark/ $PYTEST_OPTS
fi

# Generate report
echo "Generating report..."
python scripts/run_benchmark.py --report

echo "Done! Reports saved to perf/"
