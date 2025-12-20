"""
SQL processing tools for plugin execution.

Provides SQL parsing and processing utilities used across plugin implementations.
"""

from typing import List


def sql_split(sql_text: str) -> List[str]:
    """
    Split SQL text into individual statements.
    
    Handles string literals properly to avoid splitting on semicolons
    inside quoted strings.
    
    Args:
        sql_text: SQL text to split
        
    Returns:
        List of individual SQL statements
        
    Example:
        >>> sql = "SELECT * FROM users; DELETE FROM logs;"
        >>> sql_split(sql)
        ['SELECT * FROM users', 'DELETE FROM logs']
    """
    statements = []
    current_statement = []
    in_string = False
    string_char = None
    
    for char in sql_text:
        if not in_string and char in ('"', "'"):
            # Enter string literal and keep the quote
            in_string = True
            string_char = char
            current_statement.append(char)
        elif in_string and char == string_char:
            # Exit string literal and keep the quote
            in_string = False
            string_char = None
            current_statement.append(char)
        elif not in_string and char == ';':
            # Statement separator found outside strings
            statement = ''.join(current_statement).strip()
            if statement:
                statements.append(statement)
            current_statement = []
        else:
            current_statement.append(char)
    
    # Add any remaining statement
    remaining = ''.join(current_statement).strip()
    if remaining:
        statements.append(remaining)
    
    return statements
