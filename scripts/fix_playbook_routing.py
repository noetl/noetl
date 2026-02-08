#!/usr/bin/env python3
"""Fix playbook conditional routing from next: with when to case: pattern."""
import re
import sys

def fix_playbook(filepath):
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Pattern to match the old next: with when conditions
    pattern = r'(  - step: \w+\n.*?tool:.*?\n.*?cmds:.*?\n.*?\n    )next:\n((?:      - when: "{{ workload\.action }} == .*?\n        then:\n          - step: .*?\n        args: {}\n)+)      - step: (\w+)'
    
    def replace_func(match):
        prefix = match.group(1)
        conditions_block = match.group(2)
        fallback_step = match.group(3)
        
        # Convert conditions
        conditions = []
        for line in conditions_block.strip().split('\n'):
            if 'when:' in line:
                # Extract action value
                action_match = re.search(r'== (\w+[-\w]*)', line)
                if action_match:
                    action = action_match.group(1)
                    conditions.append(f'      - when: "{{{{ workload.action == \'{action}\' }}}}"')
            elif 'then:' in line:
                conditions.append(line)
            elif 'step:' in line and 'args' not in line:
                conditions.append(line)
        
        new_block = prefix + 'case:\n' + '\n'.join(conditions) + '\n    next:\n      - step: ' + fallback_step
        return new_block
    
    new_content = re.sub(pattern, replace_func, content, flags=re.DOTALL)
    
    if new_content != content:
        with open(filepath, 'w') as f:
            f.write(new_content)
        return True
    return False

if __name__ == '__main__':
    files = [
        'automation/infrastructure/clickhouse.yaml',
        'automation/infrastructure/qdrant.yaml',
        'automation/infrastructure/monitoring.yaml',
        'automation/infrastructure/gateway.yaml'
    ]
    
    for filepath in files:
        try:
            if fix_playbook(filepath):
                print(f'✓ Fixed {filepath}')
            else:
                print(f'- No changes needed for {filepath}')
        except Exception as e:
            print(f'✗ Error fixing {filepath}: {e}')
