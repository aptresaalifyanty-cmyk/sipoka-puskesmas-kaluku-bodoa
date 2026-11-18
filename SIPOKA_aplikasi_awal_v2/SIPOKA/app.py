import os, sqlite3, hashlib, secrets, json
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, g

UNITS = ['IGD', 'Poli Umum', 'Poli Gigi', 'Ruang Farmasi', 'PUSTU', 'Loket', 'Poli KIA/KB', 'Poli MTBS', 'Gizi', 'Kesling', 'Posyandu', 'CKG', 'Posyandu Lansia', 'P3K']
APP_SECRET = os.environ.get("APP_SECRET", "GANTI_DENGAN_SECRET_PANJANG_SEBELUM_DEPLOY")
DB_PATH = os.environ.get("SIPOKA_DB", "sipoka.db")
app = Flask(__name__)
app.secret_key = APP_SECRET

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()

def hash_pin(pin, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 200000).hex()
    return salt, digest

def verify_pin(pin, salt, digest):
    return secrets.compare_digest(hash_pin(pin, salt)[1], digest)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, full_name TEXT NOT NULL,
      role TEXT NOT NULL CHECK(role IN ('admin','farmasi','unit','pimpinan')),
      unit_name TEXT, pin_salt TEXT NOT NULL, pin_hash TEXT NOT NULL, active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS items(
      id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT NOT NULL, category TEXT NOT NULL,
      unit TEXT NOT NULL, stock REAL NOT NULL DEFAULT 0, min_stock REAL NOT NULL DEFAULT 0,
      active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS requests(
      id INTEGER PRIMARY KEY, request_no TEXT UNIQUE NOT NULL, user_id INTEGER NOT NULL,
      unit_name TEXT NOT NULL, requested_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Menunggu',
      note TEXT, verified_by INTEGER, verified_at TEXT, distribution_note TEXT,
      FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(verified_by) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS request_lines(
      id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, item_id INTEGER NOT NULL,
      qty_requested REAL NOT NULL, qty_approved REAL,
      FOREIGN KEY(request_id) REFERENCES requests(id) ON DELETE CASCADE,
      FOREIGN KEY(item_id) REFERENCES items(id)
    );
    CREATE TABLE IF NOT EXISTS distributions(
      id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, item_id INTEGER NOT NULL,
      qty REAL NOT NULL, distributed_at TEXT NOT NULL, distributed_by INTEGER NOT NULL,
      received_by TEXT NOT NULL,
      FOREIGN KEY(request_id) REFERENCES requests(id),
      FOREIGN KEY(item_id) REFERENCES items(id),
      FOREIGN KEY(distributed_by) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS stock_log(
      id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL, change_qty REAL NOT NULL,
      reason TEXT NOT NULL, ref TEXT, created_at TEXT NOT NULL, user_id INTEGER NOT NULL,
      FOREIGN KEY(item_id) REFERENCES items(id), FOREIGN KEY(user_id) REFERENCES users(id)
    );
    """)
    # Create initial admin only on first run; change PIN immediately after login.
    existing = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    if not existing:
        salt, digest = hash_pin(os.environ.get("SIPOKA_ADMIN_PIN", "123456"))
        conn.execute("INSERT INTO users(username,full_name,role,unit_name,pin_salt,pin_hash) VALUES(?,?,?,?,?,?)",
                     ("admin","Administrator SIPOKA","admin","Farmasi",salt,digest))
    # Load the supplied medicine/BMHP master list only when the item table is empty.
    item_count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    if item_count == 0:
        seed_path = os.path.join(os.path.dirname(__file__), "data_obat_bmhp.json")
        if os.path.exists(seed_path):
            with open(seed_path, encoding="utf-8") as source:
                seed_items = json.load(source)
            for item in seed_items:
                conn.execute("INSERT OR IGNORE INTO items(code,name,category,unit,stock,min_stock) VALUES(?,?,?,?,0,0)",
                             (None, item["name"], "Belum diklasifikasi", item["unit"]))
    conn.commit()
    conn.close()

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def roles_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get("user_id"):
                return redirect(url_for("login"))
            if session.get("role") not in roles:
                flash("Anda tidak memiliki akses untuk halaman tersebut.", "error")
                return redirect(url_for("dashboard"))
            return fn(*args, **kwargs)
        return wrapper
    return deco

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        pin = request.form.get("pin","").strip()
        user = db().execute("SELECT * FROM users WHERE username=? AND active=1",(username,)).fetchone()
        if user and verify_pin(pin, user["pin_salt"], user["pin_hash"]):
            session.clear()
            session.update(user_id=user["id"], username=user["username"], full_name=user["full_name"],
                           role=user["role"], unit_name=user["unit_name"])
            return redirect(url_for("dashboard"))
        flash("Username atau PIN tidak sesuai.", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def dashboard():
    conn = db()
    stats = {
      "pending": conn.execute("SELECT COUNT(*) FROM requests WHERE status='Menunggu'").fetchone()[0],
      "approved": conn.execute("SELECT COUNT(*) FROM requests WHERE status='Disetujui'").fetchone()[0],
      "items": conn.execute("SELECT COUNT(*) FROM items WHERE active=1").fetchone()[0],
      "low": conn.execute("SELECT COUNT(*) FROM items WHERE active=1 AND stock<=min_stock").fetchone()[0]
    }
    if session["role"] == "unit":
        rows = conn.execute("SELECT * FROM requests WHERE user_id=? ORDER BY id DESC LIMIT 10",(session["user_id"],)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM requests ORDER BY id DESC LIMIT 10").fetchall()
    return render_template("dashboard.html", stats=stats, rows=rows)

@app.route("/items", methods=["GET","POST"])
@login_required
def items():
    if request.method == "POST":
        if session["role"] not in ("admin","farmasi"):
            flash("Hanya petugas farmasi/admin yang dapat mengubah master barang.", "error")
            return redirect(url_for("items"))
        code=request.form.get("code","").strip() or None
        name=request.form.get("name","").strip()
        category=request.form.get("category","Obat")
        unit=request.form.get("unit","").strip()
        stock=float(request.form.get("stock",0) or 0)
        minimum=float(request.form.get("min_stock",0) or 0)
        if name and unit:
            try:
                cur=db().execute("INSERT INTO items(code,name,category,unit,stock,min_stock) VALUES(?,?,?,?,?,?)",
                                 (code,name,category,unit,stock,minimum))
                db().commit()
                db().execute("INSERT INTO stock_log(item_id,change_qty,reason,ref,created_at,user_id) VALUES(?,?,?,?,?,?)",
                             (cur.lastrowid,stock,"Stok awal","Inisialisasi",datetime.now().isoformat(timespec="seconds"),session["user_id"]))
                db().commit()
                flash("Barang berhasil ditambahkan.", "success")
            except sqlite3.IntegrityError:
                flash("Kode barang sudah digunakan.", "error")
        return redirect(url_for("items"))
    rows=db().execute("SELECT * FROM items WHERE active=1 ORDER BY category,name").fetchall()
    return render_template("items.html", rows=rows)

@app.route("/request/new", methods=["GET","POST"])
@roles_required("unit","admin")
def new_request():
    conn=db()
    item_rows=conn.execute("SELECT * FROM items WHERE active=1 ORDER BY category,name").fetchall()
    if request.method=="POST":
        item_ids=request.form.getlist("item_id")
        quantities=request.form.getlist("qty")
        valid=[]
        for iid, qty in zip(item_ids, quantities):
            try:
                q=float(qty)
                if q>0 and conn.execute("SELECT id FROM items WHERE id=? AND active=1",(iid,)).fetchone():
                    valid.append((int(iid),q))
            except ValueError:
                pass
        if not valid:
            flash("Masukkan minimal satu barang dengan jumlah lebih dari nol.", "error")
            return redirect(url_for("new_request"))
        unit=session.get("unit_name") or request.form.get("unit_name","Unit")
        cur=conn.execute("INSERT INTO requests(request_no,user_id,unit_name,requested_at,note) VALUES(?,?,?,?,?)",
                         ("REQ-"+datetime.now().strftime("%Y%m%d%H%M%S"),session["user_id"],unit,
                          datetime.now().isoformat(timespec="seconds"),request.form.get("note","")))
        rid=cur.lastrowid
        for iid,q in valid:
            conn.execute("INSERT INTO request_lines(request_id,item_id,qty_requested) VALUES(?,?,?)",(rid,iid,q))
        conn.commit()
        flash("Permintaan berhasil dikirim ke farmasi.", "success")
        return redirect(url_for("request_detail", rid=rid))
    return render_template("new_request.html", items=item_rows,units=UNITS)

@app.route("/requests")
@login_required
def requests_list():
    if session["role"]=="unit":
        rows=db().execute("SELECT * FROM requests WHERE user_id=? ORDER BY id DESC",(session["user_id"],)).fetchall()
    else:
        rows=db().execute("SELECT * FROM requests ORDER BY id DESC").fetchall()
    return render_template("requests.html", rows=rows)

@app.route("/request/<int:rid>")
@login_required
def request_detail(rid):
    conn=db()
    req=conn.execute("SELECT r.*,u.full_name FROM requests r JOIN users u ON u.id=r.user_id WHERE r.id=?",(rid,)).fetchone()
    if not req: return "Permintaan tidak ditemukan",404
    if session["role"]=="unit" and req["user_id"]!=session["user_id"]: return "Akses ditolak",403
    lines=conn.execute("SELECT l.*,i.name,i.category,i.unit,i.stock FROM request_lines l JOIN items i ON i.id=l.item_id WHERE l.request_id=?",(rid,)).fetchall()
    return render_template("request_detail.html", req=req, lines=lines)

@app.route("/request/<int:rid>/verify", methods=["POST"])
@roles_required("admin","farmasi")
def verify_request(rid):
    conn=db()
    req=conn.execute("SELECT * FROM requests WHERE id=?",(rid,)).fetchone()
    if not req or req["status"]!="Menunggu":
        flash("Permintaan tidak ditemukan atau sudah diproses.", "error")
        return redirect(url_for("requests_list"))
    lines=conn.execute("SELECT * FROM request_lines WHERE request_id=?",(rid,)).fetchall()
    for line in lines:
        try: approved=max(0,float(request.form.get("approved_"+str(line["id"]),0)))
        except ValueError: approved=0
        conn.execute("UPDATE request_lines SET qty_approved=? WHERE id=?",(approved,line["id"]))
    conn.execute("UPDATE requests SET status='Disetujui',verified_by=?,verified_at=?,distribution_note=? WHERE id=?",
                 (session["user_id"],datetime.now().isoformat(timespec="seconds"),request.form.get("note",""),rid))
    conn.commit()
    flash("Verifikasi tersimpan. Lanjutkan distribusi saat barang diserahkan.", "success")
    return redirect(url_for("request_detail",rid=rid))

@app.route("/request/<int:rid>/distribute", methods=["POST"])
@roles_required("admin","farmasi")
def distribute(rid):
    conn=db()
    req=conn.execute("SELECT * FROM requests WHERE id=?",(rid,)).fetchone()
    if not req or req["status"] not in ("Disetujui","Sebagian didistribusikan"):
        flash("Permintaan harus diverifikasi sebelum distribusi.", "error")
        return redirect(url_for("request_detail",rid=rid))
    lines=conn.execute("SELECT l.*,i.stock,i.name FROM request_lines l JOIN items i ON i.id=l.item_id WHERE l.request_id=?",(rid,)).fetchall()
    received=request.form.get("received_by","").strip()
    if not received:
        flash("Nama penerima wajib diisi.", "error")
        return redirect(url_for("request_detail",rid=rid))
    total=0
    for line in lines:
        already=conn.execute("SELECT COALESCE(SUM(qty),0) FROM distributions WHERE request_id=? AND item_id=?",(rid,line["item_id"])).fetchone()[0]
        remaining=max(0,(line["qty_approved"] or 0)-already)
        try: qty=float(request.form.get("dist_"+str(line["id"]),0) or 0)
        except ValueError: qty=0
        if qty<0 or qty>remaining or qty>line["stock"]:
            flash("Jumlah distribusi melebihi sisa persetujuan atau stok tersedia.", "error")
            return redirect(url_for("request_detail",rid=rid))
        if qty>0:
            conn.execute("INSERT INTO distributions(request_id,item_id,qty,distributed_at,distributed_by,received_by) VALUES(?,?,?,?,?,?)",
                         (rid,line["item_id"],qty,datetime.now().isoformat(timespec="seconds"),session["user_id"],received))
            conn.execute("UPDATE items SET stock=stock-? WHERE id=?",(qty,line["item_id"]))
            conn.execute("INSERT INTO stock_log(item_id,change_qty,reason,ref,created_at,user_id) VALUES(?,?,?,?,?,?)",
                         (line["item_id"],-qty,"Distribusi",req["request_no"],datetime.now().isoformat(timespec="seconds"),session["user_id"]))
            total+=qty
    if total:
        remaining=conn.execute("""SELECT COUNT(*) FROM request_lines l
          WHERE l.request_id=? AND COALESCE(l.qty_approved,0) >
          (SELECT COALESCE(SUM(d.qty),0) FROM distributions d WHERE d.request_id=l.request_id AND d.item_id=l.item_id)""",(rid,)).fetchone()[0]
        status="Sebagian didistribusikan" if remaining else "Selesai"
        conn.execute("UPDATE requests SET status=? WHERE id=?",(status,rid))
        conn.commit()
        flash("Distribusi berhasil dicatat dan stok diperbarui.", "success")
    else:
        flash("Tidak ada jumlah distribusi yang dimasukkan.", "error")
    return redirect(url_for("request_detail",rid=rid))

@app.route("/reports")
@roles_required("admin","farmasi","pimpinan")
def reports():
    rows=db().execute("""SELECT d.distributed_at,r.request_no,r.unit_name,i.name,i.category,d.qty,i.unit,
        d.received_by,u.full_name AS officer
        FROM distributions d JOIN requests r ON r.id=d.request_id JOIN items i ON i.id=d.item_id
        JOIN users u ON u.id=d.distributed_by ORDER BY d.id DESC""").fetchall()
    return render_template("reports.html",rows=rows)

@app.route("/users", methods=["GET","POST"])
@roles_required("admin")
def users():
    conn=db()
    if request.method=="POST":
        username=request.form.get("username","").strip()
        name=request.form.get("full_name","").strip()
        role=request.form.get("role","unit")
        unit=request.form.get("unit_name","").strip()
        pin=request.form.get("pin","").strip()
        if not username or not name or len(pin)<6 or not pin.isdigit():
            flash("Lengkapi data. PIN harus minimal 6 angka.", "error")
        else:
            salt,digest=hash_pin(pin)
            try:
                conn.execute("INSERT INTO users(username,full_name,role,unit_name,pin_salt,pin_hash) VALUES(?,?,?,?,?,?)",
                             (username,name,role,unit,salt,digest))
                conn.commit()
                flash("Akun berhasil dibuat.", "success")
            except sqlite3.IntegrityError:
                flash("Username sudah digunakan.", "error")
        return redirect(url_for("users"))
    rows=conn.execute("SELECT id,username,full_name,role,unit_name,active FROM users ORDER BY full_name").fetchall()
    return render_template("users.html",rows=rows,units=UNITS)

@app.route("/users/<int:uid>/toggle", methods=["POST"])
@roles_required("admin")
def toggle_user(uid):
    if uid==session["user_id"]:
        flash("Akun yang sedang digunakan tidak dapat dinonaktifkan.", "error")
    else:
        db().execute("UPDATE users SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?",(uid,))
        db().commit()
        flash("Status akun diperbarui.", "success")
    return redirect(url_for("users"))

@app.route("/change-pin", methods=["GET","POST"])
@login_required
def change_pin():
    if request.method=="POST":
        old=request.form.get("old_pin","")
        new=request.form.get("new_pin","")
        user=db().execute("SELECT * FROM users WHERE id=?",(session["user_id"],)).fetchone()
        if not verify_pin(old,user["pin_salt"],user["pin_hash"]):
            flash("PIN lama salah.", "error")
        elif not new.isdigit() or len(new)<6:
            flash("PIN baru minimal 6 angka.", "error")
        else:
            salt,digest=hash_pin(new)
            db().execute("UPDATE users SET pin_salt=?,pin_hash=? WHERE id=?",(salt,digest,session["user_id"]))
            db().commit()
            flash("PIN berhasil diubah.", "success")
            return redirect(url_for("dashboard"))
    return render_template("change_pin.html")

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)), debug=False)
