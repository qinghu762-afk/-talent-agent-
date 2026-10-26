"""Initialize separate Milvus logical databases in the new Milvus only."""
from pymilvus import MilvusClient
client = MilvusClient(uri='http://milvus:19530')
for name in ['talent', 'dify']:
    if name not in client.list_databases():
        client.create_database(name)
print('New-platform Milvus logical databases ready.')
