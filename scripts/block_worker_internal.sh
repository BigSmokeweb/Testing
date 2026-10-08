#!/usr/bin/env bash
# AutoQA: Block worker container from internal / private IP ranges.
# Run on VPS host after docker compose up.
set -euo pipefail

NETWORK_NAME="autoqa_worker_external"

SUBNET=$(docker network inspect "${NETWORK_NAME}" --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}' 2>/dev/null || true)

if [ -z "${SUBNET}" ]; then
    echo "Network ${NETWORK_NAME} not found. Start docker containers first:"
    echo "  docker compose up -d"
    exit 1
fi

echo "Found worker subnet: ${SUBNET}"

# Block private IP ranges from worker network on DOCKER-USER chain
for CIDR in "10.0.0.0/8" "172.16.0.0/12" "192.168.0.0/16" "169.254.0.0/16" "127.0.0.0/8"; do
    if iptables -C DOCKER-USER -s "${SUBNET}" -d "${CIDR}" -j DROP 2>/dev/null; then
        echo "Rule exists: DROP ${SUBNET} -> ${CIDR}"
    else
        iptables -I DOCKER-USER -s "${SUBNET}" -d "${CIDR}" -j DROP
        echo "Added rule: DROP ${SUBNET} -> ${CIDR}"
    fi
done

# Persist rules if netfilter-persistent installed
if command -v netfilter-persistent &>/dev/null; then
    netfilter-persistent save
    echo "Saved iptables rules."
fi

echo "Worker network isolation complete."
