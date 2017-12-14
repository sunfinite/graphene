import os
import blocktrail
import json
import sys
from utils import *

FETCH_HISTORY='FETCH_HISTORY'
if __name__ == '__main__':
    client = blocktrail.APIClient(api_key=os.environ['BLOCKTRAIL_KEY'],
        api_secret=os.environ['BLOCKTRAIL_SECRET'], network="BTC", testnet=False)

    block_hash = ''
    prev_block_hash = ''
    block = None

    blocks = {'fetch_next': None, 'fetched': []}
    if not os.path.exists(FETCH_HISTORY) or len(sys.argv) > 1:
        block = client.block_latest()
        block_hash = block['hash']
    else:
        with open(FETCH_HISTORY) as fin:
            blocks = json.loads(fin.read().strip())
            block = client.block(blocks['fetch_next'])

    per_page = 100
    page = 1
    print("Fetching transactions for block", block['hash'])
    print("There are a total of %d transactions in this block" % block['transactions'])
    all_txs = []
    while True:
        txs = client.block_transactions(block['hash'], page=page, limit=per_page)
        # for tx in txs['data']:
        #    fout.write(json.dumps(tx) + '\n')
        all_txs.extend(txs['data'])
        print("Fetched %d transactions" % (page * per_page))
        if page * per_page > block['transactions']:
            break
        page += 1

    with open('%s/%d.json' % (DATADIR, block['height']), 'w') as fout:
        block['txs'] = all_txs
        fout.write(json.dumps(block))

        with open(FETCH_HISTORY, 'w') as fout:
            blocks['fetched'].append(block['hash'])
            while block['prev_block'] in blocks['fetched']:
                block = client.block(block['prev_block'])
            blocks['fetch_next'] = block['prev_block']
            fout.write(json.dumps(blocks))
