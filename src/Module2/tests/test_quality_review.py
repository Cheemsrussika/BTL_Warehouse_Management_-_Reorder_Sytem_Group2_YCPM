"""Supplementary tests from module-specific requirement validation; not part of the 24 designed TC register."""
import tempfile
import unittest
from pathlib import Path
from app import setup_database, get_connection, transact, scan_code


class QualityReview(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "qa.sqlite"
        setup_database(self.db_path)
        self.con = get_connection(self.db_path)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_same_lot_across_two_products_is_ambiguous(self):
        self.con.execute("INSERT INTO stock VALUES('SKU002','LOT-OLD','B-01','2026-08-01',NULL,'AVAILABLE',1)")
        result, row = transact(self.con, scan_code, {'code': 'LOT-OLD', 'task_id': 'QA-01'})
        self.assertEqual(result, 'AMBIGUOUS')
        self.assertIsNone(row)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM scan_counts WHERE task_id='QA-01'").fetchone()[0], 0)

    def test_expected_sku_resolves_shared_lot(self):
        self.con.execute("INSERT INTO stock VALUES('SKU002','LOT-OLD','B-01','2026-08-01',NULL,'AVAILABLE',1)")
        result, row = transact(self.con, scan_code, {'code': 'LOT-OLD', 'expected_sku': 'SKU002', 'task_id': 'QA-02'})
        self.assertEqual((result, row['sku']), ('MATCH','SKU002'))
        self.assertEqual(self.con.execute("SELECT count FROM scan_counts WHERE task_id='QA-02'").fetchone()[0],1)


if __name__ == '__main__':
    unittest.main()
