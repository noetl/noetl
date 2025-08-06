#!/usr/bin/env python3

def test_final_parsing():
    """Test the exact same content and logic used in the React component"""
    
    # Exact same content as in the React component
    test_content = """apiVersion: noetl.io/v1
kind: Playbook
name: weather
description: "Simple weather data workflow"

workflow:
  - step: start
    desc: "Start weather workflow"
  - step: fetch_weather
    desc: "Fetch weather data for the city"
    type: workbook
  - step: report_warm
    desc: "Report warm weather"
    type: python
  - step: report_cold
    desc: "Report cold weather"  
    type: python
  - step: end
    desc: "End of workflow\""""

    print("🔍 PARSING PLAYBOOK CONTENT")
    print("📏 Content length:", len(test_content))
    print("📖 Content preview (first 500 chars):")
    print(test_content[:500])
    
    lines = test_content.split('\n')
    print("📝 Total lines:", len(lines))
    
    tasks = []
    current_task = {}
    in_workflow_section = False
    task_index = 0
    workflow_indent = 0
    in_nested_logic = False
    nested_level = 0

    for i, line in enumerate(lines):
        trimmed = line.strip()
        indent = len(line) - len(line.lstrip())
        
        # Debug key lines
        if trimmed and ('workflow' in trimmed or 'step' in trimmed or 'desc' in trimmed or 'type' in trimmed):
            print(f"📋 Line {i}: [indent:{indent}] \"{trimmed}\"")
        
        # Look for workflow/tasks/steps section
        if (trimmed == 'workflow:' or trimmed.startswith('workflow:') or
            trimmed == 'tasks:' or trimmed.startswith('tasks:') or 
            trimmed == 'steps:' or trimmed.startswith('steps:')):
            in_workflow_section = True
            workflow_indent = indent
            print(f"🎯 Found workflow section at line {i} with indent {workflow_indent}")
            continue

        if in_workflow_section:
            # Check if we've left the workflow section
            if (trimmed and indent <= workflow_indent and not trimmed.startswith('-') and 
                ':' in trimmed and not trimmed.startswith('#')):
                print(f"🚪 Left workflow section at line {i}: {trimmed}")
                break
            
            # Detect nested logic sections (next:, then:, else:, when:)
            import re
            if re.match(r'^(next|then|else|when):', trimmed):
                if not in_nested_logic:
                    in_nested_logic = True
                    nested_level = indent
                    print(f"🔀 Entering nested logic at line {i} level {nested_level}: {trimmed}")
                continue
            
            # If we're in nested logic, check if we're back to main workflow level
            if in_nested_logic and indent == workflow_indent + 2 and trimmed.startswith('- step:'):
                in_nested_logic = False
                print(f"🔙 Exiting nested logic at line {i}")
            
            # Only process main workflow steps (not nested conditional steps)
            if (trimmed.startswith('- step:') and not in_nested_logic and 
                indent == workflow_indent + 2):
                
                # Save previous task if exists
                if current_task.get('name'):
                    tasks.append(current_task.copy())
                    task_index += 1
                    print(f"💾 Saved main task: {current_task['name']}")
                
                # Extract step name
                step_match = re.search(r'step:\s*([^\'\"]+)', trimmed)
                task_name = step_match.group(1).strip() if step_match else f'Step {task_index + 1}'
                
                current_task = {
                    'id': re.sub(r'[^a-zA-Z0-9]', '_', task_name).lower(),
                    'name': task_name,
                    'type': 'default'
                }
                print(f"✨ Started main task: {task_name} [id: {current_task['id']}]")
                
            elif (trimmed.startswith('desc:') and current_task.get('name') and 
                  not in_nested_logic):
                # Update task name with description
                desc_match = re.search(r'desc:\s*[\'\"](.*?)[\'\"]|desc:\s*(.+)', trimmed)
                if desc_match:
                    description = (desc_match.group(1) or desc_match.group(2) or '').strip()
                    description = description.strip('\'"')
                    
                    # Use description as display name, keep original name as ID
                    original_name = current_task['name']
                    current_task['name'] = description
                    if (not current_task.get('id') or 
                        current_task['id'] == re.sub(r'[^a-zA-Z0-9]', '_', original_name).lower()):
                        current_task['id'] = re.sub(r'[^a-zA-Z0-9]', '_', original_name).lower()
                    print(f"📝 Updated task name to description: {description}")
                
            elif (trimmed.startswith('type:') and current_task.get('name') and 
                  not in_nested_logic):
                # Extract task type
                type_match = re.search(r'type:\s*[\'\"](.*?)[\'\"]|type:\s*([^\'\"]+)', trimmed)
                if type_match:
                    current_task['type'] = (type_match.group(1) or type_match.group(2) or '').strip()
                    print(f"🏷️ Set task type: {current_task['type']}")
            
            # Reset nested logic flag if we're back to a lower indentation
            if in_nested_logic and indent <= nested_level:
                in_nested_logic = False
                print(f"🔄 Exited nested logic due to indentation change at line {i}")

    # Add the last task
    if current_task.get('name'):
        tasks.append(current_task)
        print(f"💾 Saved final task: {current_task['name']}")

    print("🎉 PARSING COMPLETE")
    print(f"📊 Total main workflow tasks found: {len(tasks)}")
    if len(tasks) > 0:
        print("📋 Task list:")
        for i, task in enumerate(tasks):
            print(f"  {i + 1}. {task['name']} ({task['type']}) [id: {task['id']}]")
    else:
        print("❌ NO TASKS FOUND!")
    
    return tasks

if __name__ == "__main__":
    test_final_parsing()
