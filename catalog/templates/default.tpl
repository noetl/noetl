{
  "apiVersion": "noetl.io/v1",
  "kind": "Template",
  "id": "/catalog/templates/default",
"playbookId": {{ playbookId }},
  "environment": {{ environment | default({}) | tojson }},
  "variables": {{ variables | default({}) | tojson }},
  "steps": [
    {% for step in steps %}
    {
      "step": "{{ step.step }}",
      "tasks": [
        {% for task in step.tasks %}
        "{{ task }}"
        {% if not loop.last %},{% endif %}
        {% endfor %}
      ]
    }
    {% if not loop.last %},{% endif %}
    {% endfor %}
  ],

  "tasks": [
    {% for task in tasks %}
    {
      "task": "{{ task.task }}",
      "parallel": "{{ task.parallel | default('false') }}",
      {% if task.retry is defined %}
      "retry": "{{ task.retry | default(0) }}",
      {% endif %}
      "actions": [
        {% for action in task.actions %}
        {
          "action": "{{ action.action }}",
          "method": "{{ action.method }}",
          "endpoint": "{{ action.endpoint | default(variables.baseUrl ~ '/cleansing/process') }}",
            {% if action.loop %}
            "loop": {
                {% if action.loop.items %}
                "items": {{ action.loop.items | dict2list | tojson }},
                {% else %}
                "items": {{ action.loop | dict2list | tojson }},
                {% endif %}
                "iterator": "{{ action.loop.iterator | default('item') }}"
            },
            {% endif %}
          "params": {
            {% for key, value in action.params.items() %}
            "{{ key }}": "{{ value | default('') }}"
            {% if not loop.last %},{% endif %}
            {% endfor %}
          }
        }
        {% if not loop.last %},{% endif %}
        {% endfor %}
      ]
    }
    {% if not loop.last %},{% endif %}
    {% endfor %}
  ]
}
