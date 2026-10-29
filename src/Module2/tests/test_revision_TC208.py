"""TC-208 revised-case regression: both UNKNOWN and shared lot ID."""
import tempfile
import unittest
from pathlib import Path
from app import setup_database, get_connection, transact, scan_code

class RevisedTC208(unittest.TestCase):
    def test_TC_208_unknown_and_ambiguous_lot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'tc208.db';setup_database(path)
            con=get_connection(path)
            try:
                # TWO different SKUs genuinely share exactly the LOT-SHARED code.
                con.execute("INSERT INTO stock VALUES('SKU001','LOT-SHARED','A-01','2026-10-01','2027-11-01','AVAILABLE',2)")
                con.execute("INSERT INTO stock VALUES('SKU003','LOT-SHARED','B-01','2026-10-02','2027-11-01','AVAILABLE',3)")
                a,p=transact(con,scan_code,{'code':'UNKNOWN-404','task_id':'TC-208'})
                self.assertEqual(a,'NOT_FOUND');self.assertIsNone(p)
                b,p=transact(con,scan_code,{'code':'LOT-SHARED','task_id':'TC-208'})
                self.assertEqual(b,'AMBIGUOUS');self.assertIsNone(p)
                cnt=con.execute("SELECT COALESCE(SUM(count),0) FROM scan_counts WHERE task_id='TC-208'").fetchone()[0]
                self.assertEqual(cnt,0)
            finally:
                con.close()
