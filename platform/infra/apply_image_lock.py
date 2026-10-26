"""Apply verified immutable image identities to deployment source files only."""
import json
from pathlib import Path
import re

import yaml

ROOT=Path(__file__).resolve().parents[1]


def main():
    lock=json.loads((ROOT/'infra/images.lock.json').read_text('utf-8'))
    inventory=json.loads((ROOT/'infra/local-image-inventory.json').read_text('utf-8-sig'))
    for image in inventory:
        name=image['image']
        if name.startswith('talent-platform-') or not image['repo_digests']:
            continue
        digest=image['repo_digests'][0].split('@',1)[1]
        pinned=name.split('@',1)[0]+'@'+digest
        if name in lock['images'] and lock['images'][name].split('@',1)[1]!=digest:
            raise ValueError('Public manifest differs from the verified local cache: '+name)
        lock['images'][name]=pinned
        lock['unresolved'].pop(name,None)
    (ROOT/'infra/images.lock.json').write_text(json.dumps(lock,indent=2)+'\n',encoding='utf-8')
    compose_path=ROOT/'compose.yaml'
    text=compose_path.read_text('utf-8')
    compose=yaml.safe_load(text)
    for service in compose['services'].values():
        name=service['image']
        if name in lock['images']:
            text=text.replace('image: '+name+'\n','image: '+lock['images'][name]+'\n')
    compose_path.write_text(text,encoding='utf-8')
    for path in [ROOT/'Dockerfile',ROOT/'infra/gateway.Dockerfile',ROOT/'infra/frontend.Dockerfile']:
        source=path.read_text('utf-8')
        source=re.sub(r'(?m)^FROM (\S+)',lambda match:'FROM '+lock['images'].get(match[1],match[1]),source)
        path.write_text(source,encoding='utf-8')
    print('Applied verified image digests to new deployment sources only.')


if __name__=='__main__':main()
