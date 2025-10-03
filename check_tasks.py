#!/usr/bin/env python3

import requests
import json

try:
    response = requests.get('http://192.16:5000/health/background-tasks', timeout=5)
    if response.status_code == 200:
        data = response.json()

        print('=== BACKGROUND TASKS STATUS ===')
        for task_name, status in data['background_tasks'].items():
            exists = status['exists']
            running = status['running'] if exists else False
            exception = status.get('exception', 'None')
            exception_str = exception if exception and exception != 'None' else 'No'
            print(f'{task_name}: EXISTS={exists}, RUNNING={running}, EXCEPTION={exception_str}')

        # Check trade aggregator specifically
        trade_task = data['background_tasks']['trade_aggregator_task']
        if trade_task.get('exception'):
            print(f'\n=== TRADE AGGREGATOR EXCEPTION ===')
            print(trade_task['exception'])
    else:
        print(f'HTTP Error: {response.status_code}')

except Exception as e:
    print(f'Error checking background tasks: {e}')
