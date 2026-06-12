# Automation — Ansible

`infra/ansible/` provisions machines and deploys the stack end-to-end.
Every playbook is idempotent: a second run reports `changed=0` and converges
drift back to the declared state.

## Layout

```
infra/ansible/
├── ansible.cfg
├── inventories/example/hosts.yml     # copy per environment
└── playbooks/
    ├── site.yml          # full bring-up (imports the rest in order)
    ├── provision.yml     # packages, ops user, ssh hardening, ufw, auto-updates
    ├── docker.yml        # Docker Engine from the official apt repo
    ├── kubernetes.yml    # kubectl + Kind + the trading cluster + ingress
    ├── deploy-app.yml    # git checkout → docker compose up → health gate
    ├── monitoring.yml    # SigNoz from its official compose bundle
    ├── update.yml        # serialized apt upgrades + conditional reboot + re-verify
    └── verify.yml        # read-only health assertions (safe any time)
```

Host groups: `docker_hosts` (app), `k8s_hosts` (Kind), `monitoring_hosts`
(SigNoz) — a single VM can be in all three.

## Usage

```bash
cd infra/ansible
ansible-galaxy collection install community.docker community.general

# Everything, in order:
ansible-playbook playbooks/site.yml

# Individual stages:
ansible-playbook playbooks/provision.yml
ansible-playbook playbooks/deploy-app.yml -e @secrets.vault.yml --ask-vault-pass
ansible-playbook playbooks/verify.yml          # read-only, run any time
ansible-playbook playbooks/update.yml          # serial: 1 — rolling updates

# Local smoke test without any remote host:
ansible-playbook -i 'localhost,' -c local playbooks/verify.yml
```

## Secrets

API keys never live in the repo or inventory. Two supported paths:

```bash
# 1. ansible-vault file passed at runtime
ansible-vault create secrets.vault.yml     # app_env: { ALPACA_API_KEY: ..., GEMINI_API_KEY: ... }
ansible-playbook playbooks/deploy-app.yml -e @secrets.vault.yml --ask-vault-pass

# 2. environment lookups in a group_vars override
app_env:
  ALPACA_API_KEY: "{{ lookup('env', 'ALPACA_API_KEY') }}"
```

The rendered `.env` on the host is mode `0600` and `no_log: true` keeps
values out of Ansible output.

## Idempotency notes

- Package/repo/user/file tasks are natively idempotent modules.
- `kind create cluster` is guarded by a `kind get clusters` check.
- `kubectl apply` registers output and reports `changed` only on
  created/configured.
- `deploy-app.yml` gates success on `/health` returning 200 (30×2s retries) —
  a deployment that doesn't serve traffic fails the play.
- `update.yml` runs `serial: 1` and reboots only when
  `/var/run/reboot-required` exists, then re-runs `verify.yml`.
