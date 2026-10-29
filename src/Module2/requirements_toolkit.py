"""Small independent requirements exporter for the Module 2 course demo.

Not the official university `requirements_toolkit`; the course's original
Python toolkit was not included in the attached templates.
"""
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent

def export():
    spec=json.loads((HERE/'specification.json').read_text(encoding='utf-8'))
    out=HERE/'artifacts';out.mkdir(exist_ok=True)
    frs=spec['requirements'];tcs=spec['test_cases'];ucs=spec['use_cases']
    traced={f['id']:[t['id'] for t in tcs if t['fr']==f['id']] for f in frs}
    missing=[fid for fid,ids in traced.items() if not ids]
    (out/'requirements.json').write_text(json.dumps(frs,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# Module 2 — SRS Skeleton (draft)','',f"**System:** {spec['project']}",
           '**Note:** This is a student-written exporter, not the official course toolkit.','',
           '## Functional Requirements','']
    for f in frs:
        lines.extend([f"### {f['id']} — {f['f']}",f['en'],f"Related use case: {f['uc']}",f"Priority: {f['priority']}",''])
    lines.extend(['## Non-functional Requirements',''])
    for n in spec['nfr']:lines.extend([f"- {n['id']}: {n['en']}",''])
    lines.extend(['## Use Cases',''])
    for u in ucs:lines.extend([f"- {u['id']}: {u['en']}",''])
    (out/'srs_skeleton.md').write_text('\n'.join(lines),encoding='utf-8')
    summary=['MODULE 2 — RTM COVERAGE REPORT',f"Functional requirements: {len(frs)}",
             f"Use cases: {len(ucs)}",f"Designed test cases: {len(tcs)}",
             f"Requirements linked to tests: {len(traced)-len(missing)}/{len(frs)}",
             f"Design traceability coverage: {(len(traced)-len(missing))/len(frs):.0%}",
             'Integrated execution: NOT RUN (not a pass rate)','', 'FR -> UC -> Test Case']
    for f in frs:summary.append(f"{f['id']} -> {f['uc']} -> {', '.join(traced[f['id']]) or 'MISSING'}")
    if missing:summary.extend(['','Missing: '+', '.join(missing)])
    (out/'coverage_report.txt').write_text('\n'.join(summary)+'\n',encoding='utf-8')
    print('\n'.join(summary[:7]))
    return len(missing)==0

if __name__=='__main__':
    raise SystemExit(0 if export() else 1)
