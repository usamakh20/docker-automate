import docker
import requests
import sys
import psutil
import time

client = docker.from_env()

credentials = ('dataplaneapi', 'admin')
content_json = {"Content-Type": "application/json"}


def get_haproxy_config_version():
    return requests.get(url='http://localhost:5555/v2/services/haproxy/configuration/raw',
                        auth=credentials).json()['_version']


def create_transaction():
    return requests.post(url='http://localhost:5555/v2/services/haproxy/transactions',
                         params={'version': get_haproxy_config_version()}, auth=credentials,
                         headers=content_json).json()['id']


def apply_transaction(trx_id):
    return requests.put(url='http://localhost:5555/v2/services/haproxy/transactions/' + trx_id,
                        auth=credentials, headers=content_json)


def create_servers(count=1):
    """
    Creates docker containers defaults to launching a container mapped at port 5000.
    :param count: int
    :return: None
    """
    trx_id = create_transaction()

    current_server_count = len(client.containers.list())
    for i in range(current_server_count, count + current_server_count):
        client.containers.run(
            image='project-2',
            ports={'5000/tcp': 5000 + i},
            detach=True
        )

        requests.post(url='http://localhost:5555/v2/services/haproxy/configuration/servers',
                      params={'backend': 'server_backend', 'transaction_id': trx_id},
                      auth=credentials, headers=content_json,
                      json={"name": "server" + str(i), "address": "localhost", "port": 5000 + i, "check": "enabled",
                            "maxconn": 30})

    apply_transaction(trx_id)


def delete_servers(count=1, _all=False):
    """
    Deletes docker containers defaults to deleting the most recently created container.
    :param _all:
    :param count:int
    :return: None
    """
    trx_id = create_transaction()

    current_server_count = len(client.containers.list())
    if _all:
        count = current_server_count
    for i, container in enumerate(client.containers.list()[:count]):
        container.kill()

        requests.delete(
            url='http://localhost:5555/v2/services/haproxy/configuration/servers/server' + str(
                current_server_count - 1 - i),
            params={'backend': 'server_backend', 'transaction_id': trx_id},
            auth=credentials, headers=content_json)

    apply_transaction(trx_id)
    client.containers.prune()


def update_servers(count=1):
    """
    Maintains the count of currently running docker containers.
    :param count: int
    :return: None
    """

    current_server_count = len(client.containers.list())
    if current_server_count < count:
        create_servers(count - current_server_count)
    else:
        delete_servers(current_server_count - count)


if __name__ == "__main__":

    delete_servers(_all=True)

    transaction_id = create_transaction()

    requests.post(url='http://localhost:5555/v2/services/haproxy/configuration/backends',
                  params={'transaction_id': transaction_id},
                  auth=credentials,
                  json={"name": "server_backend", "mode": "http", "balance": {"algorithm": "roundrobin"},
                        "httpchk": {"method": "HEAD", "uri": "/", "version": "HTTP/1.0"}},
                  headers=content_json)

    requests.post(url='http://localhost:5555/v2/services/haproxy/configuration/servers',
                  params={'backend': 'server_backend', 'transaction_id': transaction_id},
                  auth=credentials,
                  json={"name": "server0", "address": "localhost", "port": 5000, "check": "enabled", "maxconn": 30},
                  headers=content_json)

    requests.post(url='http://localhost:5555/v2/services/haproxy/configuration/frontends',
                  params={'transaction_id': transaction_id},
                  auth=credentials,
                  json={"name": "server_frontend", "mode": "http", "default_backend": "server_backend", "maxconn": 2000,
                        "stats_options": {"stats_uri_prefix": "/haproxy?stats"}},
                  headers=content_json)

    requests.post(url='http://localhost:5555/v2/services/haproxy/configuration/binds',
                  params={'frontend': 'server_frontend', 'transaction_id': transaction_id},
                  auth=credentials, json={"name": "http", "address": "*", "port": 80},
                  headers=content_json)

    r = apply_transaction(transaction_id)

    if r.json()['status'] != 'success':
        sys.exit('Error Creating frontend or backend!!')

    print("~~~~~~~~~~~Monitoring CPU Utilization~~~~~~~~~~~~")
    while True:
        time.sleep(10)  # Monitor every 10 secs
        cpu = psutil.cpu_percent()
        N = int(cpu / 10) if cpu > 10 else 1
        update_servers(N)
        print("CPU Utilization: " + str(cpu) + "%\t No. of servers: " + str(N))
