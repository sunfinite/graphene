from bitcoin import network
from bitcoin import messages
import json
import random
import time
import sys
from io import BytesIO
from gevent import socket
import math

sys.path.append("/home/sunfinite/python-bloomfilter")
sys.path.append("/home/sunfinite/Py-IBLT")
from pybloom import BloomFilter
from iblt import IBLT



peer_address = 'localhost'
peer_port = 4242
DATA_FILE = sys.argv[1]
logging = network.logging
n_cells = 200


def tx_to_bytes(tx):
    tx_packet = messages.TxPacket()
    tx_packet.inputs = []
    tx_packet.outputs = []
    for tx_in in tx['inputs']:
        if tx_in['address'] is None:
            address = '0x00' * 32
        else:
            address = str(tx_in['address'])
        tx_packet.inputs.append(((address, tx_in['index']),
            tx_in['script_signature'].encode('utf-8'), 0))
    for tx_out in tx['outputs']:
       tx_packet.outputs.append((tx_out['value'],
        tx_out['script'].encode('utf-8')))
    buf = BytesIO()
    tx_packet.toWire(buf)
    buf.seek(0)
    return buf.read() 

def build_bloom_filter_and_iblt(m, include_value_in_iblt=False):
    c = 8 * math.pow(math.log(2), 2)
    tau = 16.5
    n = len(selected_txs)
    alpha = n / (c * tau)
    # print(alpha * tau)

    if m <= n:
        fpr = 0.1
    else:
        fpr = alpha / m - n
    print("Mempool difference", abs(m - n))
    n_cells = int((4 / 3 ) * abs(m - n)) + 30
    print('n_cells', n_cells)
    logging.info("Calculated FPR: %f" % fpr)
    fpr = 0.1
    b = BloomFilter(capacity=n, error_rate=fpr)
    i = IBLT(m=n_cells, k=3, key_size=32, value_size=0)
    for tx in selected_txs:
        b.add(tx['hash'])
        v = ''
        if include_value_in_iblt:
            v = tx_to_bytes(tx)
        i.insert(tx['hash'], v)
    return b, i

def verack_handler(connection, verack):
    logging.info("verack handled")
    p = messages.InvPacket()
    p.hashes.append((5, b"\x00" * 32))
    connection.send("inv", p)

def getdata_handler(connection, getdata):
    if len(getdata.hashes) == 1:
        logging.info("Received mempool size as %d" % getdata.hashes[0][2])
        b, i = build_bloom_filter_and_iblt(getdata.hashes[0][2])
        logging.info("Number of bits in the bloom filter: %d", b.num_bits)
        p = messages.GraphenePacket()
        p.bloom_filter = b.bitarray
        p.bloom_filter_capacity = b.capacity
        p.fpr = b.error_rate
        p.iblt = i
        connection.send("graphene", p)

def start():
    with open(DATA_FILE) as fin:
        blocks = fin.read().strip().split('\n')
        for block in blocks[:1]:
            block = json.loads(block)
            txs = block['txs']
            n_txs = len(txs)
            logging.info("Read %d transactions" % n_txs)
            # random.shuffle(txs)
            n_selected = 0
            selected_txs.extend(txs)
    client = network.GeventNetworkClient()
    client.register_handler('getdata', getdata_handler)
    client.register_handler('verack', verack_handler)
    network.ClientBehavior(client)
    client.connect((peer_address, peer_port))
    client.run_forever()

if __name__ == "__main__":
    selected_txs = []
    start()
