import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from utils import *
import numpy as np

results = {}
cols = ['txs', 'graphene', 'cmpct', 'xthin', 'unrecovered', 'n_txs', 'n_skipped']
n_blocks = 0
for f in os.listdir(DATADIR):
    if not 'results' in f:
        continue
    n_blocks += 1
    with open('%s/%s' %(DATADIR, f)) as fin:
        for line in fin:
            fields = [float(x.strip()) for x in line.split(',')]
            if fields[0] not in results:
                results[fields[0]] = {}
                for col in cols:
                    results[fields[0]][col] = []
            for j, col in enumerate(cols):
                results[fields[0]][col].append(fields[j + 1])

for col in cols[:4]:
    x = []
    y = []
    for k, v in results.items():
        x.append(k)
        y.append(np.average(v[col]) / 1024)
    print(x)
    print(y)
    if col == 'txs':
        label = 'Missing txs'
    else:
        label = col
    plt.plot(x, y, label=label)
    plt.ylabel("KB")  
    plt.xlabel("Mempool Similarity")
    plt.title("Bytes transferred averaged over %d bitcoin blocks" % n_blocks)
    plt.legend(loc='upper right')
    plt.savefig('mempool.png')

plt.clf()
x = []
y = []
for k, v in results.items():
    x.append(k)
    y.append(np.average(v['n_skipped']))
    plt.plot(x, y, label='missing transaction count')

plt.xlabel('Mempool Similarity')
plt.title('Number of missing transactions averaged over %d bitcoin blocks' % n_blocks)
plt.savefig('n_missing.png')
plt.clf()
