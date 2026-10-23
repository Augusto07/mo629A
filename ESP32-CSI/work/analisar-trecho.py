import csv, json
from pathlib import Path
import numpy as np
p=Path(r'C:\Users\vitor\.codex\attachments\951797fd-5d25-4703-b5ea-c1d834c7e0f6\Texto colado.txt')
rows=list(csv.DictReader(p.open(encoding='utf-8-sig')))
a=np.asarray([json.loads(r['data']) for r in rows],dtype=float)
t=np.asarray([int(r['local_timestamp']) for r in rows],dtype=np.int64)
dt=np.diff(t)/1000
rssi=np.asarray([int(r['rssi']) for r in rows])
amp=np.hypot(a[:,0::2],a[:,1::2])
mask=np.any(amp!=0,axis=0)
mask[:2]=False
m=amp[:,mask].mean(axis=1)
out={
 'samples':len(rows), 'id_first_last':[rows[0]['id'],rows[-1]['id']],
 'id_gaps':int(np.sum(np.diff([int(r['id']) for r in rows])!=1)),
 'duration_seconds':float((t[-1]-t[0])/1e6), 'rate_hz':float((len(rows)-1)/((t[-1]-t[0])/1e6)),
 'interval_ms':{'min':float(dt.min()),'median':float(np.median(dt)),'max':float(dt.max()),'p95':float(np.percentile(dt,95))},
 'rssi':{'min':int(rssi.min()),'max':int(rssi.max()),'mean':float(rssi.mean()),'std':float(rssi.std()),'first_half_mean':float(rssi[:len(rows)//2].mean()),'last_half_mean':float(rssi[len(rows)//2:].mean())},
 'unique_fields':{k:sorted(set(r[k] for r in rows)) for k in ['mac','channel','bandwidth','sig_mode','mcs','noise_floor','len','first_word','stbc','sgi']},
 'array_lengths':sorted(set(map(len,a))), 'invalid_first4_unique':np.unique(a[:,:4],axis=0).tolist(),
 'always_zero_complex_slots':np.flatnonzero(np.all(amp==0,axis=0)).tolist(),
 'valid_slots_used':int(mask.sum()),
 'mean_magnitude_arbitrary_units':{'min':float(m.min()),'max':float(m.max()),'mean':float(m.mean()),'std':float(m.std()),'first_half':float(m[:len(rows)//2].mean()),'last_half':float(m[len(rows)//2:].mean())}
}
print(json.dumps(out,ensure_ascii=False,indent=2))
