"""Resolve public image manifests without contacting or changing Docker.

Run explicitly when upgrading; normal deployment uses images.lock.json.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
ACCEPT = ', '.join(['application/vnd.oci.image.index.v1+json', 'application/vnd.docker.distribution.manifest.list.v2+json', 'application/vnd.oci.image.manifest.v1+json', 'application/vnd.docker.distribution.manifest.v2+json'])


def resolve(image, proxy=None):
    if '@sha256:' in image:
        return image, image
    repository, tag = image.rsplit(':', 1)
    if repository.startswith('quay.io/'):
        registry, repository = 'quay.io', repository.removeprefix('quay.io/')
    else:
        registry = 'registry-1.docker.io'
        if '/' not in repository:
            repository = 'library/' + repository
    with httpx.Client(proxy=proxy, timeout=60, follow_redirects=True, trust_env=False) as client:
        url = f'https://{registry}/v2/{repository}/manifests/{tag}'
        response = client.head(url, headers={'Accept': ACCEPT})
        if response.status_code == 401:
            challenge = response.headers['www-authenticate']
            values = dict(re.findall(r'(\w+)="([^"]+)"', challenge))
            realm = values.pop('realm')
            auth = client.get(realm, params=values)
            auth.raise_for_status()
            token = auth.json().get('token') or auth.json()['access_token']
            response = client.head(url, headers={'Accept': ACCEPT, 'Authorization': 'Bearer ' + token})
        response.raise_for_status()
        digest = response.headers['docker-content-digest']
        if not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
            raise ValueError('Invalid public manifest digest')
        return image, image + '@' + digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--proxy')
    args = parser.parse_args()
    compose = yaml.safe_load((ROOT/'compose.yaml').read_text('utf-8-sig'))
    images = {service['image'] for service in compose['services'].values() if not service['image'].startswith(('talent-platform-', 'talent-agent-'))}
    for path in [ROOT/'Dockerfile', ROOT/'infra/gateway.Dockerfile', ROOT/'infra/frontend.Dockerfile']:
        images.update(re.findall(r'(?m)^FROM\s+(\S+)', path.read_text('utf-8')))
    resolved, failures = {}, {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = {image: pool.submit(resolve, image, args.proxy) for image in sorted(images)}
        for image, future in pending.items():
            try:
                original, pinned = future.result()
                resolved[original] = pinned
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                failures[image] = type(exc).__name__
    target = ROOT/'infra/images.lock.json'
    target.write_text(json.dumps({'schema': 1, 'resolved_at': datetime.now(timezone.utc).isoformat(), 'images': resolved, 'unresolved': failures}, indent=2)+'\n', encoding='utf-8')
    print(f'Locked {len(resolved)} public images without changing Docker.')
    if failures:
        print('Resolve from a verified local image inventory:', ', '.join(failures))


if __name__ == '__main__':
    main()
