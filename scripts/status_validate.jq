def lcase: ascii_downcase;
# Identify events representing errors or failures
# (status field containing 'error' or 'failed' OR explicit action_error event_type)
def errEvt: (select((.event_type=="action_error") or (((.status|tostring)|lcase)|test("error|failed"))));

# Prefer new inline-playbook loop result (city_loop); fallback to legacy run_city_process_loop
# Each is the last action_completed for that node

def parse_or: (try (.output_result | fromjson) catch .);
# Prefer explicit loop_completed marker, fall back to aggregated action_completed for city_loop
def lastCity: (
  .events
  | map(
      select(
        (.node_name=="city_loop") and (
          (.event_type=="loop_completed") or
          (.event_type=="action_completed")
        )
      )
    )
  | last
);

def lastAgg: (.events | map(select(.node_name=="aggregate_alerts_task" and .event_type=="action_completed")) | last);

def lastStats: (.events | map(select(.node_name=="compute_stats" and .event_type=="action_completed")) | last);

# Loop iteration helpers (fallback when aggregated loop result data is absent)
def cityLoopIterations: (.events | map(select(.event_type=="loop_iteration" and .node_name=="city_loop")));
def cityLoopIterationCount: (cityLoopIterations | length);
def cityLoopIterCompletions: (.events | map(select(.event_type=="action_completed" and (.node_id|tostring|test("-iter-")) and .node_name=="city_loop")));
def cityLoopChildExecs: (cityLoopIterCompletions | map(.output_result.data.execution_id) | map(select(. != null)) | unique);
def lastCityHasAggregate: (
  lastCity and (
    (
      (lastCity.event_type=="action_completed") and (
        (
          (lastCity.output_result|type=="object") and (
            (lastCity.output_result.data.count?) or ((lastCity.output_result.data.results?|length) > 0)
          )
        ) or (
          # Compatibility: some generators emit aggregated results as a bare array
          (lastCity.output_result|type=="array") and ((lastCity.output_result|length) > 0)
        )
      )
    ) or (
      (lastCity.event_type=="loop_completed") and (
        (lastCity.result|type=="object") and (
          (lastCity.result.data.count?) or ((lastCity.result.data.results?|length) > 0)
        )
      )
    )
  )
);

"status: " + (.status // "unknown"),
"events: " + ((.events|length)|tostring),
"errors: " + ((.events|map(errEvt)|length)|tostring),
(
  if lastCityHasAggregate then
    (if lastCity.event_type=="loop_completed" then
      "city_loop.count: " + ((lastCity.result.data.count // (lastCity.result.data.results|length) // 0)|tostring)
     else
      # Prefer structured count, fallback to array length when output_result is a bare array
      (if (lastCity.output_result|type=="object") then
        "city_loop.count: " + ((lastCity.output_result.data.count // (lastCity.output_result.data.results|length) // 0)|tostring)
       else
        "city_loop.count: " + ((lastCity.output_result|length)|tostring)
       end)
     end)
  else
    "city_loop.count: " + (cityLoopIterationCount|tostring)
  end
),
(
  if lastCityHasAggregate then
    (if lastCity.event_type=="loop_completed" then
      "city_loop.results_len: " + ((lastCity.result.data.results|length // (lastCity.result.data.count // 0))|tostring)
     else
      # Prefer structured results length, fallback to array length when output_result is a bare array
      (if (lastCity.output_result|type=="object") then
        "city_loop.results_len: " + ((lastCity.output_result.data.results|length // (lastCity.output_result.data.count // 0))|tostring)
       else
        "city_loop.results_len: " + ((lastCity.output_result|length)|tostring)
       end)
     end)
  else
    "city_loop.results_len: " + (cityLoopIterationCount|tostring)
  end
),
"city_loop.iterations: " + (cityLoopIterationCount|tostring),
(if (cityLoopChildExecs|length) > 0 then "city_loop.child_execution_ids: " + (cityLoopChildExecs|tojson) else empty end),
(if (lastCityHasAggregate|not) and (cityLoopIterationCount > 0) then "warning: city_loop has iterations but no aggregated results (fallback applied)" else empty end),
(if lastAgg then "aggregate_alerts: " + ((lastAgg.output_result // {}) | tojson) else empty end),
(if lastStats then "compute_stats: " + ((lastStats.output_result // {}) | tojson) else empty end)
