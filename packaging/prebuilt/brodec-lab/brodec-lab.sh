#!/bin/sh
# brodec-lab: BRODEC's lab bridge on this machine. The service (brodec-lab.service) runs the
# bridge as the brodec-lab user; these commands read and change that service's own data, in
# /var/lib/brodec-lab. With sudo they run as the brodec-lab user, so its files stay its own.
#
#   sudo brodec-lab pair          the pairing code and its QR code, to scan in BRODEC
#   sudo brodec-lab status        paired or not, the lab's name, the last report
#   sudo brodec-lab switch on     turn VECTOR back on after he was switched off over BRODEC
#   sudo brodec-lab recovery-key  the lab's recovery key, to keep somewhere safe
#   brodec-lab lab                read the lab's sources once and print what VECTOR would see
set -eu
bin=/usr/lib/brodec-lab/brodec-lab
env_file=/etc/brodec-lab/brodec-lab.env

# The sources and the name, as the service has them.
if [ -r "$env_file" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$env_file"
  set +a
fi
BRODEC_DATA_DIR=/var/lib/brodec-lab
BRODEC_SWITCH_ON_FILE=/var/lib/brodec-lab/switch-on
export BRODEC_DATA_DIR BRODEC_SWITCH_ON_FILE

if [ "$(id -u)" -eq 0 ]; then
  exec runuser -u brodec-lab -- "$bin" "$@"
fi
if [ "$(id -un)" = brodec-lab ] || [ -r "$BRODEC_DATA_DIR" ]; then
  exec "$bin" "$@"
fi
case "${1:-}" in
  pair|status|switch|recovery-key|health)
    echo "brodec-lab: its data belongs to the service. Run: sudo brodec-lab $*" >&2
    exit 1 ;;
esac
exec "$bin" "$@"
