"""24 runnable unit checks aligned with TC-201..TC-224 (standalone demo only)."""
import json
import tempfile
import unittest
from pathlib import Path
from app import (RuleError,setup_database,get_connection,transact,create_receipt,confirm_receipt,
                 create_issue,confirm_issue,scan_code,create_return,confirm_return,
                 create_transfer,confirm_transfer,allocate)

RECEIPT={'po':'PO-1001','sku':'SKU001','lot':'LOT-TEST','bin_id':'A-01','qty':'5','expiry_date':'2027-12-31'}
ISSUE={'sku':'SKU001','qty':'6','method':'FIFO','destination':'Customer'}
RETURN={'sku':'SKU001','lot':'LOT-OLD','bin_id':'A-01','qty':'2','reason':'Customer returned'}
TRANSFER={'sku':'SKU001','lot':'LOT-OLD','source_bin':'A-01','dest_bin':'B-01','qty':'3'}

class Module2Tests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.path=Path(self.t.name)/'demo.db'
        setup_database(self.path)
        self.c=get_connection(self.path)
    def tearDown(self):
        self.c.close();self.t.cleanup()
    def execute(self,fn,*args):
        return transact(self.c,fn,*args)
    def stock_qty(self,sku,lot,bin_id,condition='AVAILABLE'):
        row=self.c.execute('SELECT qty FROM stock WHERE sku=? AND lot=? AND bin_id=? AND condition=?',
                           (sku,lot,bin_id,condition)).fetchone()
        return row['qty'] if row else 0

    def test_TC_201_valid_receipt_draft(self):
        idx=self.execute(create_receipt,RECEIPT)
        self.assertEqual(self.c.execute('SELECT status FROM receipts WHERE id=?',(idx,)).fetchone()[0],'DRAFT')
        self.assertEqual(self.stock_qty('SKU001','LOT-TEST','A-01'),0)
    def test_TC_202_confirm_receipt(self):
        idx=self.execute(create_receipt,RECEIPT);self.execute(confirm_receipt,idx)
        self.assertEqual(self.stock_qty('SKU001','LOT-TEST','A-01'),5)
    def test_TC_203_reject_excess_receipt(self):
        with self.assertRaises(RuleError):self.execute(create_receipt,{**RECEIPT,'qty':'101'})
    def test_TC_204_valid_issue_draft(self):
        idx=self.execute(create_issue,ISSUE)
        row=self.c.execute('SELECT status,destination FROM issues WHERE id=?',(idx,)).fetchone()
        self.assertEqual((row['status'],row['destination']),('DRAFT','Customer'))
    def test_TC_205_confirm_issue(self):
        idx=self.execute(create_issue,ISSUE);self.execute(confirm_issue,idx)
        self.assertEqual(self.stock_qty('SKU001','LOT-OLD','A-01'),24)
    def test_TC_206_reject_issue_excess(self):
        idx=self.execute(create_issue,{**ISSUE,'qty':'999'})
        with self.assertRaises(RuleError):self.execute(confirm_issue,idx)
        self.assertEqual(self.stock_qty('SKU001','LOT-OLD','A-01'),30)
    def test_TC_207_scan_valid_code(self):
        result,prod=self.execute(scan_code,{'code':'8930000000001'})
        self.assertEqual((result,prod['sku']),('MATCH','SKU001'))
    def test_TC_208_scan_unknown(self):
        result,prod=self.execute(scan_code,{'code':'unknown'})
        self.assertEqual((result,prod),('NOT_FOUND',None))
    def test_TC_209_count_scans(self):
        for _ in range(3): self.execute(scan_code,{'code':'SKU001','expected_sku':'SKU001','task_id':'CHECK-01','expected_qty':'3'})
        self.assertEqual(self.c.execute('SELECT count FROM scan_counts WHERE task_id="CHECK-01"').fetchone()[0],3)
    def test_TC_210_create_return(self):
        idx=self.execute(create_return,RETURN)
        self.assertEqual(self.c.execute('SELECT status FROM returns WHERE id=?',(idx,)).fetchone()[0],'DRAFT')
    def test_TC_211_reject_invalid_return_quantity(self):
        with self.assertRaises(RuleError):self.execute(create_return,{**RETURN,'qty':'0'})
    def test_TC_212_classify_return(self):
        idx=self.execute(create_return,RETURN);self.execute(confirm_return,idx,'QUARANTINE')
        self.assertEqual(self.stock_qty('SKU001','LOT-OLD','A-01','QUARANTINE'),2)
        self.assertEqual(self.stock_qty('SKU001','LOT-OLD','A-01'),30)
    def test_TC_213_create_transfer(self):
        idx=self.execute(create_transfer,TRANSFER)
        self.assertEqual(self.c.execute('SELECT status FROM transfers WHERE id=?',(idx,)).fetchone()[0],'DRAFT')
    def test_TC_214_confirm_transfer(self):
        idx=self.execute(create_transfer,TRANSFER);self.execute(confirm_transfer,idx)
        self.assertEqual(self.stock_qty('SKU001','LOT-OLD','A-01'),27)
        self.assertEqual(self.stock_qty('SKU001','LOT-OLD','B-01'),3)
    def test_TC_215_duplicate_transfer(self):
        idx=self.execute(create_transfer,TRANSFER);self.execute(confirm_transfer,idx)
        with self.assertRaises(RuleError):self.execute(confirm_transfer,idx)
        self.assertEqual(self.stock_qty('SKU001','LOT-OLD','B-01'),3)
    def test_TC_216_reject_full_destination(self):
        idx=self.execute(create_transfer,{**TRANSFER,'lot':'LOT-NEW','dest_bin':'C-01','qty':'35'})
        with self.assertRaisesRegex(RuleError,'capacity'):self.execute(confirm_transfer,idx)
    def test_TC_217_authorized_transfer(self):
        idx=self.execute(create_transfer,TRANSFER);self.execute(confirm_transfer,idx,'MANAGER')
        self.assertEqual(self.stock_qty('SKU001','LOT-OLD','B-01'),3)
    def test_TC_218_unauthorized_transfer(self):
        idx=self.execute(create_transfer,TRANSFER)
        with self.assertRaises(RuleError):self.execute(confirm_transfer,idx,'GUEST')
        self.assertEqual(self.stock_qty('SKU001','LOT-OLD','A-01'),30)
    def test_TC_219_fifo_oldest_first(self):
        self.assertEqual(allocate(self.c,'SKU001',10,'FIFO')[0]['lot'],'LOT-OLD')
    def test_TC_220_fifo_skip_quarantine(self):
        self.c.execute('INSERT INTO stock VALUES(?,?,?,?,?,?,?)',('SKU001','LOT-QUAR','X-01','2026-01-01','2027-01-01','QUARANTINE',5))
        self.assertEqual(allocate(self.c,'SKU001',5,'FIFO')[0]['lot'],'LOT-OLD')
    def test_TC_221_fifo_across_batches(self):
        a=allocate(self.c,'SKU001',40,'FIFO')
        self.assertEqual([(x['lot'],x['qty']) for x in a],[('LOT-OLD',30),('LOT-NEW',10)])
    def test_TC_222_fefo_nearest_expiry(self):
        self.assertEqual(allocate(self.c,'SKU001',10,'FEFO')[0]['lot'],'LOT-NEW')
    def test_TC_223_fefo_skip_expired(self):
        self.c.execute('INSERT INTO stock VALUES(?,?,?,?,?,?,?)',('SKU001','LOT-EXPIRED','X-01','2026-01-01','2026-08-01','AVAILABLE',5))
        self.assertEqual(allocate(self.c,'SKU001',5,'FEFO')[0]['lot'],'LOT-NEW')
    def test_TC_224_fefo_tie_received_first(self):
        self.c.execute('INSERT INTO stock VALUES(?,?,?,?,?,?,?)',('SKU001','LOT-EARLY','X-01','2026-01-01','2027-03-01','AVAILABLE',5))
        a=allocate(self.c,'SKU001',10,'FEFO')
        self.assertEqual([(x['lot'],x['qty']) for x in a],[('LOT-EARLY',5),('LOT-NEW',5)])

if __name__=='__main__':unittest.main()
