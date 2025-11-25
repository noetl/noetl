"""
Sample Python script for testing script attribute from file source.

This script demonstrates:
- Function-based execution (main function)
- Argument passing
- Return value handling
"""

def main(name="World", count=1):
    """
    Generate a greeting message.
    
    Args:
        name: Name to greet
        count: Number of times to greet
        
    Returns:
        Dictionary with greeting message and metadata
    """
    messages = []
    for i in range(count):
        messages.append(f"Hello, {name}! (Greeting #{i+1})")
    
    return {
        "status": "success",
        "messages": messages,
        "total_greetings": count,
        "script_source": "file"
    }
