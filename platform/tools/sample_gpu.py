"""Read-only sampled GPU telemetry; observations are not guaranteed true peaks."""
import argparse
import csv
import io
import json
from pathlib import Path
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument('--seconds', type=int, default=600)
args = parser.parse_args()
assert 1 <= args.seconds <= 1800
path = Path(__file__).resolve().parents[1] / 'verification' / 'gpu-samples.json'
report = {'scope': 'Observed during synthetic corpus confirmation and 10000-vector benchmark; sampled every 2s',
          'notice': 'Maximum observed sample is not a guaranteed peak; other desktop GPU use may be included', 'samples': []}
deadline = time.monotonic() + args.seconds
try:
    while time.monotonic() < deadline:
        result = subprocess.run(['nvidia-smi', '--query-gpu=timestamp,name,memory.used,memory.total,utilization.gpu',
                                 '--format=csv,noheader,nounits'], capture_output=True, text=True, check=True, timeout=10)
        for row in csv.reader(io.StringIO(result.stdout)):
            report['samples'].append({'timestamp': row[0].strip(), 'name': row[1].strip(),
                'used_mib': int(row[2]), 'total_mib': int(row[3]), 'utilization_percent': int(row[4])})
        report['max_observed_used_mib'] = max(row['used_mib'] for row in report['samples'])
        path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        time.sleep(2)
finally:
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'samples': len(report['samples']), 'max_observed_used_mib': report.get('max_observed_used_mib')}))
