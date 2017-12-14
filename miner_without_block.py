from bitcoin import network
from bitcoin import messages
import json
import random
from bitarray import bitarray
import sys
import codecs
from io import BytesIO

sys.path.append("/home/sunfinite/python-bloomfilter")
sys.path.append("/home/sunfinite/Py-IBLT")
from pybloom import BloomFilter
from iblt import IBLT

address = 'localhost'
port = 4242
DATA_FILE = sys.argv[1]
block_height = DATA_FILE.split('/')[1].split('.')[0] if '/' in DATA_FILE else DATA_FILE.split('.')[0]
MEMPOOL_PCT = float(sys.argv[2])
logging = network.logging

def reconcile_iblts(i1, i2):
    for i in range(i1.m):
        prev_count = i1.T[i][0]
        temp = [i1.T[i][0] - i2.T[i][0]]
        for j in range(1, 4):
            temp.append((i1.T[i][j] ^ i2.T[i][j]))
        i1.T[i] = temp

    i = 0
    recovered_txs_ids = set()
    while True:
        if i1.T[i][0] == 1:
            k = i1.T[i][1].tobytes().rstrip(b'0')
            if i1.key_hash(k) == i1.T[i][3]:
                logging.info("Found a pure cell")
                i1.delete(k, i1.T[i][2].tobytes())
                k = codecs.encode(k, 'hex')
                # logging.info(k)
                # logging.info(skipped_txs_ids)
                # logging.info(k in skipped_txs_ids)
                if k in skipped_txs_ids:
                    logging.info("Recovered %s" % k)
                    recovered_txs_ids.add(k)
                i = 0
            else:
                i += 1
        else:
            i += 1

        if i == i1.m:
            break
    if skipped_txs_ids == recovered_txs_ids:
        logging.info("All skipped tx ids have been recovered!")
    else:
        logging.info("Could not recover %s" % (skipped_txs_ids - recovered_txs_ids))
    logging.info("Finished reconciling")
    return list(skipped_txs_ids - recovered_txs_ids)

def inv_handler(connection, inv):
    # only request the items if it is announced alone, not in bulk
    if len(inv.hashes) == 1:
        h = inv.hashes[0]
        if h[0] == 5:
            logging.info("Received graphene inv with hash %s" % h[1])
            p = messages.GetDataPacket()
            t, h = inv.hashes[0]
            p.hashes.append((t, h, len(selected_txs)))
            # p.hashes.append((t, h))
            logging.info("Sending getdata")
            connection.send('getdata', p)

def tx_to_bytes(tx):
    tx_packet = messages.TxPacket()
    tx_packet.inputs = []
    tx_packet.outputs = []
    for tx_in in tx['inputs']:
        if tx_in['address'] is None:
            address = '0x00' * 32
        else:
            address = tx_in['address']
        tx_packet.inputs.append(((address.encode('utf-8'), tx_in['index']),
            tx_in['script_signature'].encode('utf-8'), 0))
    for tx_out in tx['outputs']:
       tx_packet.outputs.append((tx_out['value'],
        tx_out['script'].encode('utf-8')))
    buf = BytesIO()
    tx_packet.toWire(buf)
    buf.seek(0)
    return buf.read()

def graphene_handler(connection, graphene):
    logging.info("Graphene received!")
    b = bitarray()
    b.frombytes(graphene.bloom_filter[::-1])
    b.reverse()
    bf = BloomFilter(capacity=graphene.bloom_filter_capacity, error_rate=graphene.fpr)
    bf.bitarray = b

    iblt = IBLT(m=graphene.iblt_m, k=3, key_size=32, value_size=0)
    iblt.T = graphene.iblt_T

    iblt2 = IBLT(m=graphene.iblt_m, k=3, key_size=32, value_size=0)
    found = 0

    for tx in selected_txs:
        if tx['hash'] in bf:
            found += 1
            # logging.info("%s present in the bloom filter!" % tx['hash'])
            iblt2.insert(tx['hash'], '')
        else:
            # logging.info("%s missing from bloom filter" % tx['hash'])
            pass

    logging.info("Found and inserted %d txs into the second IBLT" % found)
    unrecovered = reconcile_iblts(iblt, iblt2)


    with open('data/%s_results.txt' % block_height, 'a') as fout:

        graphene = (bf.num_bits + iblt.m * (4 + 32 + 10) * 8) / 8
        cmpct = bytes_pushed['cmpct']
        xthin = bf.num_bits / 8 + 8 * (len(selected_txs) + len(skipped_txs))
        txs = sum(bytes_pushed['txs'])
        fout.write('%f,%d,%d,%d,%d,%d,%d,%d\n' % (MEMPOOL_PCT, txs, graphene,
            cmpct, xthin, len(unrecovered), bytes_pushed['n_txs'], len(skipped_txs)))
        logging.info("Number of bytes for graphene block: %d" % graphene)
        logging.info("Minimum number of bytes for compact block: %d" % cmpct)
        logging.info("Minimum number of bytes for xthin block: %d" % xthin)
        logging.info("Number of bytes for txs: %d" % txs)
        sys.exit(0)


def start():
    with open(DATA_FILE) as fin:
        blocks = fin.read().strip().split('\n')
        for block in blocks[:1]:
            block = json.loads(block)
            txs = block['txs']
            n_txs = len(txs)
            bytes_pushed['n_txs'] = n_txs
            logging.info("Read %d transactions" % n_txs)
            logging.info("Selecting %d transactions at random for inclusion in mempool" % (MEMPOOL_PCT * n_txs))
            # random.shuffle(txs)
            n_selected = 0
            for i, tx in enumerate(txs):
                if n_selected < MEMPOOL_PCT * n_txs:
                    selected_txs.append(tx)
                    n_selected += 1
                else:
                    # print("Excluding ", tx['hash'])
                    skipped_txs_ids.add(tx['hash'].encode('utf-8'))
                    bytes_pushed['txs'].append(len(tx_to_bytes(tx)))
                    skipped_txs.append(tx)
            bytes_pushed['cmpct'] = n_txs * 6 + 10 + 80
        logging.info("Skipped %d transactions" % len(skipped_txs))
    client = network.GeventNetworkClient()
    client.register_handler('inv', inv_handler)
    client.register_handler('graphene', graphene_handler)
    network.ClientBehavior(client)
    client.listen(address, port)
    client.run_forever()


if __name__ == "__main__":
    selected_txs = []
    skipped_txs_ids = set()
    # FIXME: shoddy
    skipped_txs = []
    bytes_pushed = {'txs': [], 'graphene': 0, 'headers': 80}
    start()
