#!/usr/bin/env python3
"""Deploy Qwen3-TTS to RunPod Serverless (load balancing endpoint).

Usage:
    # Create endpoint (first time):
    python scripts/deploy_runpod.py create

    # Update endpoint (after pushing new Docker image):
    python scripts/deploy_runpod.py update <endpoint_id>

    # Check endpoint status:
    python scripts/deploy_runpod.py status <endpoint_id>

    # Delete endpoint:
    python scripts/deploy_runpod.py delete <endpoint_id>

    # List all endpoints:
    python scripts/deploy_runpod.py list

Requires:
    RUNPOD_API_KEY env var or --api-key flag
"""

import argparse
import json
import os
import sys

import requests

BASE_URL = "https://rest.runpod.io/v1"
DOCKER_IMAGE = "decay256/qwen3-tts:latest"
ENDPOINT_NAME = "qwen3-tts"


def get_api_key(args):
    key = getattr(args, "api_key", None) or os.environ.get("RUNPOD_API_KEY", "")
    if not key:
        print("Error: RUNPOD_API_KEY not set. Pass --api-key or set env var.")
        sys.exit(1)
    return key


def headers(api_key):
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def cmd_list(args):
    api_key = get_api_key(args)
    resp = requests.get(f"{BASE_URL}/endpoints", headers=headers(api_key))
    resp.raise_for_status()
    endpoints = resp.json()
    if not endpoints:
        print("No endpoints found.")
        return
    for ep in endpoints:
        print(f"  {ep.get('id', '?')}  {ep.get('name', '?')}  {ep.get('status', '?')}  workers: {ep.get('workersMin', '?')}-{ep.get('workersMax', '?')}")


def cmd_create(args):
    api_key = get_api_key(args)
    tts_api_key = args.tts_api_key or os.environ.get("TTS_API_KEY", "")

    payload = {
        "name": args.name or ENDPOINT_NAME,
        "dockerImage": args.image or DOCKER_IMAGE,
        "gpuTypeIds": ["NVIDIA GeForce RTX 4090"],
        "env": {
            "API_KEY": tts_api_key,
            "ENABLED_MODELS": "voice_design,base",
            "PORT": "8000",
        },
        "scalerType": "QUEUE_DELAY",
        "scalerValue": 4,
        "workersMin": 0,
        "workersMax": args.max_workers,
        "idleTimeout": args.idle_timeout,
        "executionTimeoutMs": 600000,  # 10 min max per request
        "type": "LOAD_BALANCER",
    }

    print(f"Creating endpoint '{payload['name']}'...")
    print(f"  Image: {payload['dockerImage']}")
    print(f"  GPU: {payload['gpuTypeIds'][0]}")
    print(f"  Workers: {payload['workersMin']}-{payload['workersMax']}")
    print(f"  Idle timeout: {payload['idleTimeout']}s")

    resp = requests.post(f"{BASE_URL}/endpoints", headers=headers(api_key), json=payload)
    if resp.status_code >= 400:
        print(f"Error {resp.status_code}: {resp.text}")
        sys.exit(1)

    data = resp.json()
    endpoint_id = data.get("id", "unknown")
    print(f"\n✓ Endpoint created: {endpoint_id}")
    print(f"  URL: https://{endpoint_id}.api.runpod.ai/")
    print(f"\nUpdate your relay config to point to this URL.")
    return data


def cmd_update(args):
    api_key = get_api_key(args)
    payload = {}
    if args.image:
        payload["dockerImage"] = args.image
    if args.max_workers is not None:
        payload["workersMax"] = args.max_workers
    if args.idle_timeout is not None:
        payload["idleTimeout"] = args.idle_timeout

    if not payload:
        print("Nothing to update. Use --image, --max-workers, or --idle-timeout.")
        return

    resp = requests.patch(f"{BASE_URL}/endpoints/{args.endpoint_id}", headers=headers(api_key), json=payload)
    resp.raise_for_status()
    print(f"✓ Endpoint {args.endpoint_id} updated: {json.dumps(payload)}")


def cmd_status(args):
    api_key = get_api_key(args)
    resp = requests.get(f"{BASE_URL}/endpoints/{args.endpoint_id}", headers=headers(api_key))
    resp.raise_for_status()
    print(json.dumps(resp.json(), indent=2))


def cmd_delete(args):
    api_key = get_api_key(args)
    resp = requests.delete(f"{BASE_URL}/endpoints/{args.endpoint_id}", headers=headers(api_key))
    resp.raise_for_status()
    print(f"✓ Endpoint {args.endpoint_id} deleted")


def main():
    parser = argparse.ArgumentParser(description="Deploy Qwen3-TTS to RunPod")
    parser.add_argument("--api-key", help="RunPod API key")
    sub = parser.add_subparsers(dest="command", required=True)

    # list
    sub.add_parser("list", help="List all endpoints")

    # create
    p_create = sub.add_parser("create", help="Create a new endpoint")
    p_create.add_argument("--name", default=ENDPOINT_NAME)
    p_create.add_argument("--image", default=DOCKER_IMAGE)
    p_create.add_argument("--tts-api-key", help="API key for TTS auth")
    p_create.add_argument("--max-workers", type=int, default=1)
    p_create.add_argument("--idle-timeout", type=int, default=30, help="Seconds before idle worker shuts down")

    # update
    p_update = sub.add_parser("update", help="Update endpoint")
    p_update.add_argument("endpoint_id")
    p_update.add_argument("--image")
    p_update.add_argument("--max-workers", type=int)
    p_update.add_argument("--idle-timeout", type=int)

    # status
    p_status = sub.add_parser("status", help="Get endpoint status")
    p_status.add_argument("endpoint_id")

    # delete
    p_delete = sub.add_parser("delete", help="Delete endpoint")
    p_delete.add_argument("endpoint_id")

    args = parser.parse_args()
    {"list": cmd_list, "create": cmd_create, "update": cmd_update,
     "status": cmd_status, "delete": cmd_delete}[args.command](args)


if __name__ == "__main__":
    main()
