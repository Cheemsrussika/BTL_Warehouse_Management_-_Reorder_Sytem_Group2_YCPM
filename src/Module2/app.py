"""Warehouse Inventory and Reorder System - Module 2 demo.

Student project: Flask + SQLite. All quantities are integer units.
This is a teaching demo, not a production warehouse system.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date
from pathlib import Path
try:
    from flask import Flask, flash, redirect, render_template, request, url_for, jsonify
except ImportError:
    Flask = None  # Business logic and demo_cli.py work without Flask.

BASE_DIR = Path(__file__).resolve().parent


class RuleError(ValueError):
    """A user action violates a documented business rule."""


def get_connection(db_path):
    db = sqlite3.connect(str(db_path), timeout=5, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=5000')
    return db


def setup_database(db_path, seed=True):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = get_connection(db_path)
    try:
        con.executescript('''
            CREATE TABLE IF NOT EXISTS products (
              sku TEXT PRIMARY KEY, name TEXT NOT NULL, barcode TEXT UNIQUE NOT NULL,
              expiry_control INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS bins (
              bin_id TEXT PRIMARY KEY, capacity INTEGER NOT NULL CHECK(capacity>0),
              active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS purchase_orders (
              po TEXT PRIMARY KEY, sku TEXT NOT NULL REFERENCES products(sku),
              ordered_qty INTEGER NOT NULL, received_qty INTEGER NOT NULL DEFAULT 0,
              approved INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS stock (
              sku TEXT NOT NULL REFERENCES products(sku), lot TEXT NOT NULL,
              bin_id TEXT NOT NULL REFERENCES bins(bin_id), received_date TEXT NOT NULL,
              expiry_date TEXT, condition TEXT NOT NULL DEFAULT 'AVAILABLE',
              qty INTEGER NOT NULL CHECK(qty>=0),
              PRIMARY KEY(sku,lot,bin_id,condition)
            );
            CREATE TABLE IF NOT EXISTS receipts (
              id INTEGER PRIMARY KEY AUTOINCREMENT, po TEXT NOT NULL REFERENCES purchase_orders(po),
              sku TEXT NOT NULL REFERENCES products(sku), lot TEXT NOT NULL,
              bin_id TEXT NOT NULL REFERENCES bins(bin_id), qty INTEGER NOT NULL,
              expiry_date TEXT, status TEXT NOT NULL DEFAULT 'DRAFT'
            );
            CREATE TABLE IF NOT EXISTS issues (
              id INTEGER PRIMARY KEY AUTOINCREMENT, sku TEXT NOT NULL REFERENCES products(sku),
              qty INTEGER NOT NULL, method TEXT NOT NULL, destination TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT',
              allocations TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS returns (
              id INTEGER PRIMARY KEY AUTOINCREMENT, sku TEXT NOT NULL REFERENCES products(sku),
              lot TEXT NOT NULL, bin_id TEXT NOT NULL REFERENCES bins(bin_id),
              qty INTEGER NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT',
              inspection TEXT
            );
            CREATE TABLE IF NOT EXISTS transfers (
              id INTEGER PRIMARY KEY AUTOINCREMENT, sku TEXT NOT NULL REFERENCES products(sku),
              lot TEXT NOT NULL, source_bin TEXT NOT NULL REFERENCES bins(bin_id),
              dest_bin TEXT NOT NULL REFERENCES bins(bin_id), qty INTEGER NOT NULL,
              status TEXT NOT NULL DEFAULT 'DRAFT'
            );
            CREATE TABLE IF NOT EXISTS scans (
              id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL, sku TEXT,
              expected_sku TEXT, task_id TEXT, result TEXT NOT NULL,
              scanned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS scan_counts (
              task_id TEXT NOT NULL, sku TEXT NOT NULL REFERENCES products(sku),
              count INTEGER NOT NULL DEFAULT 0, expected_qty INTEGER, PRIMARY KEY(task_id,sku)
            );
            CREATE TABLE IF NOT EXISTS movements (
              id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL, sku TEXT NOT NULL,
              qty INTEGER NOT NULL, source_bin TEXT, dest_bin TEXT, lot TEXT,
              reference TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        if seed and con.execute('SELECT COUNT(*) FROM products').fetchone()[0] == 0:
            con.execute('BEGIN IMMEDIATE')
            try:
                con.executemany('INSERT INTO products VALUES(?,?,?,?)', [
                    ('SKU001','Instant Noodles','8930000000001',1),
                    ('SKU002','Notebook A5','8930000000002',0),
                    ('SKU003','Milk Carton','8930000000003',1),
                ])
                con.executemany('INSERT INTO bins VALUES(?,?,?)', [
                    ('A-01',300,1),('B-01',120,1),('C-01',50,1),('X-01',50,1),
                ])
                con.executemany('INSERT INTO purchase_orders VALUES(?,?,?,?,?)', [
                    ('PO-1001','SKU001',100,0,1),('PO-1002','SKU002',80,0,1),
                    ('PO-1003','SKU003',60,0,1),
                ])
                con.executemany('INSERT INTO stock VALUES(?,?,?,?,?,?,?)', [
                    ('SKU001','LOT-OLD','A-01','2026-08-01','2027-09-01','AVAILABLE',30),
                    ('SKU001','LOT-NEW','A-01','2026-09-01','2027-03-01','AVAILABLE',70),
                    ('SKU002','LOT-PAPER','B-01','2026-09-10',None,'AVAILABLE',40),
                    ('SKU003','LOT-MILK','C-01','2026-10-01','2026-12-01','AVAILABLE',20),
                ])
                con.commit()
            except Exception:
                con.rollback()
                raise
    finally:
        con.close()


def positive_qty(value):
    try:
        raw = str(value).strip()
        qty = int(raw)
        if raw != str(qty) or qty <= 0:
            raise ValueError()
        return qty
    except (ValueError, TypeError):
        raise RuleError('Quantity must be a positive whole number.')


def required(form, name):
    val = str(form.get(name,'')).strip()
    if not val:
        raise RuleError(f'{name} is required.')
    return val


def record_move(con,event,sku,qty,source,dest,lot,ref):
    con.execute('INSERT INTO movements(event,sku,qty,source_bin,dest_bin,lot,reference) VALUES(?,?,?,?,?,?,?)',
                (event,sku,qty,source,dest,lot,ref))


def product(con,sku):
    row = con.execute('SELECT * FROM products WHERE sku=?',(sku,)).fetchone()
    if not row:
        raise RuleError('Product does not exist.')
    return row


def bin_row(con,bin_id):
    row = con.execute('SELECT * FROM bins WHERE bin_id=? AND active=1',(bin_id,)).fetchone()
    if not row:
        raise RuleError('Storage bin does not exist or is inactive.')
    return row


def remaining_capacity(con,bin_id):
    b=bin_row(con,bin_id)
    filled=con.execute('SELECT COALESCE(SUM(qty),0) FROM stock WHERE bin_id=?',(bin_id,)).fetchone()[0]
    return b['capacity']-filled


def date_field(value, mandatory=False):
    value=str(value or '').strip()
    if not value:
        if mandatory: raise RuleError('Expiry date is required for this product.')
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise RuleError('Expiry date must be YYYY-MM-DD.')


def stock_add(con,sku,lot,bin_id,qty,received_date,expiry_date,condition='AVAILABLE'):
    row=con.execute('SELECT * FROM stock WHERE sku=? AND lot=? AND bin_id=? AND condition=?',
                    (sku,lot,bin_id,condition)).fetchone()
    # One physical lot code for a SKU must keep the same expiry/receiving date across bins.
    same_lot=con.execute('SELECT received_date,expiry_date FROM stock WHERE sku=? AND lot=? LIMIT 1',
                         (sku,lot)).fetchone()
    if same_lot and (same_lot['expiry_date'] != expiry_date):
        raise RuleError('Lot expiry conflicts with existing lot data.')
    if row:
        con.execute('UPDATE stock SET qty=qty+? WHERE sku=? AND lot=? AND bin_id=? AND condition=?',
                    (qty,sku,lot,bin_id,condition))
    else:
        con.execute('INSERT INTO stock VALUES(?,?,?,?,?,?,?)',
                    (sku,lot,bin_id, (same_lot['received_date'] if same_lot else received_date),
                     expiry_date,condition,qty))


def create_receipt(con,data):
    po=required(data,'po'); sku=required(data,'sku'); lot=required(data,'lot'); loc=required(data,'bin_id')
    qty=positive_qty(data.get('qty'))
    prod=product(con,sku); bin_row(con,loc)
    expiry=date_field(data.get('expiry_date'),bool(prod['expiry_control']))
    order=con.execute('SELECT * FROM purchase_orders WHERE po=? AND approved=1',(po,)).fetchone()
    if not order or order['sku'] != sku: raise RuleError('Approved purchase order and product must match.')
    if qty>order['ordered_qty']-order['received_qty']: raise RuleError('Quantity exceeds remaining purchase order.')
    if qty>remaining_capacity(con,loc): raise RuleError('Destination bin has insufficient capacity.')
    cur=con.execute('INSERT INTO receipts(po,sku,lot,bin_id,qty,expiry_date) VALUES(?,?,?,?,?,?)',
                    (po,sku,lot,loc,qty,expiry))
    return cur.lastrowid


def confirm_receipt(con,rid):
    row=con.execute('SELECT * FROM receipts WHERE id=?',(rid,)).fetchone()
    if not row: raise RuleError('Receipt not found.')
    if row['status']!='DRAFT': raise RuleError('Receipt already confirmed.')
    order=con.execute('SELECT * FROM purchase_orders WHERE po=?',(row['po'],)).fetchone()
    if order['approved']!=1 or order['sku'] != row['sku'] or row['qty']>order['ordered_qty']-order['received_qty']:
        raise RuleError('Purchase order is not valid for confirmation.')
    if row['qty']>remaining_capacity(con,row['bin_id']): raise RuleError('Destination bin is full.')
    if row['expiry_date'] and row['expiry_date']<date.today().isoformat():
        raise RuleError('Expired goods cannot be received as available stock.')
    stock_add(con,row['sku'],row['lot'],row['bin_id'],row['qty'],date.today().isoformat(),row['expiry_date'])
    con.execute("UPDATE receipts SET status='CONFIRMED' WHERE id=?",(rid,))
    con.execute('UPDATE purchase_orders SET received_qty=received_qty+? WHERE po=?',(row['qty'],row['po']))
    record_move(con,'RECEIPT',row['sku'],row['qty'],None,row['bin_id'],row['lot'],f'RC-{rid}')


def create_issue(con,data):
    sku=required(data,'sku'); qty=positive_qty(data.get('qty')); method=required(data,'method').upper()
    destination=required(data,'destination')
    product(con,sku)
    if method not in {'FIFO','FEFO'}: raise RuleError('Method must be FIFO or FEFO.')
    cur=con.execute('INSERT INTO issues(sku,qty,method,destination) VALUES(?,?,?,?)',(sku,qty,method,destination))
    return cur.lastrowid


def allocate(con,sku,qty,method):
    if method not in ('FIFO','FEFO'): raise RuleError('Unknown issue method.')
    # Demo policy: expired lots are not allowed, and FEFO requires expiry date.
    rows=con.execute("SELECT * FROM stock WHERE sku=? AND condition='AVAILABLE' AND qty>0",(sku,)).fetchall()
    rows=[r for r in rows if not r['expiry_date'] or r['expiry_date']>=date.today().isoformat()]
    if method=='FEFO':
        rows=[r for r in rows if r['expiry_date']]
        rows.sort(key=lambda r:(r['expiry_date'],r['received_date'],r['lot'],r['bin_id']))
    else:
        rows.sort(key=lambda r:(r['received_date'],r['lot'],r['bin_id']))
    remaining=qty; allocations=[]
    for row in rows:
        take=min(remaining,row['qty'])
        if take:
            allocations.append({'sku':sku,'lot':row['lot'],'bin_id':row['bin_id'],'qty':take,
                                'expiry_date':row['expiry_date'],'received_date':row['received_date']})
        remaining-=take
        if remaining==0: break
    if remaining:
        raise RuleError(f'Insufficient eligible stock: missing {remaining} unit(s).')
    return allocations


def confirm_issue(con,iid):
    row=con.execute('SELECT * FROM issues WHERE id=?',(iid,)).fetchone()
    if not row: raise RuleError('Issue not found.')
    if row['status']!='DRAFT': raise RuleError('Issue already confirmed.')
    plan=allocate(con,row['sku'],row['qty'],row['method'])
    for a in plan:
        result=con.execute("UPDATE stock SET qty=qty-? WHERE sku=? AND lot=? AND bin_id=? AND condition='AVAILABLE' AND qty>=?",
                     (a['qty'],row['sku'],a['lot'],a['bin_id'],a['qty']))
        if result.rowcount!=1: raise RuleError('Stock changed. Please retry.')
        record_move(con,'ISSUE',row['sku'],a['qty'],a['bin_id'],None,a['lot'],f'IS-{iid}')
    con.execute("UPDATE issues SET status='CONFIRMED', allocations=? WHERE id=?",(json.dumps(plan),iid))


def scan_code(con,data):
    code=required(data,'code'); expected=str(data.get('expected_sku','')).strip(); task=str(data.get('task_id','')).strip()
    # SKU and registered barcodes identify a product directly. A lot ID alone
    # may belong to several SKUs; never arbitrarily take the first one.
    candidates=con.execute('SELECT * FROM products WHERE sku=? OR barcode=?',(code,code)).fetchall()
    if not candidates:
        candidates=con.execute("SELECT DISTINCT p.* FROM products p JOIN stock s ON p.sku=s.sku WHERE s.lot=?",(code,)).fetchall()
    if len(candidates)>1 and expected:
        candidates=[p for p in candidates if p['sku']==expected]
    ambiguous=len(candidates)>1
    matched=candidates[0] if len(candidates)==1 else None
    valid=bool(matched and (not expected or matched['sku']==expected))
    expected_qty=data.get('expected_qty')
    if expected_qty not in (None,''):
        expected_qty=positive_qty(expected_qty)
    else: expected_qty=None
    outcome='MATCH' if valid else ('AMBIGUOUS' if ambiguous else ('MISMATCH' if matched else 'NOT_FOUND'))
    con.execute('INSERT INTO scans(code,sku,expected_sku,task_id,result) VALUES(?,?,?,?,?)',
                (code,matched['sku'] if matched else None,expected or None,task or None,outcome))
    if valid and task:
        con.execute('''INSERT INTO scan_counts(task_id,sku,count,expected_qty) VALUES(?,?,1,?)
                        ON CONFLICT(task_id,sku) DO UPDATE SET count=count+1,
                        expected_qty=COALESCE(scan_counts.expected_qty,excluded.expected_qty)''',
                    (task,matched['sku'],expected_qty))
    return outcome,matched


def create_return(con,data):
    sku=required(data,'sku'); lot=required(data,'lot'); loc=required(data,'bin_id'); reason=required(data,'reason')
    qty=positive_qty(data.get('qty')); product(con,sku);bin_row(con,loc)
    cur=con.execute('INSERT INTO returns(sku,lot,bin_id,qty,reason) VALUES(?,?,?,?,?)',
                    (sku,lot,loc,qty,reason))
    return cur.lastrowid


def confirm_return(con,rid,inspection):
    row=con.execute('SELECT * FROM returns WHERE id=?',(rid,)).fetchone()
    if not row: raise RuleError('Return not found.')
    if row['status']!='DRAFT': raise RuleError('Return already confirmed.')
    if inspection not in ('AVAILABLE','QUARANTINE'): raise RuleError('Inspection must be AVAILABLE or QUARANTINE.')
    if row['qty']>remaining_capacity(con,row['bin_id']): raise RuleError('Destination bin is full.')
    prev=con.execute('SELECT * FROM stock WHERE sku=? AND lot=? LIMIT 1',(row['sku'],row['lot'])).fetchone()
    if inspection=='AVAILABLE' and not prev: raise RuleError('Unknown lot cannot be returned to available stock.')
    expiry=prev['expiry_date'] if prev else None
    if inspection=='AVAILABLE' and expiry and expiry < date.today().isoformat():
        raise RuleError('Expired return must be quarantined.')
    stock_add(con,row['sku'],row['lot'],row['bin_id'],row['qty'],
              prev['received_date'] if prev else date.today().isoformat(),expiry,inspection)
    con.execute("UPDATE returns SET status='CONFIRMED', inspection=? WHERE id=?",(inspection,rid))
    record_move(con,'RETURN_'+inspection,row['sku'],row['qty'],None,row['bin_id'],row['lot'],f'RT-{rid}')


def create_transfer(con,data):
    sku=required(data,'sku');lot=required(data,'lot');src=required(data,'source_bin');dest=required(data,'dest_bin')
    qty=positive_qty(data.get('qty'))
    product(con,sku);bin_row(con,src);bin_row(con,dest)
    if src==dest:raise RuleError('Source and destination must be different.')
    cur=con.execute('INSERT INTO transfers(sku,lot,source_bin,dest_bin,qty) VALUES(?,?,?,?,?)',
                    (sku,lot,src,dest,qty))
    return cur.lastrowid


def validate_transfer(con,row):
    if row['status']!='DRAFT':raise RuleError('Transfer already confirmed.')
    bin_row(con,row['source_bin']);bin_row(con,row['dest_bin'])
    source=con.execute("SELECT * FROM stock WHERE sku=? AND lot=? AND bin_id=? AND condition='AVAILABLE'",
                       (row['sku'],row['lot'],row['source_bin'])).fetchone()
    if not source or source['qty']<row['qty']:raise RuleError('Not enough eligible stock in source bin.')
    if remaining_capacity(con,row['dest_bin'])<row['qty']:raise RuleError('Not enough capacity in destination bin.')
    return source


def confirm_transfer(con,tid,actor_role='STAFF'):
    if actor_role not in {'STAFF','MANAGER'}:
        raise RuleError('Only warehouse staff or managers can confirm a transfer.')
    row=con.execute('SELECT * FROM transfers WHERE id=?',(tid,)).fetchone()
    if not row: raise RuleError('Transfer not found.')
    source=validate_transfer(con,row)
    result=con.execute("UPDATE stock SET qty=qty-? WHERE sku=? AND lot=? AND bin_id=? AND condition='AVAILABLE' AND qty>=?",
                 (row['qty'],row['sku'],row['lot'],row['source_bin'],row['qty']))
    if result.rowcount!=1:raise RuleError('Stock changed during transfer.')
    stock_add(con,row['sku'],row['lot'],row['dest_bin'],row['qty'],source['received_date'],source['expiry_date'])
    con.execute("UPDATE transfers SET status='CONFIRMED' WHERE id=?",(tid,))
    record_move(con,'TRANSFER',row['sku'],row['qty'],row['source_bin'],row['dest_bin'],row['lot'],f'TR-{tid}')


def transact(con,action,*args):
    con.execute('BEGIN IMMEDIATE')
    try:
        result=action(con,*args)
        con.commit()
        return result
    except Exception:
        con.rollback()
        raise


def create_app(db_path=None):
    if Flask is None:
        raise RuntimeError('Flask is not installed. Use python demo_cli.py, or pip install -r requirements.txt first.')
    app=Flask(__name__)
    app.config.update(SECRET_KEY=os.environ.get('SECRET_KEY','dev-only-demo-not-production'),
                      DB_PATH=str(db_path or os.environ.get('WIRS_DB',BASE_DIR/'warehouse.db')))
    setup_database(app.config['DB_PATH'])

    @app.context_processor
    def add_global():
        return {'app_name':'WIRS · Module 2'}

    @app.route('/')
    def dashboard():
        with get_connection(app.config['DB_PATH']) as con:
            stocks=con.execute('''SELECT s.*,p.name FROM stock s JOIN products p ON s.sku=p.sku WHERE s.qty>0
                                  ORDER BY s.sku,s.lot,s.bin_id''').fetchall()
            moves=con.execute('SELECT * FROM movements ORDER BY id DESC LIMIT 12').fetchall()
            counters={x:con.execute(f'SELECT COUNT(*) FROM {x}').fetchone()[0] for x in ('receipts','issues','returns','transfers')}
        return render_template('dashboard.html',stocks=stocks,moves=moves,counters=counters)

    @app.route('/operations',methods=['GET','POST'])
    def operations():
        kind=request.values.get('kind','receipts')
        mapping={'receipts':(create_receipt,'Goods receipt created in DRAFT.'),
                 'issues':(create_issue,'Stock issue created in DRAFT.'),
                 'returns':(create_return,'Return created in DRAFT.'),
                 'transfers':(create_transfer,'Transfer created in DRAFT.')}
        if kind not in mapping: kind='receipts'
        if request.method=='POST':
            with get_connection(app.config['DB_PATH']) as con:
                try:
                    idx=transact(con,mapping[kind][0],request.form)
                    flash(f'{mapping[kind][1]} #{idx}','success')
                except RuleError as e:
                    flash(str(e),'error')
            return redirect(url_for('operations',kind=kind))
        with get_connection(app.config['DB_PATH']) as con:
            products=con.execute('SELECT * FROM products').fetchall()
            bins=con.execute('SELECT * FROM bins WHERE active=1').fetchall()
            orders=con.execute('SELECT * FROM purchase_orders').fetchall()
            rows=con.execute(f'SELECT * FROM {kind} ORDER BY id DESC LIMIT 30').fetchall()
            stock=con.execute('SELECT * FROM stock WHERE qty>0').fetchall()
        return render_template('operations.html',kind=kind,rows=rows,products=products,bins=bins,orders=orders,stock=stock)

    @app.post('/confirm/<kind>/<int:item_id>')
    def confirm(kind,item_id):
        actions={'receipts':confirm_receipt,'issues':confirm_issue,'transfers':confirm_transfer}
        with get_connection(app.config['DB_PATH']) as con:
            try:
                if kind=='returns':
                    transact(con,confirm_return,item_id,request.form.get('inspection','QUARANTINE'))
                elif kind in actions:
                    transact(con,actions[kind],item_id,request.form.get('role','STAFF')) if kind=='transfers' else transact(con,actions[kind],item_id)
                else: raise RuleError('Unknown operation.')
                flash(f'Operation #{item_id} confirmed.','success')
            except RuleError as e:flash(str(e),'error')
        return redirect(url_for('operations',kind=kind))

    @app.route('/scan',methods=['GET','POST'])
    def scan():
        info=None
        with get_connection(app.config['DB_PATH']) as con:
            if request.method=='POST':
                try:
                    outcome,row=transact(con,scan_code,request.form)
                    info=f'{outcome}: {row["sku"]} – {row["name"]}' if row else outcome
                    flash(info,'success' if outcome=='MATCH' else 'error')
                except RuleError as e: flash(str(e),'error')
            history=con.execute('SELECT * FROM scans ORDER BY id DESC LIMIT 20').fetchall()
            counts=con.execute('SELECT * FROM scan_counts ORDER BY task_id,sku').fetchall()
            products=con.execute('SELECT * FROM products').fetchall()
        return render_template('scan.html',history=history,counts=counts,products=products)

    @app.route('/preview',methods=['GET','POST'])
    def preview():
        result=[]
        with get_connection(app.config['DB_PATH']) as con:
            if request.method=='POST':
                try:
                    result=allocate(con,required(request.form,'sku'),positive_qty(request.form.get('qty')),
                                    required(request.form,'method'))
                    flash('Allocation preview generated. Stock has not changed.','success')
                except RuleError as e:flash(str(e),'error')
            prods=con.execute('SELECT * FROM products').fetchall()
        return render_template('preview.html',result=result,prods=prods)

    @app.get('/api/stock')
    def stock_api():
        with get_connection(app.config['DB_PATH']) as con:
            items=con.execute('SELECT * FROM stock ORDER BY sku,lot,bin_id').fetchall()
        return jsonify([dict(x) for x in items])

    @app.get('/health')
    def health():return {'status':'ok','module':'2'}

    return app


if __name__=='__main__':
    create_app().run(host='127.0.0.1',port=5000,debug=False)
