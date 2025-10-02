#!/bin/bash

API_BASE="http://localhost:8080/api/sys"

usage() {
  echo "Usage: $0 [status|threads|start|stop]"
  echo "  status  - get system and process status (formatted table)"
  echo "  threads - get active thread info (summary table)"
  echo "  start   - start memory profiling"
  echo "  stop    - stop memory profiling, download .bin, and generate reports"
}

if [ $# -ne 1 ]; then
  usage
  exit 1
fi

ACTION=$1

if ! command -v curl &> /dev/null; then
  echo "Error: curl is required"
  exit 1
fi

if ! command -v jq &> /dev/null; then
  echo "Warning: jq not found, output will not be formatted"
fi

print_status_table() {
  if ! command -v jq &> /dev/null; then
    cat
    return
  fi

  local json=$1

  echo -e "\n=== SYSTEM STATUS ==="
  echo "$json" | jq -r '
    .system |
    [
      "CPU (%)", (.cpu_percent|tostring),
      "Memory (%)", (.memory_percent|tostring),
      "Net Sent (MB)", (.net_io_sent_mb|tostring),
      "Net Recv (MB)", (.net_io_recv_mb|tostring)
    ]
    | .[]' | awk 'NR%2{printf "%-15s: ", $0;next;}1'

  echo -e "\n=== PROCESS STATUS ==="
  echo "$json" | jq -r '
    .process |
    [
      "PID", (.pid|tostring),
      "CPU (%)", (.cpu_percent|tostring),
      "User CPU Time (s)", (.user_cpu_time|tostring),
      "System CPU Time (s)", (.system_cpu_time|tostring),
      "RSS Mem (MB)", (.memory_rss_mb|tostring),
      "VMS Mem (MB)", (.memory_vms_mb|tostring),
      "Shared Mem (MB)", (.memory_shared_mb|tostring),
      "Threads", (.num_threads|tostring),
      "IO Read (MB)", (.io_read_mb|tostring),
      "IO Write (MB)", (.io_write_mb|tostring)
    ]
    | .[]' | awk 'NR%2{printf "%-20s: ", $0;next;}1'
  echo
}

print_threads_table() {
  if ! command -v jq &> /dev/null; then
    cat
    return
  fi

  local json=$1

  echo -e "\n=== THREADS SUMMARY ==="
  echo "Thread ID   Name              Alive"
  echo "$json" | jq -r '.[] | [.thread_id, .name, (.is_alive | tostring)] | @tsv' | column -t -s $'\t'
  echo
}

case "$ACTION" in
  status)
    echo "Fetching system and process status..."
    RESPONSE=$(curl -s "$API_BASE/status")
    print_status_table "$RESPONSE"
    ;;

  threads)
    echo "Fetching active threads info..."
    RESPONSE=$(curl -s "$API_BASE/threads")
    print_threads_table "$RESPONSE"
    ;;

  start)
    echo "Starting memory profiling..."
    curl -s -X POST "$API_BASE/profiler/memory/start" | jq .
    ;;


stop)
  echo "Stopping memory profiling and downloading profile data..."
  OUTPUT_BIN="memray_profile_$(date +%Y%m%d_%H%M%S).bin"

  STATUS_CODE=$(curl -s -w "%{http_code}" -X POST "$API_BASE/profiler/memory/stop" --output "$OUTPUT_BIN")

  if [ "$STATUS_CODE" -ne 200 ] || [ ! -s "$OUTPUT_BIN" ]; then
    echo "Error: Failed to download profiling data (HTTP status: $STATUS_CODE)."
    if [ -f "$OUTPUT_BIN" ]; then
        echo "Server response:"
        cat "$OUTPUT_BIN"
        rm "$OUTPUT_BIN"
    fi
    exit 2
  fi

  echo "Profile data saved to $OUTPUT_BIN"

  if ! command -v memray &> /dev/null; then
    echo "memray CLI not found. Please install memray to generate HTML or summary."
    exit 3
  fi

  OUTPUT_HTML="${OUTPUT_BIN%.bin}.html"
  echo "Generating flamegraph HTML report..."
  memray flamegraph "$OUTPUT_BIN" -o "$OUTPUT_HTML"

  if [ -f "$OUTPUT_HTML" ]; then
    echo "Flamegraph HTML generated: $OUTPUT_HTML"
  else
    echo "Failed to generate flamegraph HTML."
    exit 4
  fi

  echo -e "\n=== Memray Allocation Table (Top 20) ==="
  echo "Note: If sorting is unsupported, full default view will be shown."

  echo -e "\n=== Memray Allocation Table (Top 20 by Own Memory) ==="
  echo "Generating terminal view..."

  echo -e "\n=== Memray Allocation Table (Top 20 by Own Memory) ==="
  echo "Generating terminal view..."

  echo -e "\n=== Memray Allocation Table (Top 20 by Own Memory) ==="
  echo "Generating terminal view..."

  echo -e "\n=== Memray Allocation Table (Top 20 by Own Memory) ==="
  echo "Generating terminal view..."

  table_output=$(memray table --text --sort-by=own_memory "$OUTPUT_BIN" 2>/dev/null | head -n 25)
  if [ -n "$table_output" ]; then
    echo "$table_output"
    echo "Table rendered successfully."
  else
    echo "Fallback: Generating HTML version..."
    OUTPUT_TABLE_HTML="memray-table-${OUTPUT_BIN%.bin}.html"
    memray table "$OUTPUT_BIN" -o "$OUTPUT_TABLE_HTML"
    echo "Wrote $OUTPUT_TABLE_HTML"
  fi

  if command -v open &> /dev/null; then
    open "$OUTPUT_TABLE_HTML"
  elif command -v xdg-open &> /dev/null; then  #
    xdg-open "$OUTPUT_TABLE_HTML" &> /dev/null &
  fi

  ;;
esac