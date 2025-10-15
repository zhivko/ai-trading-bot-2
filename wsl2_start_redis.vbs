Set oShell = CreateObject("WScript.Shell")
oShell.Run "wsl", 0
oShell.Run "bash -c ""sudo service redis-server start --daemonize yes"""
