#!/usr/bin/env python3

import os
import sys
import json

# Add the current directory to Python path
sys.path.insert(0, '/Users/ndrpt/noetl/noetl')

from noetl.server import CatalogService

def test_playbook_content():
    print("Testing playbook content retrieval...")
    
    try:
        catalog_service = CatalogService()
        
        # Try to get the weather example playbook
        playbook_id = "weather_example"
        print(f"\nTrying to fetch playbook: {playbook_id}")
        
        # Get latest version
        try:
            latest_version = catalog_service.get_latest_version(playbook_id)
            print(f"Latest version: {latest_version}")
        except Exception as e:
            print(f"Error getting latest version: {e}")
            return
            
        # Fetch the entry
        try:
            entry = catalog_service.fetch_entry(playbook_id, latest_version)
            if entry:
                content = entry.get('content', '')
                print(f"\nContent found: {len(content)} characters")
                print(f"Content preview (first 500 chars):")
                print("-" * 50)
                print(content[:500])
                print("-" * 50)
                
                # Test our parsing logic
                print(f"\nTesting parsing logic:")
                test_parse_content(content)
            else:
                print("No entry found")
        except Exception as e:
            print(f"Error fetching entry: {e}")
            
    except Exception as e:
        print(f"General error: {e}")

def test_parse_content(content):
    """Test the parsing logic similar to what's in FlowVisualization.tsx"""
    print("=== PARSING PLAYBOOK CONTENT ===")
    print(f"Content length: {len(content)}")
    
    lines = content.split('\n')
    print(f"Total lines: {len(lines)}")
    
    tasks = []
    current_task = {}
    in_section = False
    task_index = 0
    indent_level = 0
    
    for i, line in enumerate(lines):
        trimmed = line.strip()
        leading_spaces = len(line) - len(line.lstrip())
        
        # Look for workflow/tasks/steps section
        if (trimmed == 'workflow:' or trimmed.startswith('workflow:') or
            trimmed == 'tasks:' or trimmed.startswith('tasks:') or 
            trimmed == 'steps:' or trimmed.startswith('steps:')):
            in_section = True
            indent_level = leading_spaces
            print(f"✓ Found section at line {i}: '{trimmed}' with indent level {indent_level}")
            continue
            
        if in_section:
            # Check if we've left the section
            if (trimmed and leading_spaces <= indent_level and 
                not trimmed.startswith('-') and not trimmed.endswith(':') and 
                not trimmed.startswith('#')):
                print(f"Left section at line {i}: '{trimmed}'")
                break
                
            # Start of a new task/step
            if (trimmed.startswith('- step:') or 
                trimmed.startswith('- name:') or 
                trimmed.startswith('-step:') or
                trimmed.startswith('-name:') or
                trimmed.startswith('- ') or
                (trimmed.startswith('-') and ('step:' in trimmed or 'name:' in trimmed))):
                
                # Save previous task
                if current_task.get('name'):
                    current_task['id'] = current_task.get('id', f'task-{task_index + 1}')
                    tasks.append(current_task.copy())
                    task_index += 1
                    print(f"✓ Saved task: {current_task['name']}")
                
                # Extract task name
                task_name = ''
                task_type = 'default'
                
                if 'step:' in trimmed:
                    import re
                    step_match = re.search(r'step:\s*([^\'\"]+)', trimmed)
                    task_name = step_match.group(1).strip() if step_match else ''
                elif 'name:' in trimmed:
                    import re
                    name_match = re.search(r'name:\s*[\'\"](.*?)[\'\"]|name:\s*([^\'\"]+)', trimmed)
                    task_name = (name_match.group(1) or name_match.group(2) or '').strip() if name_match else ''
                elif trimmed.startswith('- ') and ':' not in trimmed:
                    task_name = trimmed[2:].strip()
                
                if not task_name:
                    task_name = f'Task {task_index + 1}'
                
                current_task = {
                    'id': f'task-{task_index + 1}',
                    'name': task_name,
                    'type': task_type
                }
                print(f"✓ Started new task: {task_name}")
            
            elif trimmed.startswith('type:') or trimmed.startswith('action:'):
                # Extract task type
                import re
                type_match = re.search(r'(?:type|action):\s*[\'\"](.*?)[\'\"]|(?:type|action):\s*([^\'\"]+)', trimmed)
                if type_match and current_task:
                    current_task['type'] = (type_match.group(1) or type_match.group(2) or '').strip()
                    print(f"✓ Set task type: {current_task['type']}")
    
    # Add the last task
    if current_task.get('name'):
        current_task['id'] = current_task.get('id', f'task-{task_index + 1}')
        tasks.append(current_task)
        print(f"✓ Saved final task: {current_task['name']}")
    
    print("=== PARSING COMPLETE ===")
    print(f"Total tasks found: {len(tasks)}")
    for task in tasks:
        print(f"  - {task['name']} ({task['type']})")
    
    return tasks

if __name__ == "__main__":
    test_playbook_content()
