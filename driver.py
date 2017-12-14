import os
from utils import *
import subprocess
import time

mempool_values = [0.999, 0.99, 0.95, 0.9, 0.75]

for f in os.listdir(DATADIR):
    if 'results' not in f:
        height = f.split('.')[0]
        if os.path.exists('%s/%s_results.json' % (DATADIR, height)):
            print("Found results file for %s. Skipping" % height)
            continue
        else:
            print("Computing values for block %s" % height)
            f = '%s/%s' % (DATADIR, f)
            for m in mempool_values:
                p1 = subprocess.Popen("python3 miner_without_block.py %s %f" % (f, m), 
                    shell=True)
                time.sleep(1)
                p2 = subprocess.Popen("python3 miner_with_block.py %s" % f,
                        shell=True)
                p1.communicate()
                p2.communicate()
