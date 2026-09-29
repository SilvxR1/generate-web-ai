#!/usr/bin/env bash
# v0.2 R4.2 — install or update the isolated generation worker on a VM.
#
#   sudo ./install.sh <repo-url> <git-ref>
#
# Idempotent. Installs packages, the unprivileged `gwa-worker` user, the
# release at /opt/gwa-worker/releases/<commit> (switched atomically via
# /opt/gwa-worker/current), systemd units, firewall and SSH hardening.
# It NEVER: starts or enables the worker, creates or prints a secret,
# relaxes a kernel/AppArmor restriction, or touches Railway. Supported:
# Debian 12/13 (recommended — unprivileged user namespaces enabled by
# default). Ubuntu 24.04 restricts them via AppArmor: see the runbook.
set -euo pipefail

REPO_URL="${1:?usage: install.sh <repo-url> <git-ref>}"
GIT_REF="${2:?usage: install.sh <repo-url> <git-ref>}"
[[ ${EUID} -eq 0 ]] || { echo "install.sh must run as root" >&2; exit 1; }

# shellcheck disable=SC1091
. /etc/os-release
case "${ID}:${VERSION_ID}" in
  debian:12|debian:13) ;;
  ubuntu:24.04) echo "NOTE: Ubuntu restricts unprivileged user namespaces via AppArmor; see the runbook." ;;
  *) echo "unsupported OS ${ID} ${VERSION_ID} (use Debian 13)" >&2; exit 1 ;;
esac

HERE="$(cd "$(dirname "$0")" && pwd)"
BASE=/opt/gwa-worker
export DEBIAN_FRONTEND=noninteractive

echo "== packages"
apt-get update -q
apt-get install -y -q --no-install-recommends \
  bubblewrap git curl ca-certificates nftables unattended-upgrades dbus-user-session uidmap openssl
if ! node --version 2>/dev/null | grep -q '^v24\.'; then
  curl -fsSL https://deb.nodesource.com/setup_24.x | bash -   # same source as apps/api/Dockerfile.prod
  apt-get install -y -q nodejs
fi
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

echo "== worker user"
id gwa-worker >/dev/null 2>&1 || useradd --system --home-dir /var/lib/gwa-worker --create-home \
  --shell /usr/sbin/nologin gwa-worker
loginctl enable-linger gwa-worker   # the user manager that creates each job's cgroup scope
WORKER_UID="$(id -u gwa-worker)"
if [[ -r /proc/sys/kernel/apparmor_restrict_unprivileged_userns ]] \
   && [[ "$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns)" == "1" ]]; then
  echo "WARNING: AppArmor restricts unprivileged user namespaces; acceptance will FAIL until an"
  echo "         AppArmor profile permits them for /usr/bin/bwrap (not relaxed globally here)."
fi

echo "== release ${GIT_REF}"
install -d -m 0755 "${BASE}" "${BASE}/releases"
STAGE="$(mktemp -d "${BASE}/releases/.stage-XXXXXX")"
git -C "${STAGE}" init -q
git -C "${STAGE}" fetch -q --depth 1 "${REPO_URL}" "${GIT_REF}"
git -C "${STAGE}" checkout -q FETCH_HEAD
COMMIT="$(git -C "${STAGE}" rev-parse HEAD)"
RELEASE="${BASE}/releases/${COMMIT}"
if [[ -d "${RELEASE}" ]]; then
  rm -rf -- "${STAGE}"
else
  mv -T "${STAGE}" "${RELEASE}"
fi
(
  cd "${RELEASE}/apps/api"
  UV_PYTHON_INSTALL_DIR="${BASE}/python" UV_CACHE_DIR="${BASE}/uv-cache" uv sync --frozen
  PLAYWRIGHT_BROWSERS_PATH="${BASE}/ms-playwright" .venv/bin/python -m playwright install --with-deps chromium
)
chown -R root:root "${BASE}"
chmod -R a+rX,go-w "${BASE}"
ln -sfn "${RELEASE}" "${BASE}/current.new" && mv -T "${BASE}/current.new" "${BASE}/current"
echo "current -> ${COMMIT}"

echo "== configuration and units"
install -d -m 0755 /etc/gwa-worker
[[ -f /etc/gwa-worker/worker.env ]] || install -m 0644 "${HERE}/worker.env.example" /etc/gwa-worker/worker.env
install -m 0644 "${HERE}/gwa-worker.service" /etc/systemd/system/gwa-worker.service
install -m 0644 "${HERE}/gwa-worker-acceptance.service" /etc/systemd/system/gwa-worker-acceptance.service
for unit in gwa-worker gwa-worker-acceptance; do
  install -d -m 0755 "/etc/systemd/system/${unit}.service.d"
  cat > "/etc/systemd/system/${unit}.service.d/10-user-runtime.conf" <<EOF
# Written by install.sh: the worker user's systemd manager creates each job's cgroup scope.
[Unit]
Requires=user@${WORKER_UID}.service
After=user@${WORKER_UID}.service

[Service]
Environment=XDG_RUNTIME_DIR=/run/user/${WORKER_UID}
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/${WORKER_UID}/bus
EOF
done
install -d -m 0755 "/etc/systemd/system/user@${WORKER_UID}.service.d" "/etc/systemd/system/user-${WORKER_UID}.slice.d"
cat > "/etc/systemd/system/user@${WORKER_UID}.service.d/50-gwa-delegate.conf" <<'EOF'
# cgroup v2 controllers the per-job scopes need (MemoryMax, TasksMax, CPUQuota).
[Service]
Delegate=cpu io memory pids
EOF
cat > "/etc/systemd/system/user-${WORKER_UID}.slice.d/50-gwa-ceiling.conf" <<'EOF'
# Ceiling for ALL of the worker user's job sandboxes together (one job at a time).
[Slice]
MemoryMax=6G
TasksMax=4096
CPUQuota=350%
EOF
install -d -m 0755 /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=1G\n' > /etc/systemd/journald.conf.d/50-gwa-worker.conf
systemctl daemon-reload
systemctl restart systemd-journald
systemctl restart "user@${WORKER_UID}.service" || true

echo "== firewall"
install -m 0644 "${HERE}/nftables.conf" /etc/nftables.conf
nft -c -f /etc/nftables.conf           # validate before applying (established SSH stays open)
systemctl enable nftables
systemctl restart nftables

echo "== ssh"
has_key() { [[ -s "$1/.ssh/authorized_keys" ]]; }
if has_key /root || { [[ -n "${SUDO_USER:-}" ]] && has_key "$(getent passwd "${SUDO_USER}" | cut -d: -f6)"; }; then
  install -m 0644 "${HERE}/50-gwa-worker-sshd.conf" /etc/ssh/sshd_config.d/50-gwa-worker.conf
  sshd -t && systemctl reload ssh
  echo "key-only SSH enabled"
else
  echo "WARNING: no authorized_keys found for root or ${SUDO_USER:-the sudo user}; SSH hardening NOT applied."
fi

cat <<EOF

Installed ${COMMIT}. The worker is NOT enabled or started. Next (runbook):
  1. install the worker token:   /etc/gwa-worker/worker-token (root:root 0600)
  2. set GWA_API_BASE_URL in     /etc/gwa-worker/worker.env
  3. host acceptance:            systemctl start gwa-worker-acceptance.service
                                 journalctl -u gwa-worker-acceptance.service -o cat | tail -40
  4. only after R4_HOST_ACCEPTANCE=PASS and owner authorization: configure Railway, then
                                 systemctl enable --now gwa-worker.service
EOF
