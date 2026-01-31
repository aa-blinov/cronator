#!/bin/bash
# Don't use set -e here because we want to continue even if some chown/chmod fail
# (e.g., on some mounted volumes with restrictive filesystems)

# This script runs as root to fix permissions before switching to cronator user
# Ensure directories exist and have proper permissions
# This handles the case where volumes are mounted from the host

# Ensure /app is owned by cronator (for any files copied during build)
# This may fail on mounted volumes, which is OK - we'll handle it in the app
chown -R cronator:cronator /app 2>/dev/null || true

# Ensure specific directories exist and have proper permissions
# This handles the case where volumes are mounted from the host
DIRS="/app/scripts /app/envs /app/logs /app/data /app/data/artifacts"

for dir in $DIRS; do
    # Create directory if it doesn't exist
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir" 2>/dev/null || true
    fi
    # Set ownership to cronator user (we're running as root here)
    # This may fail on some mounted volumes (e.g., NFS, some Docker volumes)
    # which is OK - the application will handle permission errors gracefully
    chown -R cronator:cronator "$dir" 2>/dev/null || true
    # Set permissions (read/write/execute for owner, read/execute for group/others)
    # Also set setgid bit on directories so new files inherit group ownership
    chmod 2775 "$dir" 2>/dev/null || chmod 755 "$dir" 2>/dev/null || true
done

# Always rebuild CSS from input.css on container startup
# This ensures CSS is always up-to-date with any changes
if [ -f /app/app/static/input.css ]; then
    echo "Building CSS from input.css..."
    # Install npm dependencies if node_modules doesn't exist
    if [ ! -d /app/node_modules ]; then
        npm install --silent 2>/dev/null || true
    fi
    # Build CSS
    npm run build:css 2>/dev/null || true
    echo "CSS build completed (or skipped if npm not available)"
fi

# Switch to cronator user and execute the main command
exec gosu cronator "$@"
