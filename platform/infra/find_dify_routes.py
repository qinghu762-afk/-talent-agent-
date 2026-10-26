import json,urllib.request
for path in ['api/controllers/console','api/controllers/console/app','api/controllers/console/auth','api/controllers/console/datasets']:
    with urllib.request.urlopen('https://api.github.com/repos/langgenius/dify/contents/'+path+'?ref=1.17.1',timeout=30) as r: data=json.load(r)
    print(path,[x['name'] for x in data])
