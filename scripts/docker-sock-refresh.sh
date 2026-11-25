#!/bin/sh
# Restart containers whose bind-mounted Docker socket went stale.
#
# live-restore keeps containers running while dockerd restarts, but dockerd
# recreates /var/run/docker.sock. Containers that bind-mount the socket
# (Nextcloud AIO's mastercontainer, Arcane) keep the old, deleted one and lose
# all access to Docker until they are restarted. Run by docker-sock-refresh.service
# each time docker.service starts.
set -u
SOCK=/var/run/docker.sock

# Wait for dockerd to answer.
i=0
until docker info >/dev/null 2>&1; do
    i=$((i + 1)); [ "$i" -ge 60 ] && { echo "dockerd not answering" >&2; exit 1; }
    sleep 2
done
# Give containers with restart policies time to come up after a full boot.
sleep 10

host_ino=$(stat -c %i "$SOCK")
rc=0
for id in $(docker ps -q); do
    docker inspect -f '{{range .Mounts}}{{if eq .Destination "/var/run/docker.sock"}}yes{{end}}{{end}}' "$id" | grep -q yes || continue
    name=$(docker inspect -f '{{.Name}}' "$id" | sed 's#^/##')
    pid=$(docker inspect -f '{{.State.Pid}}' "$id")
    ino=$(stat -L -c %i "/proc/$pid/root$SOCK" 2>/dev/null || echo missing)
    if [ "$ino" = "$host_ino" ]; then
        echo "$name: socket current"
        continue
    fi
    echo "$name: stale socket (inode $ino, host $host_ino), restarting"
    if docker restart "$name" >/dev/null; then
        pid=$(docker inspect -f '{{.State.Pid}}' "$name")
        ino=$(stat -L -c %i "/proc/$pid/root$SOCK" 2>/dev/null || echo missing)
        if [ "$ino" = "$host_ino" ]; then echo "$name: socket current after restart"; else echo "$name: still stale" >&2; rc=1; fi
    else
        echo "$name: restart failed" >&2; rc=1
    fi
done
exit $rc
