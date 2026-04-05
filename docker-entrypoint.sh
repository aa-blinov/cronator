#!/bin/bash

DIRS="/app/scripts /app/envs /app/logs /app/data /app/data/artifacts"

for dir in $DIRS; do
    mkdir -p "$dir" 2>/dev/null || true
    chown cronator:cronator "$dir" 2>/dev/null || true
    chmod 2775 "$dir" 2>/dev/null || chmod 755 "$dir" 2>/dev/null || true
done

# Switch to cronator user and execute the main command
exec gosu cronator "$@"
