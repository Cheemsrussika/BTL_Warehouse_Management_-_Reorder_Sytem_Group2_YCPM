"""Run the core Module 2 features using Python's standard library only."""
import sys
from pathlib import Path
from app import (RuleError,setup_database,get_connection,transact,create_receipt,confirm_receipt,
                 create_issue,confirm_issue,scan_code,create_return,confirm_return,create_transfer,
                 confirm_transfer,allocate)

DB_PATH=Path(__file__).with_name('warehouse.db')

def prompt(label, default=''):
    response=input(f'{label} [{default}]: ').strip()
    return response or default


def print_stock(con):
    print('\n SKU     LOT            BIN    QTY  CONDITION     EXPIRY')
    print(' ' + '-'*68)
    for r in con.execute('SELECT * FROM stock WHERE qty>0 ORDER BY sku, lot, bin_id'):
        print(f" {r['sku']:<7} {r['lot']:<14} {r['bin_id']:<6} {r['qty']:<4} {r['condition']:<13} {r['expiry_date'] or '-'}")


def main():
    setup_database(DB_PATH)
    print('WAREHOUSE INVENTORY AND REORDER SYSTEM — MODULE 2')
    print('Local demo (Python standard library + SQLite).')
    with get_connection(DB_PATH) as con:
        while True:
            print('\n1. Current stock  2. Goods receipt  3. Goods issue  4. Scan code')
            print('5. Goods return   6. Bin transfer   7. FIFO/FEFO preview  8. History  0. Exit')
            option=prompt('Select','1')
            try:
                if option=='0':break
                if option=='1':print_stock(con)
                elif option=='2':
                    data={'po':prompt('Purchase order','PO-1001'),'sku':prompt('SKU','SKU001'),
                          'lot':prompt('Lot','LOT-DEMO'),'bin_id':prompt('Bin','A-01'),
                          'qty':prompt('Quantity','5'),'expiry_date':prompt('Expiry (YYYY-MM-DD)','2027-12-31')}
                    rid=transact(con,create_receipt,data)
                    print(f'Draft receipt #{rid} created.')
                    if prompt('Confirm now? (y/n)','y').lower()=='y':
                        transact(con,confirm_receipt,rid);print('Receipt confirmed.')
                elif option=='3':
                    data={'sku':prompt('SKU','SKU001'),'qty':prompt('Quantity','5'),
                          'method':prompt('FIFO or FEFO','FIFO').upper(),
                          'destination':prompt('Destination','Customer order')}
                    iid=transact(con,create_issue,data)
                    print(f'Draft issue #{iid} created.')
                    if prompt('Confirm now? (y/n)','y').lower()=='y':
                        transact(con,confirm_issue,iid);print('Issue confirmed.')
                elif option=='4':
                    d={'code':prompt('Code (SKU / barcode / lot)','SKU001'),
                       'expected_sku':prompt('Expected SKU (blank = any)',''),
                       'task_id':prompt('Count task ID (blank = skip)','CHECK-01'),
                       'expected_qty':prompt('Expected count (optional)','')}
                    status,prod=transact(con,scan_code,d)
                    print(f"Scan result: {status}. {prod['sku'] if prod else ''}")
                elif option=='5':
                    d={'sku':prompt('SKU','SKU001'),'lot':prompt('Existing lot','LOT-OLD'),
                       'qty':prompt('Quantity','2'),'bin_id':prompt('Bin','A-01'),
                       'reason':prompt('Reason','Customer returned item')}
                    rid=transact(con,create_return,d);print(f'Draft return #{rid} created.')
                    if prompt('Confirm now? (y/n)','y').lower()=='y':
                        quality=prompt('AVAILABLE or QUARANTINE','QUARANTINE').upper()
                        transact(con,confirm_return,rid,quality);print('Return confirmed.')
                elif option=='6':
                    d={'sku':prompt('SKU','SKU001'),'lot':prompt('Lot','LOT-OLD'),
                       'source_bin':prompt('From','A-01'),'dest_bin':prompt('To','B-01'),
                       'qty':prompt('Quantity','3')}
                    tid=transact(con,create_transfer,d);print(f'Draft transfer #{tid} created.')
                    if prompt('Confirm now? (y/n)','y').lower()=='y':
                        transact(con,confirm_transfer,tid,prompt('Role STAFF or MANAGER','STAFF').upper());print('Transfer confirmed.')
                elif option=='7':
                    sku=prompt('SKU','SKU001');qty=int(prompt('Quantity','40'))
                    method=prompt('FIFO or FEFO','FIFO').upper()
                    plan=allocate(con,sku,qty,method)
                    for p in plan: print(f"Pick {p['qty']} x {p['sku']} from {p['lot']} at {p['bin_id']} (expiry {p['expiry_date']})")
                    print('Preview only: stock unchanged.')
                elif option=='8':
                    for r in con.execute('SELECT * FROM movements ORDER BY id DESC LIMIT 20'):
                        print(f"{r['created_at']} | {r['event']} | {r['sku']} | qty={r['qty']} | {r['reference']}")
                else:print('Unknown menu option.')
            except (RuleError,ValueError) as exc:
                print('ERROR:',exc)
    print('Goodbye!')

if __name__=='__main__':main()
