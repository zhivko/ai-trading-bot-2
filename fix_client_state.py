#!/usr/bin/env python3

import re

def fix_client_state(filename):
    """Fix client_state usage in the file"""

    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Update function signatures
    content = re.sub(
        r'async def handle_\w+\(data: dict, client_state: dict, request_id: str\) -> dict:',
        lambda m: m.group(0).replace('client_state: dict', 'websocket: WebSocket'),
        content
    )

    # 2. Update specific functions that were already updated (their signatures)
    # handle_config_message, handle_init_message signatures should already be updated from earlier changes

    # 3. Update calls in handle_request_action
    content = re.sub(
        r'return await handle_\w+\(data, client_state, request_id\)',
        lambda m: m.group(0).replace('client_state', 'websocket'),
        content
    )

    # 4. Update function bodies - replace client_state usage with websocket.scope['session']
    # This is the most complex part. For each function that used client_state, we need to:
    # - Add: session = websocket.scope.get('session', {})
    # - Replace: client_state.get('key') with session.get('key')

    # Find all handler function blocks
    handler_pattern = r'(async def handle_\w+\([^)]+websocket: WebSocket[^)]+request_id: str\) -> dict:.*?)(?=\n\nasync def|$)'
    handler_matches = re.finditer(handler_pattern, content, re.DOTALL)

    new_content = content
    for match in reversed(list(handler_matches)):  # Process in reverse to maintain positions
        func_block = match.group(1)

        # Skip functions that are too complex or already fixed
        if 'handle_get_drawings' in func_block and 'session = websocket.scope.get' in func_block:
            continue
        if 'handle_config_message' in func_block or 'handle_init_message' in func_block:
            continue

        # Add session extraction at the beginning of function body
        func_start = func_block.find('"""') # Skip docstring
        if func_start > 0:
            body_start = func_block.find('"""', func_start + 3) + 3
        else:
            body_start = func_block.find(':\n') + 2

        # Add session extraction
        session_line = "\n    session = websocket.scope.get('session', {})\n"
        func_block = func_block[:body_start] + session_line + func_block[body_start:]

        # Replace client_state.get() calls with session.get()
        func_block = re.sub(r'client_state\.get\(([^)]+)\)', r'session.get(\1)', func_block)

        # Replace direct client_state[] access
        func_block = re.sub(r'client_state\[([\'"]([^\'"]+)[\'"])\]', r"session.get('\2')", func_block)

        # Replace data.get(..., client_state.get(...)) patterns
        func_block = re.sub(r'data\.get\([^,]+,\s*client_state\.get\(([^)]+)\)\s*\)',
                           lambda m: f"data.get('{m.group(1).strip('\"\'')}', session.get({m.group(1)}))", func_block)

        # Replace new_content with the updated block
        new_content = new_content[:match.start()] + func_block + new_content[match.end():]

    # Write back
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(new_content)

    print("Fixed client_state usage")

if __name__ == "__main__":
    fix_client_state("AppTradingView2.py")
