"""Smoke verification of eight demo workflows on a disposable SQLite file.

Does NOT execute the group's integrated application or sign off its test cases.
"""
import json
import tempfile
from datetime import datetime
from pathlib import Path
from app import (setup_database, get_connection, transact, create_receipt, confirm_receipt,
                 create_issue, confirm_issue, scan_code, create_return, confirm_return,
                 create_transfer, confirm_transfer, allocate)

BASE=Path(__file__).resolve().parent

def verify():
    events=[]
    with tempfile.TemporaryDirectory(prefix='wirs_module2_') as temp:
        db_path=Path(temp)/'demo_verify.db'
        setup_database(db_path)
        with get_connection(db_path) as con:
            def event(name, ok, note):
                events.append({'workflow':name,'ok':bool(ok),'note':note})
                if not ok:raise AssertionError(name+' failed: '+note)
            qty=lambda sku,lot,loc,state='AVAILABLE': con.execute('''SELECT COALESCE(SUM(qty),0) FROM stock
                WHERE sku=? AND lot=? AND bin_id=? AND condition=?''',(sku,lot,loc,state)).fetchone()[0]
            event('1. View stock', qty('SKU001','LOT-OLD','A-01')==30, 'Seeded available units: 30')
            rid=transact(con,create_receipt,{'po':'PO-1001','sku':'SKU001','lot':'LOT-QA','bin_id':'A-01', 'qty':'5','expiry_date':'2027-12-31'})
            transact(con,confirm_receipt,rid)
            event('2. Receive goods', qty('SKU001','LOT-QA','A-01')==5, 'Received +5 LOT-QA')
            iid=transact(con,create_issue,{'sku':'SKU001','qty':'4','method':'FIFO','destination':'Order'})
            transact(con,confirm_issue,iid)
            event('3. Issue goods',qty('SKU001','LOT-OLD','A-01')==26,'Issued 4 from earliest received LOT-OLD')
            status,prod=transact(con,scan_code,{'code':'8930000000001','expected_sku':'SKU001','task_id':'SMOKE'})
            event('4. Scan barcode', status=='MATCH' and prod['sku']=='SKU001','Registered barcode recognized')
            ret=transact(con,create_return,{'sku':'SKU001','lot':'LOT-OLD','bin_id':'A-01','qty':'2','reason':'Returned damaged'})
            transact(con,confirm_return,ret,'QUARANTINE')
            event('5. Return goods',qty('SKU001','LOT-OLD','A-01','QUARANTINE')==2,'2 returned units quarantined')
            tr=transact(con,create_transfer,{'sku':'SKU001','lot':'LOT-OLD','source_bin':'A-01','dest_bin':'B-01','qty':'3'})
            transact(con,confirm_transfer,tr)
            event('6. Bin transfer',qty('SKU001','LOT-OLD','B-01')==3,'Moved 3 LOT-OLD units A-01 -> B-01')
            fifo=allocate(con,'SKU001',2,'FIFO')
            fefo=allocate(con,'SKU001',2,'FEFO')
            event('7. FIFO/FEFO preview',fifo[0]['lot']=='LOT-OLD' and fefo[0]['lot']=='LOT-NEW','FIFO LOT-OLD; FEFO LOT-NEW')
            count=con.execute('SELECT COUNT(*) FROM movements').fetchone()[0]
            event('8. Movement history',count==4,'4 confirmed movement entries (receipt/issue/return/transfer)')
    return events

if __name__=='__main__':
    rows=verify()
    path=BASE/'artifacts'/'demo_smoke_report.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'generated_at':datetime.now().isoformat(timespec='seconds'),
        'scope':'Local standalone demo; not integrated team testing','results':rows},indent=2),encoding='utf-8')
    for row in rows:print(('OK' if row['ok'] else 'FAIL')+' | '+row['workflow']+' | '+row['note'])
    print(f'Completed {sum(r["ok"] for r in rows)}/{len(rows)} workflow checks. Written: {path}')
