#!/usr/bin/env python3
"""
Migrate Python tools in playbooks from old DSL (with def main()) to new DSL format.

Old format:
  tool:
    kind: python
    code: |
      def main(arg1, arg2):
        return {"status": "success"}

New format:
  tool:
    kind: python
    auth: {}
    libs: {}
    args:
      arg1: "{{ value1 }}"
      arg2: "{{ value2 }}"
    code: |
      result = {"status": "success"}
"""

import re
import sys
from pathlib import Path
import yaml

def migrate_python_tool(content: str) -> str:
    """Migrate Python tool definitions in playbook YAML content."""
    
    # Pattern to match python tool with def main
    # This matches multi-line tool definitions
    pattern = r'''([ ]+tool:\s*\n(?:[ ]+\w+:.*\n)*?)([ ]+kind:\s*python\s*\n)((?:[ ]+(?!kind:).*\n)*?)([ ]+code:\s*\|\s*\n(?:[ ]+.*\n)*?[ ]+def (?:async )?main\([^)]*\):.*?\n(?:[ ]+.*\n)*?)'''
    
    def replacer(match):
        tool_start = match.group(1)
        kind_line = match.group(2)
        middle_content = match.group(3)
        code_section = match.group(4)
        
        # Extract indentation from kind line
        indent = re.match(r'([ ]+)', kind_line).group(1)
        
        # Check if auth, libs, args already exist in middle_content
        has_auth = 'auth:' in middle_content
        has_libs = 'libs:' in middle_content  
        has_args = 'args:' in middle_content
        
        # Extract code content and transform
        code_match = re.search(r'code:\s*\|\s*\n((?:[ ]+.*\n)*)', code_section)
        if not code_match:
            return match.group(0)  # Return unchanged if can't parse
        
        code_lines = code_match.group(1)
        
        # Remove def main wrapper and transform return to result assignment
        # Handle both sync and async def main
        transformed_code = re.sub(
            r'([ ]*)(?:async )?def main\([^)]*\):\s*\n', 
            '', 
            code_lines
        )
        
        # Dedent code by one level
        code_indent = len(re.match(r'([ ]*)', transformed_code).group(1))
        if code_indent >= 4:
            transformed_code = '\n'.join(
                line[4:] if len(line) > 4 else line 
                for line in transformed_code.split('\n')
            )
        
        # Replace return with result =
        transformed_code = re.sub(
            r'(\s*)return\s+',
            r'\1result = ',
            transformed_code
        )
        
        # Build new tool definition
        new_tool = tool_start + kind_line
        
        # Add auth, libs, args if not present
        if not has_auth:
            new_tool += f'{indent}auth: {{}}\n'
        if not has_libs:
            new_tool += f'{indent}libs: {{}}\n'
        if not has_args:
            new_tool += f'{indent}args: {{}}\n'
        
        # Add any middle content that wasn't auth/libs/args
        if middle_content.strip():
            new_tool += middle_content
        
        # Add transformed code
        new_tool += f'{indent}code: |\n'
        for line in transformed_code.split('\n'):
            if line.strip():
                new_tool += f'{indent}  {line}\n'
            elif line:  # preserve empty lines with indentation
                new_tool += f'{indent}  \n'
        
        return new_tool
    
    # Apply migration
    result = re.sub(pattern, replacer, content, flags=re.MULTILINE)
    return result

def main():
    if len(sys.argv) < 2:
        print("Usage: python migrate_python_dsl.py <playbook.yaml> [<playbook2.yaml> ...]")
        print("   or: python migrate_python_dsl.py --all")
        sys.exit(1)
    
    if sys.argv[1] == '--all':
        # Find all playbooks with def main
        root = Path(__file__).resolve().parents[1]
        playbooks_dir = root / 'tests' / 'fixtures' / 'playbooks'
        files = []
        for yaml_file in playbooks_dir.rglob('*.yaml'):
            content = yaml_file.read_text()
            if 'def main(' in content and 'kind: python' in content:
                files.append(yaml_file)
    else:
        files = [Path(f) for f in sys.argv[1:]]
    
    print(f"Migrating {len(files)} playbook(s)...")
    
    for filepath in files:
        print(f"\nProcessing: {filepath}")
        
        try:
            content = filepath.read_text()
            original = content
            
            # Migrate Python tools
            migrated = migrate_python_tool(content)
            
            if migrated != original:
                # Write back
                filepath.write_text(migrated)
                print(f"  ✅ Migrated {filepath.name}")
            else:
                print(f"  ⏭️  No changes needed for {filepath.name}")
        
        except Exception as e:
            print(f"  ❌ Error processing {filepath}: {e}")
            continue
    
    print(f"\n✅ Migration complete!")

if __name__ == '__main__':
    main()
