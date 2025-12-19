# Iterator (loop) step

Repeat a task for each item in a collection and aggregate results.

What it does
- Iterates over a list (`collection`), binding each element as a named variable.
- Runs the nested `task` per item and collects outputs.
- Provides per-item and aggregated save options.

Required keys
- loop: block with iterator configuration
  - collection: list value to iterate
  - element: variable name bound to the current item
  - mode: sequential|async (optional, default sequential)

Control options
- mode: sequential (default) or async
- concurrency: max parallel tasks when mode=async
- where: expression to filter items (truthy keeps the item)
- order_by: expression to sort items before iteration
- limit: cap number of items processed
- chunk: group size for batched processing (engine-dependent)

Context variables
- `{{ element }}`: current item (e.g., `city`)
- `_loop.index` (0-based), `_loop.count` (1-based), `_loop.size` (total)
- `this.data` inside the task: the current step's output
- `this.result`: list of collected per-item results
- `this.result_index`: list of indices for which results exist
- Guards: `this is defined and this.data is defined` when saving per-item outputs

Saving
- Inside task: per-item save of the step output (e.g., upserting a row)
- On the iterator step: aggregated save of `this.result`

Usage patterns (fragments)
- Async HTTP fan-out with guarded Postgres upsert
  ```yaml
  - step: http_loop
    tool: http
    loop:
      element: city
      collection: "{{ workload.cities }}"
      mode: async
    endpoint: "{{ workload.base_url }}/forecast"
    data:
      latitude: "{{ city.lat }}"
      longitude: "{{ city.lon }}"
      hourly: temperature_2m
      forecast_days: 1
    sink:
      data:
        id: "{{ execution_id }}:{{ city.name }}:{{ http_loop.result_index }}"
        execution_id: "{{ execution_id }}"
        iter_index: "{{ http_loop.result_index }}"
        city: "{{ city.name }}"
        payload: "{{ (this.data | tojson) if this is defined and this.data is defined else '' }}"
      tool: postgres
      auth: pg_local
      table: public.weather_http_raw
      mode: upsert
      key: id
  ```

- Aggregate results for later steps
  ```yaml
  - step: http_loop
    tool: http
    loop:
      element: it
      collection: "{{ http_search.result.items }}"
    url: "{{ it.url }}"
    method: GET
    sink:
      - name: content
        data: "{{ this.data }}"
  
  - step: use_aggregated
    tool: python
    args:
      pages: "{{ http_loop.result }}"
  ```

Notes
- When mode=async, ensure external services and rate limits can handle concurrency.
- Use `order_by` to stabilize processing order if needed for deterministic ids.
