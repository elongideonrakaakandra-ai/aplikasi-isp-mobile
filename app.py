# ============================================================
#   APLIKASI ISP v1.9 - BDA CONNECTION
#   Versi Android (APK) - Flask + SQLite + MikroTik + WA Intent
# ============================================================

# ============================================================
#   LOGGING AWAL
# ============================================================
def _log(pesan):
    try:
        with open('startup.log', 'a', encoding='utf-8') as f:
            import datetime
            f.write(f"[{datetime.datetime.now()}] {pesan}\n")
    except:
        pass
    try:
        print(pesan)
    except:
        pass

_log("=" * 60)
_log("app.py: mulai load (versi Android)")

# ============================================================
#   IMPORT UTAMA
# ============================================================
try:
    import flask
    _log("app.py: flask OK")
except Exception as e:
    _log(f"app.py: flask GAGAL - {e}")
    raise

try:
    import routeros_api
    _log("app.py: routeros_api OK")
except Exception as e:
    _log(f"app.py: routeros_api GAGAL - {e}")
    raise

try:
    import sqlite3
    _log("app.py: sqlite3 OK")
except Exception as e:
    _log(f"app.py: sqlite3 GAGAL - {e}")
    raise

# WA helper (menggantikan pywhatkit untuk Android)
try:
    from mobile_wa import kirim_wa_intent
    _log("app.py: mobile_wa OK")
except Exception as e:
    _log(f"app.py: mobile_wa GAGAL - {e} - lanjut tanpa WA")
    kirim_wa_intent = None

_log("app.py: semua import OK, lanjut load")

from flask import Flask, render_template_string, request, redirect, send_from_directory, Response
import os
import sys
import time
import csv
import io
import shutil
import configparser
import threading
import webbrowser
import traceback
from datetime import datetime, date, timedelta
from urllib.parse import quote

app = Flask(__name__)

# ============================================================
#   PATH HANDLING
# ============================================================
def resource_path(relative):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative)
    return os.path.join(os.path.abspath('.'), relative)


def user_data_path(relative):
    # Di Android, main.py sudah chdir ke app_storage_path()
    # sehingga os.path.abspath('.') menunjuk ke folder data app.
    if hasattr(sys, '_MEIPASS'):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.abspath('.')
    return os.path.join(base, relative)


# ============================================================
#   BACA CONFIG.INI
# ============================================================
CONFIG_FILE = user_data_path('config.ini')
config = configparser.ConfigParser()

DEFAULT_CONFIG = {
    'mikrotik': {
        'ip': '192.168.88.1',
        'user': 'py-script',
        'pass': '12345678',
        'port': '8728',
    },
    'aplikasi': {
        'port_web': '5000',
        'auto_buka_browser': 'yes',
    }
}

if os.path.exists(CONFIG_FILE):
    config.read(CONFIG_FILE)
else:
    for section, values in DEFAULT_CONFIG.items():
        config[section] = values
    with open(CONFIG_FILE, 'w') as f:
        config.write(f)
    _log(f"OK Config baru dibuat: {CONFIG_FILE}")

for section, values in DEFAULT_CONFIG.items():
    if not config.has_section(section):
        config.add_section(section)
    for key, val in values.items():
        if not config.has_option(section, key):
            config.set(section, key, val)
with open(CONFIG_FILE, 'w') as f:
    config.write(f)

MIKROTIK_IP   = config.get('mikrotik', 'ip')
MIKROTIK_USER = config.get('mikrotik', 'user')
MIKROTIK_PASS = config.get('mikrotik', 'pass')
MIKROTIK_PORT = config.getint('mikrotik', 'port')

DB_FILE = user_data_path('isp.db')
BACKUP_DIR = user_data_path('backup')

# ============================================================
#   KONFIGURASI DEFAULT
# ============================================================
DEFAULT_PENGATURAN = {
    'nama_isp': 'BDA CONNECTION',
    'wa_admin': '6285856776447',
    'rekening': 'BCA 1234567890 a/n BDA Connection',
    'info': 'Pembayaran akan diverifikasi dalam 1x24 jam oleh admin.',
}

PAKET_BANDWIDTH = {
    '3Mbps'  : '3M/3M',
    '5Mbps'  : '5M/5M',
    '10Mbps' : '10M/10M',
    '20Mbps' : '20M/20M',
}

HARGA_PAKET = {
    '3Mbps'  : 100000,
    '5Mbps'  : 125000,
    '10Mbps' : 150000,
    '20Mbps' : 250000,
    'default': 0,
}

IP_LOCAL_PPPOE = '10.10.10.1'
IP_POOL_PPPOE  = 'pppoe-pool'
IP_RANGE_POOL  = '10.10.10.10-10.10.10.254'

PROFIL_ISOLIR = 'isolir'
RATE_LIMIT_ISOLIR = '64k/64k'


# ============================================================
#   DATABASE SQLITE
# ============================================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS pelanggan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama_pppoe TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            profil TEXT NOT NULL,
            nama_lengkap TEXT,
            alamat TEXT,
            telepon TEXT,
            harga INTEGER DEFAULT 0,
            tgl_jatuh_tempo TEXT,
            status TEXT DEFAULT 'aktif',
            tgl_isolir TEXT,
            dibuat_pada TEXT
        )
    """)
    c.execute("PRAGMA table_info(pelanggan)")
    kolom = [row[1] for row in c.fetchall()]
    if 'tgl_isolir' not in kolom:
        c.execute("ALTER TABLE pelanggan ADD COLUMN tgl_isolir TEXT")

    c.execute("""
        CREATE TABLE IF NOT EXISTS pengaturan (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    for key, val in DEFAULT_PENGATURAN.items():
        c.execute("SELECT value FROM pengaturan WHERE key = ?", (key,))
        if not c.fetchone():
            c.execute("INSERT INTO pengaturan (key, value) VALUES (?, ?)", (key, val))

    conn.commit()
    conn.close()
    _log(f"OK Database siap: {os.path.abspath(DB_FILE)}")


def db_query(query, params=(), fetch=None):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(query, params)
    if fetch == 'one':
        h = c.fetchone()
        conn.close()
        return dict(h) if h else None
    elif fetch == 'all':
        h = c.fetchall()
        conn.close()
        return [dict(r) for r in h]
    else:
        conn.commit()
        last_id = c.lastrowid
        conn.close()
        return last_id


def db_get_pelanggan_semua():
    return db_query("SELECT * FROM pelanggan ORDER BY nama_pppoe", fetch='all')


def db_get_pelanggan(nama_pppoe):
    return db_query("SELECT * FROM pelanggan WHERE nama_pppoe = ?",
                    (nama_pppoe,), fetch='one')


def db_tambah_pelanggan(nama_pppoe, password, profil, nama_lengkap,
                         alamat, telepon, harga, tgl_jatuh_tempo):
    return db_query("""
        INSERT INTO pelanggan
        (nama_pppoe, password, profil, nama_lengkap, alamat, telepon,
         harga, tgl_jatuh_tempo, status, dibuat_pada)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'aktif', ?)
    """, (nama_pppoe, password, profil, nama_lengkap, alamat, telepon,
          harga, tgl_jatuh_tempo, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))


def db_edit_pelanggan(nama_pppoe, password, profil, nama_lengkap,
                       alamat, telepon, harga, tgl_jatuh_tempo, status):
    db_query("""
        UPDATE pelanggan SET
            password = ?, profil = ?, nama_lengkap = ?, alamat = ?,
            telepon = ?, harga = ?, tgl_jatuh_tempo = ?, status = ?
        WHERE nama_pppoe = ?
    """, (password, profil, nama_lengkap, alamat, telepon, harga,
          tgl_jatuh_tempo, status, nama_pppoe))


def db_set_status(nama_pppoe, status, tgl_isolir=None):
    db_query("""
        UPDATE pelanggan SET status = ?, tgl_isolir = ?
        WHERE nama_pppoe = ?
    """, (status, tgl_isolir, nama_pppoe))


def db_hapus_pelanggan(nama_pppoe):
    db_query("DELETE FROM pelanggan WHERE nama_pppoe = ?", (nama_pppoe,))


# ============================================================
#   FUNGSI PENGATURAN
# ============================================================
def db_get_pengaturan(key, default=''):
    hasil = db_query("SELECT value FROM pengaturan WHERE key = ?", (key,), fetch='one')
    if hasil and hasil.get('value'):
        return hasil['value']
    return default


def db_set_pengaturan(key, value):
    ada = db_query("SELECT key FROM pengaturan WHERE key = ?", (key,), fetch='one')
    if ada:
        db_query("UPDATE pengaturan SET value = ? WHERE key = ?", (value, key))
    else:
        db_query("INSERT INTO pengaturan (key, value) VALUES (?, ?)", (key, value))


def get_nama_isp():
    return db_get_pengaturan('nama_isp', DEFAULT_PENGATURAN['nama_isp'])


def get_wa_admin():
    return db_get_pengaturan('wa_admin', DEFAULT_PENGATURAN['wa_admin'])


def get_rekening():
    return db_get_pengaturan('rekening', DEFAULT_PENGATURAN['rekening'])


def get_info_tambahan():
    return db_get_pengaturan('info', DEFAULT_PENGATURAN['info'])


# ============================================================
#   FUNGSI BACKUP DATABASE
# ============================================================
def pastikan_folder_backup():
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
    return BACKUP_DIR


def backup_database():
    try:
        pastikan_folder_backup()
        tanggal = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        nama_file = f'isp-{tanggal}.db'
        path_backup = os.path.join(BACKUP_DIR, nama_file)
        shutil.copy2(DB_FILE, path_backup)
        _log(f"OK Backup: {path_backup} ({os.path.getsize(path_backup)} bytes)")
        return nama_file
    except Exception as e:
        _log(f"GAGAL backup: {e}")
        return None


def daftar_backup():
    try:
        pastikan_folder_backup()
        files = []
        for f in os.listdir(BACKUP_DIR):
            if f.endswith('.db'):
                path = os.path.join(BACKUP_DIR, f)
                files.append({
                    'nama': f,
                    'ukuran': os.path.getsize(path),
                    'ukuran_str': format_bytes(os.path.getsize(path)),
                    'tanggal': datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d %H:%M:%S'),
                })
        files.sort(key=lambda x: x['tanggal'], reverse=True)
        return files
    except Exception as e:
        _log(f"Error list backup: {e}")
        return []


def hapus_backup(nama_file):
    try:
        path = os.path.join(BACKUP_DIR, nama_file)
        if os.path.exists(path):
            os.remove(path)
            _log(f"OK Hapus backup: {nama_file}")
            return True
    except Exception as e:
        _log(f"GAGAL hapus backup: {e}")
    return False


def restore_database(nama_file_backup):
    try:
        path_backup = os.path.join(BACKUP_DIR, nama_file_backup)
        if not os.path.exists(path_backup):
            _log("GAGAL restore: file tidak ada")
            return False
        tgl = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        shutil.copy2(DB_FILE, os.path.join(BACKUP_DIR, f'sebelum-restore-{tgl}.db'))
        shutil.copy2(path_backup, DB_FILE)
        _log(f"OK Restore dari: {nama_file_backup}")
        return True
    except Exception as e:
        _log(f"GAGAL restore: {e}")
        return False


def auto_backup_harian():
    while True:
        try:
            time.sleep(24 * 60 * 60)
            backup_database()
            _log("Auto-backup harian selesai")
        except Exception as e:
            _log(f"Error auto-backup: {e}")


def mulai_auto_backup():
    backup_database()
    t = threading.Thread(target=auto_backup_harian, daemon=True)
    t.start()
    _log("Auto-backup harian dimulai")


# ============================================================
#   WHATSAPP (via Intent Android / browser)
# ============================================================
def normalisasi_nomor(nomor):
    if not nomor:
        return None
    bersih = ''.join(c for c in str(nomor) if c.isdigit() or c == '+')
    bersih = bersih.lstrip('+')
    if bersih.startswith('0'):
        bersih = '62' + bersih[1:]
    elif not bersih.startswith('62'):
        bersih = '62' + bersih
    return '+' + bersih


def buat_pesan_tagihan(nama_lengkap, tgl_jatuh_tempo, harga, paket, nama_pppoe=''):
    if harga and harga > 0:
        harga_str = f"Rp {harga:,}".replace(',', '.')
    else:
        harga_str = "-"
    nama_isp = get_nama_isp()
    pesan = (
        f"Halo {nama_lengkap},\n\n"
        f"Ini pengingat dari {nama_isp}:\n\n"
        f"📅 Jatuh tempo: {tgl_jatuh_tempo}\n"
        f"📦 Paket: {paket}\n"
        f"💰 Tagihan: {harga_str}\n\n"
        f"Mohon segera melakukan pembayaran sebelum tanggal jatuh tempo "
        f"agar layanan internet tetap aktif.\n\n"
        f"Terima kasih. 🙏"
    )
    return pesan


def kirim_whatsapp(nomor, pesan, wait_time=15):
    """Kirim WA via Intent Android. Di PC, buka browser wa.me."""
    if not kirim_wa_intent:
        _log("GAGAL kirim WA: mobile_wa tidak tersedia")
        return False
    try:
        nomor_format = normalisasi_nomor(nomor)
        if not nomor_format:
            return False
        _log(f"Membuka WhatsApp ke {nomor_format}...")
        hasil = kirim_wa_intent(nomor_format, pesan)
        if hasil:
            _log(f"OK WhatsApp dibuka untuk {nomor_format}")
        return hasil
    except Exception as e:
        _log(f"GAGAL kirim WA: {e}")
        return False


def dapatkan_pelanggan_h3():
    target = (date.today() + timedelta(days=3)).isoformat()
    return [p for p in db_get_pelanggan_semua()
            if p.get('status') == 'aktif' and p.get('tgl_jatuh_tempo') == target]


def dapatkan_pelanggan_hari_ini():
    target = date.today().isoformat()
    return [p for p in db_get_pelanggan_semua()
            if p.get('status') == 'aktif' and p.get('tgl_jatuh_tempo') == target]


def dapatkan_pelanggan_telat():
    hari_ini = date.today().isoformat()
    return [p for p in db_get_pelanggan_semua()
            if p.get('status') == 'aktif'
            and p.get('tgl_jatuh_tempo')
            and p['tgl_jatuh_tempo'] < hari_ini]


# ============================================================
#   KONEKSI MIKROTIK - AUTO-DETECT VERSI
# ============================================================
_mikrotik_version_cache = None


def koneksi_mikrotik():
    try:
        conn = routeros_api.RouterOsApiPool(
            MIKROTIK_IP, username=MIKROTIK_USER, password=MIKROTIK_PASS,
            port=MIKROTIK_PORT, plaintext_login=True
        )
        api = conn.get_api()
        api.get_resource('/system/identity').get()
        return conn
    except Exception as e1:
        _log(f"Koneksi port {MIKROTIK_PORT} gagal: {e1}")
        try:
            conn = routeros_api.RouterOsApiPool(
                MIKROTIK_IP, username=MIKROTIK_USER, password=MIKROTIK_PASS,
                port=8729, plaintext_login=True, ssl=True
            )
            _log("OK Terhubung via API-SSL (port 8729)")
            return conn
        except Exception as e2:
            _log(f"Fallback API-SSL gagal: {e2}")
            raise e1


def cek_koneksi_mikrotik():
    global _mikrotik_version_cache
    try:
        conn = koneksi_mikrotik()
        api = conn.get_api()
        resource = api.get_resource('/system/resource').get()
        identity = api.get_resource('/system/identity').get()
        conn.disconnect()
        versi = resource[0].get('version', '?') if resource else '?'
        nama = identity[0].get('name', '?') if identity else '?'
        _mikrotik_version_cache = versi
        return {'status': 'OK', 'versi': versi, 'nama': nama, 'ip': MIKROTIK_IP}
    except Exception as e:
        return {'status': 'ERROR', 'pesan': str(e), 'ip': MIKROTIK_IP}


def get_interfaces():
    try:
        conn = koneksi_mikrotik()
        api = conn.get_api()
        data = api.get_resource('/interface').get()
        conn.disconnect()
        return data
    except Exception as e:
        _log(f"Error get_interfaces: {e}")
        return None


def pastikan_pool_ada():
    try:
        conn = koneksi_mikrotik()
        api = conn.get_api()
        resource = api.get_resource('/ip/pool')
        pools = resource.get()
        if not any(p.get('name') == IP_POOL_PPPOE for p in pools):
            resource.add(name=IP_POOL_PPPOE, ranges=IP_RANGE_POOL)
            _log(f"OK Pool '{IP_POOL_PPPOE}' dibuat.")
        conn.disconnect()
        return True
    except Exception as e:
        _log(f"GAGAL pastikan pool: {e}")
        return False


def pastikan_profil_ada(nama_profil, rate_limit):
    try:
        conn = koneksi_mikrotik()
        api = conn.get_api()
        resource = api.get_resource('/ppp/profile')
        profiles = resource.get()
        target = next((p for p in profiles if p.get('name') == nama_profil), None)
        if target:
            local_skrg = target.get('local-address', '') or ''
            remote_skrg = target.get('remote-address', '') or ''
            if not local_skrg or not remote_skrg:
                pid = target.get('.id') or target.get('id')
                resource.set(id=pid, **{
                    'local-address': IP_LOCAL_PPPOE,
                    'remote-address': IP_POOL_PPPOE})
        else:
            resource.add(name=nama_profil, rate_limit=rate_limit, **{
                'local-address': IP_LOCAL_PPPOE,
                'remote-address': IP_POOL_PPPOE})
        conn.disconnect()
        return True
    except Exception as e:
        _log(f"GAGAL pastikan profil: {e}")
        return False


def mt_set_profile(nama, profil_baru):
    try:
        conn = koneksi_mikrotik()
        api = conn.get_api()
        resource = api.get_resource('/ppp/secret')
        target = next((s for s in resource.get() if s.get('name') == nama), None)
        if not target:
            conn.disconnect(); return False
        sid = target.get('.id') or target.get('id')
        resource.set(id=sid, profile=profil_baru)
        conn.disconnect(); return True
    except Exception as e:
        _log(f"GAGAL set profile: {e}"); return False


def kick_pppoe_active(nama):
    try:
        conn = koneksi_mikrotik()
        api = conn.get_api()
        resource = api.get_resource('/ppp/active')
        target = next((a for a in resource.get() if a.get('name') == nama), None)
        if target:
            aid = target.get('.id') or target.get('id')
            resource.remove(id=aid)
        conn.disconnect(); return True
    except Exception as e:
        _log(f"GAGAL kick: {e}"); return False


def mt_tambah_secret(nama, password, profil):
    try:
        conn = koneksi_mikrotik()
        api = conn.get_api()
        api.get_resource('/ppp/secret').add(
            name=nama, password=password, service='pppoe', profile=profil)
        conn.disconnect(); return True
    except Exception as e:
        _log(f"GAGAL tambah secret: {e}"); return False


def mt_edit_secret(nama, password, profil):
    try:
        conn = koneksi_mikrotik()
        api = conn.get_api()
        resource = api.get_resource('/ppp/secret')
        target = next((s for s in resource.get() if s.get('name') == nama), None)
        if not target:
            conn.disconnect(); return False
        sid = target.get('.id') or target.get('id')
        resource.set(id=sid, password=password, profile=profil)
        conn.disconnect(); return True
    except Exception as e:
        _log(f"GAGAL edit secret: {e}"); return False


def mt_hapus_secret(nama):
    try:
        conn = koneksi_mikrotik()
        api = conn.get_api()
        resource = api.get_resource('/ppp/secret')
        target = next((s for s in resource.get() if s.get('name') == nama), None)
        if not target:
            conn.disconnect(); return False
        sid = target.get('.id') or target.get('id')
        resource.remove(id=sid)
        conn.disconnect(); return True
    except Exception as e:
        _log(f"GAGAL hapus secret: {e}"); return False


# ============================================================
#   SYNC DARI MIKROTIK
# ============================================================
def sync_dari_mikrotik():
    """Ambil semua PPP Secret dari MikroTik, masukkan ke database."""
    hasil = {'ditambah': 0, 'dilewati': 0, 'error': 0, 'detail': []}

    try:
        conn = koneksi_mikrotik()
        api = conn.get_api()
        secrets = api.get_resource('/ppp/secret').get()
        conn.disconnect()
    except Exception as e:
        hasil['detail'].append(f"❌ Gagal konek MikroTik: {e}")
        return hasil

    if not secrets:
        hasil['detail'].append("⚠️ Tidak ada PPP Secret di MikroTik")
        return hasil

    for s in secrets:
        nama = s.get('name', '').strip()
        password = s.get('password', '').strip() or '12345678'
        profil = s.get('profile', 'default').strip()
        disabled = s.get('disabled', 'false')

        if not nama:
            continue

        existing = db_get_pelanggan(nama)
        if existing:
            hasil['dilewati'] += 1
            hasil['detail'].append(f"⚠️ SKIP — {nama} (sudah ada)")
            continue

        try:
            db_tambah_pelanggan(
                nama_pppoe=nama,
                password=password,
                profil=profil,
                nama_lengkap=nama,
                alamat='',
                telepon='',
                harga=0,
                tgl_jatuh_tempo=''
            )
            status = 'ISOLIR' if disabled == 'true' else 'AKTIF'
            hasil['ditambah'] += 1
            hasil['detail'].append(f"✅ TAMBAH — {nama} ({profil}, {status})")
        except Exception as e:
            hasil['error'] += 1
            hasil['detail'].append(f"❌ GAGAL — {nama}: {e}")

    return hasil


# ============================================================
#   ISOLIR / AKTIFKAN
# ============================================================
def isolir_pelanggan(nama_pppoe):
    data = db_get_pelanggan(nama_pppoe)
    if not data: return False
    pastikan_profil_ada(PROFIL_ISOLIR, RATE_LIMIT_ISOLIR)
    if not mt_set_profile(nama_pppoe, PROFIL_ISOLIR): return False
    kick_pppoe_active(nama_pppoe)
    db_set_status(nama_pppoe, 'isolir', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    _log(f"OK ISOLIR: '{nama_pppoe}'")
    return True


def aktifkan_pelanggan(nama_pppoe):
    data = db_get_pelanggan(nama_pppoe)
    if not data: return False
    profil_asli = data.get('profil') or 'default'
    if profil_asli in PAKET_BANDWIDTH:
        pastikan_profil_ada(profil_asli, PAKET_BANDWIDTH[profil_asli])
    if not mt_set_profile(nama_pppoe, profil_asli): return False
    kick_pppoe_active(nama_pppoe)
    db_set_status(nama_pppoe, 'aktif', None)
    _log(f"OK AKTIF: '{nama_pppoe}'")
    return True


def cek_dan_isolir_otomatis():
    hari_ini = date.today().isoformat()
    diisolir = []
    for p in db_get_pelanggan_semua():
        if p['status'] == 'aktif' and p.get('tgl_jatuh_tempo'):
            if p['tgl_jatuh_tempo'] < hari_ini:
                if isolir_pelanggan(p['nama_pppoe']):
                    diisolir.append(p['nama_pppoe'])
    return diisolir


# ============================================================
#   MONITORING
# ============================================================
def format_bytes(b):
    try:
        b = int(b)
    except:
        b = 0
    if b < 1024: return f"{b} B"
    elif b < 1024*1024: return f"{b/1024:.1f} KB"
    elif b < 1024*1024*1024: return f"{b/(1024*1024):.1f} MB"
    else: return f"{b/(1024*1024*1024):.2f} GB"


def format_rate(bps):
    try:
        bps = int(bps)
    except:
        bps = 0
    if bps < 1024: return f"{bps} B/s"
    elif bps < 1024*1024: return f"{bps/1024:.1f} KB/s"
    else: return f"{bps/(1024*1024):.2f} MB/s"


def get_active_pppoe():
    try:
        conn = koneksi_mikrotik()
        api = conn.get_api()
        aktif = api.get_resource('/ppp/active').get()
        conn.disconnect(); return aktif
    except Exception as e:
        _log(f"Error get_active: {e}"); return []


def cari_nama_pppoe_dari_ip(ip):
    try:
        for a in get_active_pppoe():
            if a.get('address') == ip:
                return a.get('name')
    except: pass
    return None


def sample_interfaces():
    try:
        conn = koneksi_mikrotik()
        api = conn.get_api()
        snapshot = {}
        for iface in api.get_resource('/interface').get():
            nama = iface.get('name', '')
            if nama.startswith('<pppoe-'):
                snapshot[nama] = {
                    'rx': int(iface.get('rx-byte', 0) or 0),
                    'tx': int(iface.get('tx-byte', 0) or 0)}
        conn.disconnect(); return snapshot
    except Exception as e:
        _log(f"Error sample: {e}"); return {}


def get_live_traffic(jeda=1.0):
    snap1 = sample_interfaces()
    time.sleep(jeda)
    snap2 = sample_interfaces()
    hasil = {}
    for iface in snap2:
        user = iface.replace('<pppoe-', '').rstrip('>')
        s1 = snap1.get(iface, {'rx': 0, 'tx': 0})
        s2 = snap2[iface]
        hasil[user] = {
            'rx_total_str': format_bytes(s2['rx']),
            'tx_total_str': format_bytes(s2['tx']),
            'rx_rate_str': format_rate(max(0, (s2['rx'] - s1['rx']) // int(jeda))),
            'tx_rate_str': format_rate(max(0, (s2['tx'] - s1['tx']) // int(jeda))),
        }
    return hasil


# ============================================================
#   CSS UMUM
# ============================================================
CSS_UMUM = """
    body { font-family: Arial, sans-serif; background: #f0f2f5; margin: 0; padding: 20px; }
    .container { max-width: 1400px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
    h1 { color: #333; margin-top: 0; margin-bottom: 20px; }
    .nav-menu { display: flex; gap: 10px; margin-bottom: 25px; border-bottom: 2px solid #eee; flex-wrap: wrap; }
    .nav-menu a { padding: 12px 20px; text-decoration: none; color: #666; font-weight: 600; border-bottom: 3px solid transparent; }
    .nav-menu a:hover { color: #0066cc; background: #f5f9ff; }
    .nav-menu a.active { color: #0066cc; border-bottom-color: #0066cc; }
    .info { background: #e7f3ff; border-left: 4px solid #0066cc; padding: 12px 15px; margin-bottom: 20px; border-radius: 4px; font-size: 14px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #eee; }
    th { background: #0066cc; color: white; font-weight: 600; font-size: 12px; }
    tr:hover { background: #f9f9f9; }
    .status-aktif { color: #00a651; font-weight: bold; }
    .status-nonaktif { color: #999; }
    .status-isolir { color: #cc0000; font-weight: bold; }
    .error { background: #ffe7e7; border-left: 4px solid #cc0000; color: #cc0000; padding: 15px; border-radius: 4px; margin-bottom: 20px; }
    .sukses { background: #e7f9ed; border-left: 4px solid #00a651; color: #006f34; padding: 15px; border-radius: 4px; margin-bottom: 20px; }
    .warn { background: #fff8e1; border-left: 4px solid #ffa726; color: #9c6500; padding: 15px; border-radius: 4px; margin-bottom: 20px; }
    .footer { margin-top: 20px; text-align: center; color: #999; font-size: 12px; }
    .btn-tambah { background: #00a651; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; font-weight: 600; font-size: 14px; }
    .btn-tambah:hover { background: #008a42; }
    .btn-cek { background: #0066cc; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; font-weight: 600; font-size: 14px; }
    .btn-cek:hover { background: #0052a3; }
    .btn-edit { background: #ffa726; color: white; padding: 5px 8px; border: none; border-radius: 4px; cursor: pointer; font-size: 11px; font-weight: 600; margin-right: 3px; }
    .btn-edit:hover { background: #f57c00; }
    .btn-hapus { background: #ef5350; color: white; padding: 5px 8px; border: none; border-radius: 4px; cursor: pointer; font-size: 11px; font-weight: 600; margin-right: 3px; }
    .btn-hapus:hover { background: #c62828; }
    .btn-isolir { background: #d32f2f; color: white; padding: 5px 8px; border: none; border-radius: 4px; cursor: pointer; font-size: 11px; font-weight: 600; margin-right: 3px; }
    .btn-isolir:hover { background: #b71c1c; }
    .btn-aktifkan { background: #00a651; color: white; padding: 5px 8px; border: none; border-radius: 4px; cursor: pointer; font-size: 11px; font-weight: 600; margin-right: 3px; }
    .btn-aktifkan:hover { background: #008a42; }
    .btn-wa { background: #25D366; color: white; padding: 6px 10px; border: none; border-radius: 4px; cursor: pointer; font-size: 11px; font-weight: 600; text-decoration: none; display: inline-block; margin-right: 3px; }
    .btn-wa:hover { background: #128C7E; }
    .btn-primary { background: #0066cc; color: white; padding: 12px 30px; border: none; border-radius: 6px; cursor: pointer; font-weight: 700; font-size: 14px; }
    .btn-primary:hover { background: #0052a3; }
    .modal-bg { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 100; }
    .modal-bg.aktif { display: flex; align-items: center; justify-content: center; }
    .modal { background: white; padding: 30px; border-radius: 8px; width: 90%; max-width: 520px; box-shadow: 0 4px 20px rgba(0,0,0,0.2); max-height: 90vh; overflow-y: auto; }
    .modal h2 { margin-top: 0; color: #333; }
    .modal label { display: block; margin-top: 12px; margin-bottom: 5px; color: #444; font-weight: 600; font-size: 13px; }
    .modal input, .modal select { width: 100%; padding: 9px; border: 1px solid #ddd; border-radius: 5px; font-size: 14px; box-sizing: border-box; }
    .modal input:focus, .modal select:focus { outline: none; border-color: #0066cc; }
    .modal input[readonly] { background: #f0f0f0; color: #666; }
    .row2 { display: flex; gap: 10px; }
    .row2 > div { flex: 1; }
    .modal-buttons { display: flex; gap: 10px; margin-top: 25px; }
    .btn-simpan { background: #0066cc; color: white; padding: 12px 20px; border: none; border-radius: 5px; cursor: pointer; font-weight: 600; flex: 1; font-size: 14px; }
    .btn-simpan:hover { background: #0052a3; }
    .btn-batal { background: #eee; color: #444; padding: 12px 20px; border: none; border-radius: 5px; cursor: pointer; font-weight: 600; flex: 1; font-size: 14px; }
    .btn-batal:hover { background: #ddd; }
    tr.isolir { background: #fff5f5; }
    tr.isolir:hover { background: #ffeaea; }
    tr.online { background: #f0fff5; }
    tr.online:hover { background: #e0ffee; }
    tr.offline { color: #999; }
    .badge-online { background: #00a651; color: white; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: bold; }
    .badge-offline { background: #ccc; color: white; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: bold; }
    .rx-rate { color: #0066cc; font-weight: bold; }
    .tx-rate { color: #cc6600; font-weight: bold; }
    .total-bytes { font-size: 11px; color: #888; }
    .empty { text-align: center; padding: 40px; color: #999; background: #f9f9f9; border-radius: 8px; }
    .empty-icon { font-size: 48px; margin-bottom: 10px; }
    .card { background: #f9f9f9; border-radius: 8px; padding: 20px; margin-bottom: 20px; border-left: 4px solid #0066cc; }
    .card h2 { margin-top: 0; color: #333; }
    .card-h3 { border-left-color: #ffa726; }
    .card-hariini { border-left-color: #d32f2f; }
    .card-telat { border-left-color: #8b0000; }
    .badge-count { background: #0066cc; color: white; padding: 3px 12px; border-radius: 12px; font-size: 12px; font-weight: bold; margin-left: 8px; }
    .form-group { margin-bottom: 20px; }
    .form-group label { display: block; margin-bottom: 8px; font-weight: 600; color: #333; font-size: 14px; }
    .form-group input, .form-group textarea { width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; box-sizing: border-box; font-family: inherit; }
    .form-group input:focus, .form-group textarea:focus { outline: none; border-color: #0066cc; box-shadow: 0 0 0 3px rgba(0,102,204,0.1); }
    .form-group .hint { font-size: 12px; color: #888; margin-top: 5px; font-style: italic; }
    .settings-section { background: #fafbfc; border-radius: 10px; padding: 24px; margin-bottom: 20px; border: 1px solid #eef0f3; }
    .settings-section h2 { margin-top: 0; color: #333; font-size: 18px; border-bottom: 2px solid #eef0f3; padding-bottom: 10px; margin-bottom: 20px; }
    .qris-preview { max-width: 200px; border: 1px solid #ddd; border-radius: 8px; padding: 8px; background: white; }
    .backup-info { background: #e7f3ff; border-left: 4px solid #0066cc; padding: 16px; border-radius: 8px; margin-bottom: 20px; font-size: 13px; line-height: 1.7; color: #444; }
    .backup-info strong { color: #0066cc; }
    .btn-big { display: inline-block; padding: 14px 28px; border-radius: 8px; text-decoration: none; font-weight: 700; font-size: 14px; margin-right: 10px; margin-bottom: 10px; cursor: pointer; border: none; }
    .btn-download { background: #00a651; color: white; }
    .btn-download:hover { background: #008a42; }
    .btn-restore { background: #ffa726; color: white; }
    .btn-restore:hover { background: #f57c00; }
    .btn-hapus-single { background: #ef5350; color: white; padding: 6px 12px; font-size: 12px; border-radius: 4px; }
    .btn-hapus-single:hover { background: #c62828; }
    .btn-dl-single { background: #0066cc; color: white; padding: 6px 12px; font-size: 12px; border-radius: 4px; text-decoration: none; }
    .btn-dl-single:hover { background: #0052a3; }
    .btn-restore-single { background: #ffa726; color: white; padding: 6px 12px; font-size: 12px; border-radius: 4px; }
    .upload-box { background: #fff8e1; border: 2px dashed #ffa726; border-radius: 10px; padding: 24px; text-align: center; margin-top: 20px; }
    .upload-btn { background: #ffa726; color: white; padding: 12px 24px; border-radius: 8px; cursor: pointer; font-weight: 700; display: inline-block; }
    .upload-btn input { display: none; }
    .warning-box { background: #ffe7e7; border-left: 4px solid #cc0000; padding: 14px; border-radius: 8px; margin-top: 20px; font-size: 13px; color: #cc0000; line-height: 1.6; }
"""


def navbar(active=''):
    def cls(name):
        return 'class="active"' if active == name else ''
    return f"""
        <div class="nav-menu">
            <a href="/" {cls('home')}>Interface</a>
            <a href="/pelanggan" {cls('pel')}>Pelanggan</a>
            <a href="/monitoring" {cls('mon')}>📊 Monitoring</a>
            <a href="/notifikasi" {cls('not')}>📱 Notifikasi WA</a>
            <a href="/import_pelanggan" {cls('imp')}>📤 Import</a>
            <a href="/backup" {cls('backup')}>📦 Backup</a>
            <a href="/pengaturan" {cls('set')}>⚙️ Pengaturan</a>
        </div>
"""


# ============================================================
#   HTML TEMPLATES
# ============================================================
HTML_INTERFACE = """
<!DOCTYPE html><html lang="id"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Interface</title>
<style>""" + CSS_UMUM + """</style></head><body><div class="container">
<h1>🌐 Dashboard ISP</h1>""" + navbar('home') + """
<div class="info"><strong>MikroTik:</strong> """ + MIKROTIK_IP + """</div>
{% if error %}<div class="error">⚠️ {{ error }}</div>{% endif %}
{% if interfaces %}<table><thead><tr><th>No</th><th>Nama</th><th>Tipe</th><th>Status</th></tr></thead>
<tbody>{% for iface in interfaces %}<tr>
<td>{{ loop.index }}</td><td><strong>{{ iface.get('name', 'N/A') }}</strong></td>
<td>{{ iface.get('type', 'N/A') }}</td>
<td>{% if iface.get('running') == 'true' %}<span class="status-aktif">● AKTIF</span>{% else %}<span class="status-nonaktif">○ NONAKTIF</span>{% endif %}</td>
</tr>{% endfor %}</tbody></table>{% endif %}
<div class="footer">Aplikasi ISP v1.9 | {{ nama_isp }}</div>
</div></body></html>
"""


HTML_PELANGGAN = """
<!DOCTYPE html><html lang="id"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Pelanggan</title>
<style>""" + CSS_UMUM + """</style></head><body><div class="container">
<h1>🌐 Dashboard ISP</h1>""" + navbar('pel') + """
{% if pesan_sukses %}<div class="sukses">✅ {{ pesan_sukses }}</div>{% endif %}
{% if pesan_warn %}<div class="warn">ℹ️ {{ pesan_warn }}</div>{% endif %}
{% if error %}<div class="error">⚠️ {{ error }}</div>{% endif %}
<div class="info">
<div><strong>Total:</strong> {{ pelanggan|length }} | <strong style="color:#00a651;">Aktif:</strong> {{ jumlah_aktif }} | <strong style="color:#cc0000;">Isolir:</strong> {{ jumlah_isolir }}</div>
<div>
<a class="btn-wa" href="/export_pelanggan">📥 Export</a>
<a class="btn-wa" href="/import_pelanggan" style="background:#0066cc;">📤 Import</a>
<form action="/sync_mikrotik" method="POST" style="display:inline;" onsubmit="return confirm('Sync semua pelanggan dari MikroTik ke database?');">
<button type="submit" class="btn-cek" style="background:#ffa726;">🔄 Sync MikroTik</button>
</form>
<button class="btn-tambah" onclick="bukaModalTambah()">+ Tambah</button>
<button class="btn-cek" onclick="cekOtomatis()">🔄 Cek Jatuh Tempo</button>
</div></div>

{% if pelanggan and pelanggan|length > 0 %}
<table><thead><tr><th>No</th><th>Nama PPPoE</th><th>Nama Lengkap</th><th>Telepon</th><th>Paket</th><th>Harga</th><th>Jatuh Tempo</th><th>Status</th><th>Aksi</th></tr></thead>
<tbody>{% for p in pelanggan %}<tr class="{% if p.status == 'isolir' %}isolir{% endif %}">
<td>{{ loop.index }}</td><td><strong>{{ p.nama_pppoe }}</strong></td>
<td>{{ p.nama_lengkap or '-' }}</td><td>{{ p.telepon or '-' }}</td>
<td>{{ p.profil }}</td>
<td>Rp {{ '{:,}'.format(p.harga or 0).replace(',', '.') }}</td>
<td>{{ p.tgl_jatuh_tempo or '-' }}</td>
<td>{% if p.status == 'isolir' %}<span class="status-isolir">🔒 ISOLIR</span>{% else %}<span class="status-aktif">● AKTIF</span>{% endif %}</td>
<td>
<a class="btn-wa" href="/banner?user={{ p.nama_pppoe }}" target="_blank">👁️</a>
{% if p.telepon %}<a class="btn-wa" href="/kirim_wa/{{ p.nama_pppoe }}">📱</a>{% endif %}
{% if p.status == 'isolir' %}<button class="btn-aktifkan" onclick="konfirmasiAktifkan('{{ p.nama_pppoe }}')">✅</button>
{% else %}<button class="btn-isolir" onclick="konfirmasiIsolir('{{ p.nama_pppoe }}')">🔒</button>{% endif %}
<button class="btn-edit" onclick='bukaModalEdit({{ p|tojson }})'>✏️</button>
<button class="btn-hapus" onclick="konfirmasiHapus('{{ p.nama_pppoe }}')">🗑️</button>
</td></tr>{% endfor %}</tbody></table>
{% elif not error %}<div class="empty"><div class="empty-icon">📭</div><h3>Belum ada pelanggan</h3><p>Klik <strong>🔄 Sync MikroTik</strong> untuk tarik data dari router, atau <strong>+ Tambah</strong> manual.</p></div>{% endif %}

<div class="footer">Aplikasi ISP v1.9 | {{ nama_isp }}</div></div>

<div id="modalTambah" class="modal-bg"><div class="modal"><h2>➕ Tambah Pelanggan</h2>
<form action="/tambah_pelanggan" method="POST">
<label>Nama PPPoE</label><input type="text" name="nama_pppoe" required>
<label>Password</label><input type="text" name="password" required>
<label>Nama Lengkap</label><input type="text" name="nama_lengkap">
<label>Alamat</label><input type="text" name="alamat">
<label>Telepon</label><input type="text" name="telepon">
<div class="row2"><div><label>Paket</label>
<select name="paket" id="paket_tambah" onchange="autoHargaTambah()">
<option value="3Mbps">3 Mbps</option><option value="5Mbps">5 Mbps</option>
<option value="10Mbps" selected>10 Mbps</option><option value="20Mbps">20 Mbps</option>
<option value="default">Default</option><option value="__manual__">✏️ Isi Manual</option>
</select></div><div><label>Harga</label><input type="number" name="harga" id="harga_tambah" value="150000"></div></div>
<div id="manual_wrap_tambah" style="display:none;"><label>Profil Manual</label><input type="text" name="profil_manual"></div>
<label>Jatuh Tempo</label><input type="date" name="tgl_jatuh_tempo">
<div class="modal-buttons"><button type="button" class="btn-batal" onclick="tutupModalTambah()">Batal</button>
<button type="submit" class="btn-simpan">Simpan</button></div></form></div></div>

<div id="modalEdit" class="modal-bg"><div class="modal"><h2>✏️ Edit Pelanggan</h2>
<form action="/edit_pelanggan" method="POST">
<label>Nama PPPoE</label><input type="text" name="nama_pppoe" id="edit_nama" readonly>
<label>Password</label><input type="text" name="password" id="edit_password">
<label>Nama Lengkap</label><input type="text" name="nama_lengkap" id="edit_nama_lengkap">
<label>Alamat</label><input type="text" name="alamat" id="edit_alamat">
<label>Telepon</label><input type="text" name="telepon" id="edit_telepon">
<div class="row2"><div><label>Paket</label>
<select name="paket" id="edit_paket" onchange="autoHargaEdit()">
<option value="3Mbps">3 Mbps</option><option value="5Mbps">5 Mbps</option>
<option value="10Mbps">10 Mbps</option><option value="20Mbps">20 Mbps</option>
<option value="default">Default</option><option value="__manual__">✏️ Isi Manual</option>
</select></div><div><label>Harga</label><input type="number" name="harga" id="edit_harga"></div></div>
<div id="manual_wrap_edit" style="display:none;"><label>Profil Manual</label><input type="text" name="profil_manual" id="edit_profil_manual"></div>
<label>Jatuh Tempo</label><input type="date" name="tgl_jatuh_tempo" id="edit_tgl">
<div class="modal-buttons"><button type="button" class="btn-batal" onclick="tutupModalEdit()">Batal</button>
<button type="submit" class="btn-simpan">Simpan</button></div></form></div></div>

<form id="formHapus" action="/hapus_pelanggan" method="POST" style="display:none;"><input type="hidden" name="nama_pppoe" id="hapus_nama"></form>
<form id="formIsolir" action="/isolir_pelanggan" method="POST" style="display:none;"><input type="hidden" name="nama_pppoe" id="isolir_nama"></form>
<form id="formAktifkan" action="/aktifkan_pelanggan" method="POST" style="display:none;"><input type="hidden" name="nama_pppoe" id="aktifkan_nama"></form>
<form id="formCek" action="/cek_otomatis" method="POST" style="display:none;"></form>

<script>
var HARGA = {'3Mbps':100000,'5Mbps':125000,'10Mbps':150000,'20Mbps':250000,'default':0};
function bukaModalTambah(){document.getElementById('modalTambah').classList.add('aktif');}
function tutupModalTambah(){document.getElementById('modalTambah').classList.remove('aktif');}
function autoHargaTambah(){var v=document.getElementById('paket_tambah').value;
if(v==='__manual__'){document.getElementById('manual_wrap_tambah').style.display='block';}
else{document.getElementById('manual_wrap_tambah').style.display='none';if(HARGA[v]!==undefined)document.getElementById('harga_tambah').value=HARGA[v];}}
function bukaModalEdit(p){
document.getElementById('edit_nama').value=p.nama_pppoe;
document.getElementById('edit_password').value=p.password;
document.getElementById('edit_nama_lengkap').value=p.nama_lengkap||'';
document.getElementById('edit_alamat').value=p.alamat||'';
document.getElementById('edit_telepon').value=p.telepon||'';
document.getElementById('edit_harga').value=p.harga||0;
document.getElementById('edit_tgl').value=p.tgl_jatuh_tempo||'';
var s=document.getElementById('edit_paket');var f=false;
for(var i=0;i<s.options.length;i++){if(s.options[i].value===p.profil){s.selectedIndex=i;f=true;break;}}
if(!f&&p.profil){s.value='__manual__';document.getElementById('manual_wrap_edit').style.display='block';document.getElementById('edit_profil_manual').value=p.profil;}
else{document.getElementById('manual_wrap_edit').style.display='none';}
document.getElementById('modalEdit').classList.add('aktif');}
function tutupModalEdit(){document.getElementById('modalEdit').classList.remove('aktif');}
function autoHargaEdit(){var v=document.getElementById('edit_paket').value;
if(v==='__manual__'){document.getElementById('manual_wrap_edit').style.display='block';}
else{document.getElementById('manual_wrap_edit').style.display='none';if(HARGA[v]!==undefined)document.getElementById('edit_harga').value=HARGA[v];}}
function konfirmasiHapus(n){if(confirm('Yakin HAPUS "'+n+'"?')){document.getElementById('hapus_nama').value=n;document.getElementById('formHapus').submit();}}
function konfirmasiIsolir(n){if(confirm('ISOLIR "'+n+'"?')){document.getElementById('isolir_nama').value=n;document.getElementById('formIsolir').submit();}}
function konfirmasiAktifkan(n){if(confirm('AKTIFKAN "'+n+'"?')){document.getElementById('aktifkan_nama').value=n;document.getElementById('formAktifkan').submit();}}
function cekOtomatis(){if(confirm('Cek & isolir pelanggan telat?')){document.getElementById('formCek').submit();}}
</script></body></html>
"""


HTML_MONITORING = """
<!DOCTYPE html><html lang="id"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Monitoring</title>
<meta http-equiv="refresh" content="15">
<style>""" + CSS_UMUM + """</style></head><body><div class="container">
<h1>📊 Monitoring Live</h1>""" + navbar('mon') + """
<div class="info"><div><span class="status-aktif">● {{ jumlah_online }} Online</span> | <span class="status-nonaktif">○ {{ jumlah_offline }} Offline</span> | Total: {{ total_pelanggan }}</div>
<div><a href="/monitoring" class="btn-cek">🔄 Refresh</a></div></div>
{% if pelanggan_data %}<table><thead><tr><th>No</th><th>Nama PPPoE</th><th>Status</th><th>IP</th><th>Uptime</th><th>⬇️ RX</th><th>⬆️ TX</th></tr></thead>
<tbody>{% for p in pelanggan_data %}<tr class="{% if p.online %}online{% else %}offline{% endif %}">
<td>{{ loop.index }}</td><td><strong>{{ p.nama_pppoe }}</strong></td>
<td>{% if p.online %}<span class="badge-online">ONLINE</span>{% else %}<span class="badge-offline">OFFLINE</span>{% endif %}</td>
<td>{{ p.ip or '-' }}</td><td>{{ p.uptime or '-' }}</td>
<td>{% if p.online %}<span class="rx-rate">⬇ {{ p.rx_rate_str }}</span><div class="total-bytes">{{ p.rx_total_str }}</div>{% else %}-{% endif %}</td>
<td>{% if p.online %}<span class="tx-rate">⬆ {{ p.tx_rate_str }}</span><div class="total-bytes">{{ p.tx_total_str }}</div>{% else %}-{% endif %}</td>
</tr>{% endfor %}</tbody></table>{% endif %}
<div class="footer">Aplikasi ISP v1.9 | {{ nama_isp }}</div></div></body></html>
"""


HTML_NOTIFIKASI = """
<!DOCTYPE html><html lang="id"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Notifikasi WA</title>
<style>""" + CSS_UMUM + """</style></head><body><div class="container">
<h1>📱 Notifikasi WhatsApp</h1>""" + navbar('not') + """
{% if pesan_sukses %}<div class="sukses">✅ {{ pesan_sukses }}</div>{% endif %}
<div class="info"><div><strong>H-3:</strong> {{ h3|length }} | <strong>Hari ini:</strong> {{ hari_ini|length }} | <strong>Telat:</strong> {{ telat|length }}</div></div>

<div class="card card-h3"><h2>⏰ H-3 <span class="badge-count">{{ h3|length }}</span></h2>
{% if h3 %}<table><thead><tr><th>Nama</th><th>Telepon</th><th>Paket</th><th>Jatuh Tempo</th><th>Aksi</th></tr></thead>
<tbody>{% for p in h3 %}<tr><td><strong>{{ p.nama_pppoe }}</strong></td><td>{{ p.telepon or '-' }}</td>
<td>{{ p.profil }}</td><td>{{ p.tgl_jatuh_tempo }}</td>
<td><a class="btn-wa" href="/kirim_wa/{{ p.nama_pppoe }}">📱 WA</a></td></tr>{% endfor %}</tbody></table>
{% else %}<p style="color:#999;">Tidak ada.</p>{% endif %}</div>

<div class="card card-hariini"><h2>🔔 Hari Ini <span class="badge-count" style="background:#d32f2f;">{{ hari_ini|length }}</span></h2>
{% if hari_ini %}<table><thead><tr><th>Nama</th><th>Telepon</th><th>Paket</th><th>Jatuh Tempo</th><th>Aksi</th></tr></thead>
<tbody>{% for p in hari_ini %}<tr><td><strong>{{ p.nama_pppoe }}</strong></td><td>{{ p.telepon or '-' }}</td>
<td>{{ p.profil }}</td><td>{{ p.tgl_jatuh_tempo }}</td>
<td><a class="btn-wa" href="/kirim_wa/{{ p.nama_pppoe }}">📱 WA</a></td></tr>{% endfor %}</tbody></table>
{% else %}<p style="color:#999;">Tidak ada.</p>{% endif %}</div>

<div class="card card-telat"><h2>⚠️ Telat <span class="badge-count" style="background:#8b0000;">{{ telat|length }}</span></h2>
{% if telat %}<table><thead><tr><th>Nama</th><th>Telepon</th><th>Paket</th><th>Jatuh Tempo</th><th>Aksi</th></tr></thead>
<tbody>{% for p in telat %}<tr><td><strong>{{ p.nama_pppoe }}</strong></td><td>{{ p.telepon or '-' }}</td>
<td>{{ p.profil }}</td><td>{{ p.tgl_jatuh_tempo }}</td>
<td><a class="btn-wa" href="/kirim_wa/{{ p.nama_pppoe }}">📱 WA</a></td></tr>{% endfor %}</tbody></table>
{% else %}<p style="color:#999;">Tidak ada.</p>{% endif %}</div>

<div class="footer">Aplikasi ISP v1.9 | {{ nama_isp }}</div></div></body></html>
"""


HTML_BANNER = """
<!DOCTYPE html><html lang="id"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tagihan - {{ nama_isp }}</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; background: #f5f6f8; min-height: 100vh; padding: 16px; color: #333; }
.wrap { max-width: 440px; margin: 0 auto; }
.header { background: linear-gradient(135deg, #ff0033 0%, #cc0029 100%); color: white; padding: 24px 22px; border-radius: 14px 14px 0 0; }
.brand { font-size: 22px; font-weight: 800; letter-spacing: 0.5px; margin-bottom: 4px; }
.brand-sub { font-size: 11px; opacity: 0.85; letter-spacing: 2px; }
.body-card { background: white; border-radius: 0 0 14px 14px; box-shadow: 0 8px 30px rgba(0,0,0,0.08); }
.alert { background: #fff4f4; border-left: 4px solid #ff0033; margin: 22px 22px 0 22px; padding: 14px 16px; border-radius: 8px; display: flex; gap: 12px; }
.alert-icon { font-size: 24px; flex-shrink: 0; }
.alert-text { font-size: 13px; line-height: 1.5; color: #555; }
.alert-text strong { color: #cc0029; display: block; margin-bottom: 3px; font-size: 14px; }
.section { padding: 22px; }
.greeting { font-size: 14px; color: #555; line-height: 1.6; margin-bottom: 18px; }
.greeting strong { color: #222; }
.info-card { background: #fafbfc; border: 1px solid #eef0f3; border-radius: 10px; padding: 16px; margin-bottom: 18px; }
.info-row { display: flex; justify-content: space-between; padding: 9px 0; font-size: 13px; border-bottom: 1px dashed #eef0f3; }
.info-row:last-child { border-bottom: none; }
.info-row .label { color: #888; }
.info-row .value { font-weight: 600; color: #222; }
.total-card { background: linear-gradient(135deg, #ff0033 0%, #cc0029 100%); color: white; padding: 16px 18px; border-radius: 10px; margin-bottom: 22px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 12px rgba(255,0,51,0.25); }
.total-card .label { font-size: 12px; opacity: 0.9; letter-spacing: 1px; font-weight: 600; }
.total-card .amount { font-size: 22px; font-weight: 800; }
.title { font-size: 13px; font-weight: 700; color: #222; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
.title .bar { width: 3px; height: 16px; background: #ff0033; border-radius: 2px; }
.qris-wrap { background: #fafbfc; border: 1px solid #eef0f3; border-radius: 10px; padding: 18px; text-align: center; margin-bottom: 22px; }
.qris-wrap img { max-width: 190px; width: 100%; background: white; padding: 8px; border-radius: 8px; border: 1px solid #eef0f3; }
.qris-hint { font-size: 11px; color: #888; margin-top: 10px; }
.bank-wrap { background: #fafbfc; border: 1px solid #eef0f3; border-radius: 10px; padding: 14px 16px; margin-bottom: 22px; font-size: 13px; color: #333; line-height: 1.7; }
.bank-wrap strong { color: #cc0029; }
.steps { background: #f0f7ff; border-radius: 10px; padding: 14px 16px; margin-bottom: 20px; }
.steps-title { font-size: 12px; font-weight: 700; color: #0066cc; margin-bottom: 10px; }
.step { display: flex; gap: 10px; font-size: 12px; color: #444; margin-bottom: 8px; line-height: 1.5; }
.step-num { width: 20px; height: 20px; background: #0066cc; color: white; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; flex-shrink: 0; }
.btn-wa { display: flex; align-items: center; justify-content: center; gap: 8px; width: 100%; background: #25D366; color: white; text-align: center; padding: 14px; border-radius: 10px; text-decoration: none; font-weight: 700; font-size: 14px; box-shadow: 0 4px 12px rgba(37,211,102,0.25); }
.footer { text-align: center; padding: 18px; color: #999; font-size: 11px; background: #fafbfc; border-top: 1px solid #eef0f3; line-height: 1.6; border-radius: 0 0 14px 14px; }
.footer strong { color: #666; }
.empty { text-align: center; padding: 50px 22px; }
.empty .icon { font-size: 56px; margin-bottom: 14px; }
</style></head><body>
<div class="wrap">
<div class="header">
<div class="brand">{{ nama_isp }}</div>
<div class="brand-sub">INTERNET SERVICE PROVIDER</div>
</div>
<div class="body-card">
{% if data %}
<div class="alert"><div class="alert-icon">⚠️</div>
<div class="alert-text"><strong>Internet Sementara Diisolir</strong>
Tagihan Anda sudah melewati tanggal jatuh tempo.</div></div>
<div class="section">
<div class="greeting">Halo, <strong>{{ data.nama_lengkap or data.nama_pppoe }}</strong> 👋<br>
Silakan lakukan pembayaran untuk mengaktifkan kembali layanan internet Anda.</div>
<div class="info-card">
<div class="info-row"><span class="label">🆔 ID Pelanggan</span><span class="value">{{ data.nama_pppoe }}</span></div>
<div class="info-row"><span class="label">📦 Paket</span><span class="value">{{ data.profil }}</span></div>
<div class="info-row"><span class="label">📅 Jatuh Tempo</span><span class="value">{{ data.tgl_jatuh_tempo or '-' }}</span></div>
</div>
<div class="total-card"><span class="label">TOTAL TAGIHAN</span>
<span class="amount">Rp {{ '{:,}'.format(data.harga or 0).replace(',', '.') }}</span></div>
<div class="title"><span class="bar"></span> Pembayaran via QRIS</div>
<div class="qris-wrap">
<img src="/static/qris.png" alt="QRIS" onerror="this.style.display='none';this.parentNode.innerHTML='<div style=color:#999;padding:24px;font-size:13px;>📷 QRIS belum tersedia<br><small>Silakan hubungi admin</small></div>';">
<div class="qris-hint">Scan dengan aplikasi bank / e-wallet</div></div>
<div class="title"><span class="bar"></span> Atau Transfer Bank</div>
<div class="bank-wrap"><strong>{{ rekening }}</strong></div>
<div class="steps"><div class="steps-title">📸 CARA KONFIRMASI PEMBAYARAN</div>
<div class="step"><span class="step-num">1</span><span>Screenshot bukti pembayaran Anda</span></div>
<div class="step"><span class="step-num">2</span><span>Kirim ke WhatsApp Admin via tombol di bawah</span></div>
<div class="step"><span class="step-num">3</span><span>Tunggu verifikasi (± 1x24 jam)</span></div></div>
<a href="https://wa.me/{{ wa_admin }}?text=Halo%20Admin%20{{ nama_isp }}%2C%0A%0ASaya%20*{{ data.nama_pppoe }}*%20sudah%20bayar.%0A%0ABerikut%20bukti%20transfer."
class="btn-wa"><span>📱</span> Kirim Bukti Bayar ke Admin</a>
</div>
<div class="footer"><strong>{{ nama_isp }}</strong> &copy; 2026<br>{{ info }}</div>
{% else %}<div class="empty"><div class="icon">🔍</div><h3>Data Tidak Ditemukan</h3></div>{% endif %}
</div></div></body></html>
"""


HTML_IMPORT = """
<!DOCTYPE html><html lang="id"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Import</title>
<style>""" + CSS_UMUM + """
.upload-box { background: #f8f9fa; border: 2px dashed #0066cc; border-radius: 12px; padding: 40px 20px; text-align: center; margin-bottom: 20px; }
.upload-icon { font-size: 60px; margin-bottom: 15px; }
.file-input { display: inline-block; padding: 12px 24px; background: #0066cc; color: white; border-radius: 8px; cursor: pointer; font-weight: 600; }
.file-input input { display: none; }
.file-name { margin-top: 12px; font-size: 13px; color: #666; font-style: italic; }
.btn-submit { background: #00a651; color: white; padding: 14px 40px; border: none; border-radius: 8px; cursor: pointer; font-weight: 700; font-size: 15px; margin-top: 20px; }
.hasil-box { border-radius: 12px; padding: 24px; margin-bottom: 20px; }
.hasil-sukses { background: #e7f9ed; border-left: 4px solid #00a651; }
.hasil-error { background: #ffe7e7; border-left: 4px solid #cc0000; }
.hasil-title { font-size: 18px; font-weight: 700; margin-bottom: 12px; }
.stat-row { display: flex; gap: 20px; margin-bottom: 16px; flex-wrap: wrap; }
.stat-item { background: white; padding: 12px 20px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.05); }
.stat-item .num { font-size: 24px; font-weight: 700; }
.stat-item .label { font-size: 12px; color: #888; }
.detail-log { background: #2d2d2d; color: #e0e0e0; padding: 16px; border-radius: 8px; font-family: monospace; font-size: 12px; line-height: 1.7; max-height: 400px; overflow-y: auto; }
.info-cara { background: #fff8e1; border-left: 4px solid #ffa726; padding: 16px; border-radius: 8px; margin-bottom: 20px; font-size: 13px; line-height: 1.7; color: #666; }
.btn-tpl { display: inline-block; background: #0066cc; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 13px; margin-right: 8px; }
</style></head><body><div class="container">
<h1>📤 Import Pelanggan dari CSV</h1>""" + navbar('imp') + """
{% if hasil and hasil.error %}<div class="hasil-box hasil-error"><div class="hasil-title">❌ Error</div><p>{{ hasil.error }}</p></div>{% endif %}
{% if hasil and hasil.total %}<div class="hasil-box hasil-sukses">
<div class="hasil-title">📊 Hasil Import</div>
<div class="stat-row">
<div class="stat-item"><div class="num" style="color:#0066cc;">{{ hasil.total }}</div><div class="label">Total</div></div>
<div class="stat-item"><div class="num" style="color:#00a651;">{{ hasil.berhasil }}</div><div class="label">Berhasil</div></div>
<div class="stat-item"><div class="num" style="color:#cc0000;">{{ hasil.gagal }}</div><div class="label">Gagal</div></div>
</div>
<div class="detail-log">{% for d in hasil.detail %}<div>{{ d }}</div>{% endfor %}</div>
<div style="margin-top:20px;"><a href="/pelanggan" class="btn-tpl">👥 Lihat Pelanggan</a>
<a href="/import_pelanggan" class="btn-tpl" style="background:#00a651;">📤 Import Lagi</a></div></div>{% endif %}

<div class="info-cara"><strong>📋 Cara Import:</strong>
<ol><li>Download template CSV</li><li>Buka Excel</li><li>Isi data</li><li>Simpan CSV UTF-8</li><li>Upload</li></ol>
<p style="margin-top:12px;"><strong>Wajib:</strong> nama_pppoe, password<br>
<strong>Opsional:</strong> profil, nama_lengkap, alamat, telepon, harga, tgl_jatuh_tempo</p></div>

<div style="margin-bottom:20px;">
<a href="/download_template" class="btn-tpl">📋 Template</a>
<a href="/export_pelanggan" class="btn-tpl" style="background:#00a651;">📥 Export</a></div>

<form action="/import_pelanggan" method="POST" enctype="multipart/form-data">
<div class="upload-box"><div class="upload-icon">📁</div>
<h3>Pilih File CSV</h3><p style="color:#888;font-size:13px;margin:10px 0;">Format: .csv (UTF-8)</p>
<label class="file-input">📎 Pilih File<input type="file" name="file" accept=".csv" required onchange="tampilNama(this)"></label>
<div class="file-name" id="fileName">Belum ada file</div></div>
<div style="text-align:center;"><button type="submit" class="btn-submit">🚀 Mulai Import</button></div>
</form>
<div class="footer">Aplikasi ISP v1.9 | {{ nama_isp }}</div></div>

<script>
function tampilNama(i){var e=document.getElementById('fileName');
if(i.files&&i.files[0]){e.textContent='📎 '+i.files[0].name;e.style.color='#00a651';e.style.fontStyle='normal';}}
</script></body></html>
"""


HTML_BACKUP = """
<!DOCTYPE html><html lang="id"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Backup Database</title>
<style>""" + CSS_UMUM + """</style></head><body><div class="container">
<h1>📦 Backup & Restore Database</h1>""" + navbar('backup') + """

{% if pesan_sukses %}<div class="sukses">✅ {{ pesan_sukses }}</div>{% endif %}
{% if pesan_error %}<div class="error">⚠️ {{ pesan_error }}</div>{% endif %}

<div class="backup-info">
<strong>ℹ️ Informasi:</strong><br>
• Database disimpan sebagai file <code>isp.db</code> (SQLite)<br>
• Backup otomatis dibuat <strong>setiap hari</strong> dan disimpan di folder <code>backup/</code><br>
• <strong>Download DB Aktif</strong> — unduh database yang sedang dipakai<br>
• <strong>Restore</strong> — kembalikan database dari file backup (hati-hati!)
</div>

<h2 style="margin-top:20px;">⚡ Aksi Cepat</h2>
<a href="/download_db_sekarang" class="btn-big btn-download">📥 Download Database Aktif</a>
<a href="/backup_sekarang" class="btn-big btn-restore">📦 Buat Backup Sekarang</a>

<h2 style="margin-top:30px;">📂 Daftar Backup ({{ daftar|length }} file)</h2>

{% if daftar and daftar|length > 0 %}
<table>
<thead><tr><th>No</th><th>Nama File</th><th>Ukuran</th><th>Tanggal</th><th>Aksi</th></tr></thead>
<tbody>
{% for b in daftar %}
<tr>
<td>{{ loop.index }}</td>
<td><strong>{{ b.nama }}</strong></td>
<td>{{ b.ukuran_str }}</td>
<td>{{ b.tanggal }}</td>
<td>
<a class="btn-big btn-dl-single" href="/download_backup/{{ b.nama }}">📥</a>
<form action="/restore_backup/{{ b.nama }}" method="POST" style="display:inline;" onsubmit="return confirm('Yakin RESTORE dari {{ b.nama }}? Database saat ini akan digantikan.');">
<button type="submit" class="btn-big btn-restore-single">🔄</button>
</form>
<form action="/hapus_backup/{{ b.nama }}" method="POST" style="display:inline;" onsubmit="return confirm('Hapus backup {{ b.nama }}?');">
<button type="submit" class="btn-big btn-hapus-single">🗑️</button>
</form>
</td>
</tr>
{% endfor %}
</tbody>
</table>
{% else %}
<div class="empty"><div class="empty-icon">📭</div><h3>Belum ada backup</h3>
<p>Klik <strong>Buat Backup Sekarang</strong> untuk memulai.</p></div>
{% endif %}

<div class="upload-box">
<h3>📤 Restore dari File Upload</h3>
<p>Upload file <code>.db</code> dari komputer lain untuk restore.</p>
<form action="/upload_restore" method="POST" enctype="multipart/form-data">
<label class="upload-btn">
📎 Pilih File .db
<input type="file" name="file_db" accept=".db" required onchange="tampilNama(this)">
</label>
<div id="fileName" style="margin-top:10px;font-size:13px;color:#666;font-style:italic;">Belum ada file</div>
<br><br>
<button type="submit" class="btn-big btn-restore" onclick="return confirm('Yakin restore dari file upload? Database saat ini akan digantikan.');">🔄 Restore Sekarang</button>
</form>
</div>

<div class="warning-box">
<strong>⚠️ Peringatan:</strong> Restore akan <strong>menggantikan database yang sekarang</strong>. Sebelum restore, sistem akan otomatis membuat backup "sebelum-restore" untuk keamanan.
</div>

<div class="footer">Aplikasi ISP v1.9 | Backup & Restore</div>
</div>

<script>
function tampilNama(i){var e=document.getElementById('fileName');
if(i.files&&i.files[0]){e.textContent='📎 '+i.files[0].name;e.style.color='#00a651';e.style.fontStyle='normal';}}
</script></body></html>
"""


HTML_PENGATURAN = """
<!DOCTYPE html><html lang="id"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Pengaturan</title>
<style>""" + CSS_UMUM + """</style></head><body><div class="container">
<h1>⚙️ Pengaturan Aplikasi</h1>""" + navbar('set') + """

{% if pesan_sukses %}<div class="sukses">✅ {{ pesan_sukses }}</div>{% endif %}
{% if pesan_error %}<div class="error">⚠️ {{ pesan_error }}</div>{% endif %}

<div class="info">
<div>Ubah identitas ISP, nomor WA admin, rekening bank, dan info banner.</div>
</div>

<div class="settings-section">
<h2>🔌 Status MikroTik</h2>
<table>
<tr><td><strong>IP MikroTik</strong></td><td>{{ info_mikrotik.ip }}</td></tr>
<tr><td><strong>Status Koneksi</strong></td>
<td>{% if info_mikrotik.status == 'OK' %}<span style="color:#00a651;font-weight:bold;">● Terhubung</span>{% else %}<span style="color:#cc0000;font-weight:bold;">● Gagal</span>{% endif %}</td></tr>
{% if info_mikrotik.status == 'OK' %}
<tr><td><strong>Nama Router</strong></td><td>{{ info_mikrotik.nama }}</td></tr>
<tr><td><strong>Versi RouterOS</strong></td><td>{{ info_mikrotik.versi }}</td></tr>
{% else %}
<tr><td><strong>Error</strong></td><td style="color:#cc0000;font-size:12px;">{{ info_mikrotik.pesan }}</td></tr>
{% endif %}
</table>
<p style="margin-top:12px;font-size:12px;color:#888;">ℹ️ Support MikroTik RouterOS v6 dan v7.</p>
</div>

<div class="settings-section">
<h2>🏢 Identitas ISP</h2>
<form action="/simpan_pengaturan" method="POST">
<div class="form-group">
<label>Nama ISP / Brand</label>
<input type="text" name="nama_isp" value="{{ pengaturan.nama_isp }}" required>
</div>
<div class="form-group">
<label>Nomor WhatsApp Admin</label>
<input type="text" name="wa_admin" value="{{ pengaturan.wa_admin }}" required>
<div class="hint">Format: 628xxxxxxxxxx</div>
</div>
<div class="form-group">
<label>Rekening Bank / E-Wallet</label>
<input type="text" name="rekening" value="{{ pengaturan.rekening }}" required>
</div>
<div class="form-group">
<label>Info Tambahan di Footer Banner</label>
<textarea name="info" rows="3">{{ pengaturan.info }}</textarea>
</div>
<button type="submit" class="btn-primary">💾 Simpan Pengaturan</button>
</form>
</div>

<div class="settings-section">
<h2>📷 Gambar QRIS</h2>
<div style="display:flex;gap:20px;align-items:flex-start;flex-wrap:wrap;">
<div style="flex:1;min-width:220px;">
<img src="/static/qris.png?t={{ time_now }}" alt="QRIS" class="qris-preview" onerror="this.style.display='none';this.parentNode.innerHTML='<p style=color:#999;font-size:13px;>Belum ada QRIS</p>';">
</div>
<div style="flex:2;min-width:280px;">
<form action="/upload_qris" method="POST" enctype="multipart/form-data">
<div class="form-group">
<label>Pilih File QRIS</label>
<input type="file" name="qris" accept="image/png,image/jpeg" required>
</div>
<button type="submit" class="btn-primary">📤 Upload QRIS</button>
</form>
</div>
</div>
</div>

<div class="settings-section">
<h2>ℹ️ Informasi Aplikasi</h2>
<table>
<tr><td><strong>Versi</strong></td><td>v1.9 (Android)</td></tr>
<tr><td><strong>MikroTik IP</strong></td><td>""" + MIKROTIK_IP + """</td></tr>
<tr><td><strong>Database</strong></td><td style="font-size:11px;word-break:break-all;">""" + DB_FILE + """</td></tr>
<tr><td><strong>Config</strong></td><td style="font-size:11px;word-break:break-all;">""" + CONFIG_FILE + """</td></tr>
<tr><td><strong>Backup Dir</strong></td><td style="font-size:11px;word-break:break-all;">""" + BACKUP_DIR + """</td></tr>
</table>
</div>

<div class="footer">Aplikasi ISP v1.9 | Pengaturan</div>
</div></body></html>
"""


# ============================================================
#   ROUTES
# ============================================================
@app.route('/')
def home():
    interfaces = get_interfaces()
    if interfaces is None:
        return render_template_string(HTML_INTERFACE, interfaces=[],
            error="Gagal konek ke MikroTik. Cek WiFi & config.ini.",
            nama_isp=get_nama_isp())
    return render_template_string(HTML_INTERFACE, interfaces=interfaces,
        error=None, nama_isp=get_nama_isp())


@app.route('/pelanggan')
def pelanggan():
    daftar = db_get_pelanggan_semua()
    jumlah_aktif = sum(1 for p in daftar if p.get('status') == 'aktif')
    jumlah_isolir = sum(1 for p in daftar if p.get('status') == 'isolir')
    pesan_sukses = None; pesan_error = None; pesan_warn = None
    r = request.args.get('sukses')
    if r == 'tambah': pesan_sukses = "Pelanggan baru berhasil ditambahkan."
    elif r == 'edit': pesan_sukses = "Data pelanggan berhasil diupdate."
    elif r == 'hapus': pesan_sukses = "Pelanggan berhasil dihapus."
    elif r == 'isolir': pesan_sukses = "Pelanggan berhasil diisolir."
    elif r == 'aktifkan': pesan_sukses = "Pelanggan berhasil diaktifkan."
    elif r == 'cek': pesan_warn = request.args.get('msg', 'Cek selesai.')
    e = request.args.get('error')
    if e: pesan_error = f"Gagal: {e}"
    return render_template_string(HTML_PELANGGAN,
        pelanggan=daftar, jumlah_aktif=jumlah_aktif, jumlah_isolir=jumlah_isolir,
        pesan_sukses=pesan_sukses, pesan_error=pesan_error, pesan_warn=pesan_warn,
        nama_isp=get_nama_isp())


@app.route('/monitoring')
def monitoring():
    daftar_db = db_get_pelanggan_semua()
    aktif = get_active_pppoe()
    traffic = get_live_traffic(jeda=1.0)
    aktif_map = {}
    for a in aktif:
        aktif_map[a.get('name', '')] = {
            'ip': a.get('address', '-'), 'uptime': a.get('uptime', '-')}
    pelanggan_data = []; jumlah_online = 0
    for p in daftar_db:
        nama = p['nama_pppoe']; online = nama in aktif_map
        if online: jumlah_online += 1
        t = traffic.get(nama, {})
        pelanggan_data.append({
            'nama_pppoe': nama, 'nama_lengkap': p.get('nama_lengkap') or '',
            'online': online, 'ip': aktif_map.get(nama, {}).get('ip', ''),
            'uptime': aktif_map.get(nama, {}).get('uptime', ''),
            'rx_rate_str': t.get('rx_rate_str', '0 B/s'),
            'tx_rate_str': t.get('tx_rate_str', '0 B/s'),
            'rx_total_str': t.get('rx_total_str', '0 B'),
            'tx_total_str': t.get('tx_total_str', '0 B')})
    return render_template_string(HTML_MONITORING,
        pelanggan_data=pelanggan_data, jumlah_online=jumlah_online,
        jumlah_offline=len(daftar_db) - jumlah_online,
        total_pelanggan=len(daftar_db), nama_isp=get_nama_isp())


@app.route('/notifikasi')
def notifikasi():
    return render_template_string(HTML_NOTIFIKASI,
        h3=dapatkan_pelanggan_h3(), hari_ini=dapatkan_pelanggan_hari_ini(),
        telat=dapatkan_pelanggan_telat(), pesan_sukses=request.args.get('sukses'),
        nama_isp=get_nama_isp())


@app.route('/banner')
def banner_isolir():
    nama = request.args.get('user', '')
    data = db_get_pelanggan(nama) if nama else None
    return render_template_string(HTML_BANNER,
        nama=nama, data=data, nama_isp=get_nama_isp(),
        wa_admin=get_wa_admin(), rekening=get_rekening(),
        info=get_info_tambahan())


@app.route('/static/<path:filename>')
def static_files(filename):
    user_static = user_data_path(os.path.join('static', filename))
    if os.path.exists(user_static):
        return send_from_directory(user_data_path('static'), filename)
    try:
        return send_from_directory(resource_path('static'), filename)
    except Exception:
        return "Not found", 404


@app.route('/kirim_wa/<nama_pppoe>')
def kirim_wa_pelanggan(nama_pppoe):
    data = db_get_pelanggan(nama_pppoe)
    if not data: return redirect('/notifikasi?sukses=Pelanggan+tidak+ditemukan')
    if not data.get('telepon'): return redirect('/notifikasi?sukses=Nomor+kosong')
    pesan = buat_pesan_tagihan(
        data.get('nama_lengkap') or data['nama_pppoe'],
        data.get('tgl_jatuh_tempo', '-'), data.get('harga', 0),
        data.get('profil', '-'), data.get('nama_pppoe', ''))
    if kirim_whatsapp(data['telepon'], pesan):
        return redirect(f'/notifikasi?sukses=WhatsApp+dibuka+untuk+{nama_pppoe}')
    return redirect('/notifikasi?sukses=Gagal+buka+WhatsApp')


# ============================================================
#   SYNC ROUTE
# ============================================================
@app.route('/sync_mikrotik', methods=['POST'])
def sync_mikrotik_route():
    hasil = sync_dari_mikrotik()
    msg = f"Sync selesai. {hasil['ditambah']} ditambah, {hasil['dilewati']} dilewati, {hasil['error']} error."
    return redirect(f'/pelanggan?sukses=cek&msg={quote(msg)}')


# ============================================================
#   BACKUP ROUTES
# ============================================================
@app.route('/backup')
def backup_page():
    daftar = daftar_backup()
    return render_template_string(HTML_BACKUP,
        daftar=daftar,
        pesan_sukses=request.args.get('sukses'),
        pesan_error=request.args.get('error'),
        nama_isp=get_nama_isp())


@app.route('/backup_sekarang')
def backup_sekarang():
    hasil = backup_database()
    if hasil:
        return redirect(f'/backup?sukses=Backup+berhasil+dibuat:+{hasil}')
    return redirect('/backup?error=Gagal+membuat+backup')


@app.route('/download_backup/<nama_file>')
def download_backup(nama_file):
    pastikan_folder_backup()
    return send_from_directory(BACKUP_DIR, nama_file, as_attachment=True)


@app.route('/download_db_sekarang')
def download_db_sekarang():
    with open(DB_FILE, 'rb') as f:
        data = f.read()
    tanggal = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    filename = f'isp-aktif-{tanggal}.db'
    return Response(data, mimetype='application/octet-stream',
        headers={'Content-Disposition': f'attachment; filename={filename}'})


@app.route('/hapus_backup/<nama_file>', methods=['POST'])
def hapus_backup_route(nama_file):
    if hapus_backup(nama_file):
        return redirect('/backup?sukses=Backup+dihapus')
    return redirect('/backup?error=Gagal+hapus')


@app.route('/restore_backup/<nama_file>', methods=['POST'])
def restore_backup_route(nama_file):
    if restore_database(nama_file):
        return redirect('/backup?sukses=Database+berhasil+di-restore')
    return redirect('/backup?error=Gagal+restore')


@app.route('/upload_restore', methods=['POST'])
def upload_restore():
    file = request.files.get('file_db')
    if not file or not file.filename:
        return redirect('/backup?error=File+tidak+ditemukan')
    if not file.filename.endswith('.db'):
        return redirect('/backup?error=File+harus+.db')
    try:
        pastikan_folder_backup()
        tgl = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        shutil.copy2(DB_FILE, os.path.join(BACKUP_DIR, f'sebelum-upload-{tgl}.db'))
        file.save(DB_FILE)
        _log(f"OK Restore dari upload: {file.filename}")
        return redirect('/backup?sukses=Database+berhasil+di-restore+dari+file')
    except Exception as e:
        _log(f"GAGAL restore upload: {e}")
        return redirect('/backup?error=Gagal+upload')


# ============================================================
#   PENGATURAN
# ============================================================
@app.route('/pengaturan')
def pengaturan():
    data = {
        'nama_isp': get_nama_isp(),
        'wa_admin': get_wa_admin(),
        'rekening': get_rekening(),
        'info': get_info_tambahan(),
    }
    info_mikrotik = cek_koneksi_mikrotik()
    return render_template_string(HTML_PENGATURAN,
        pengaturan=data,
        pesan_sukses=request.args.get('sukses'),
        pesan_error=request.args.get('error'),
        time_now=int(time.time()),
        nama_isp=get_nama_isp(),
        info_mikrotik=info_mikrotik)


@app.route('/simpan_pengaturan', methods=['POST'])
def simpan_pengaturan():
    try:
        db_set_pengaturan('nama_isp', request.form.get('nama_isp', '').strip())
        db_set_pengaturan('wa_admin', request.form.get('wa_admin', '').strip())
        db_set_pengaturan('rekening', request.form.get('rekening', '').strip())
        db_set_pengaturan('info', request.form.get('info', '').strip())
        return redirect('/pengaturan?sukses=Pengaturan+berhasil+disimpan')
    except Exception as e:
        _log(f"Error simpan pengaturan: {e}")
        return redirect('/pengaturan?error=Gagal+menyimpan')


@app.route('/upload_qris', methods=['POST'])
def upload_qris():
    try:
        file = request.files.get('qris')
        if not file or not file.filename:
            return redirect('/pengaturan?error=File+tidak+ditemukan')
        static_dir = user_data_path('static')
        os.makedirs(static_dir, exist_ok=True)
        filepath = os.path.join(static_dir, 'qris.png')
        file.save(filepath)
        _log(f"OK QRIS disimpan: {filepath}")
        return redirect('/pengaturan?sukses=QRIS+berhasil+diupload')
    except Exception as e:
        _log(f"Error upload QRIS: {e}")
        return redirect('/pengaturan?error=Gagal+upload+QRIS')


# ============================================================
#   EXPORT / IMPORT
# ============================================================
@app.route('/export_pelanggan')
def export_pelanggan():
    daftar = db_get_pelanggan_semua()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['nama_pppoe','password','profil','nama_lengkap','alamat',
                     'telepon','harga','tgl_jatuh_tempo','status'])
    for p in daftar:
        writer.writerow([
            p.get('nama_pppoe',''), p.get('password',''), p.get('profil',''),
            p.get('nama_lengkap') or '', p.get('alamat') or '',
            p.get('telepon') or '', p.get('harga') or 0,
            p.get('tgl_jatuh_tempo') or '', p.get('status') or 'aktif'])
    output.seek(0)
    filename = f"pelanggan-{date.today().isoformat()}.csv"
    return Response(output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'})


@app.route('/download_template')
def download_template():
    content = (
        "nama_pppoe,password,profil,nama_lengkap,alamat,telepon,harga,tgl_jatuh_tempo\n"
        "budi,budi123,5Mbps,Budi Santoso,Jl. Merdeka No.5,081234567890,125000,2026-10-25\n"
        "siti,siti123,10Mbps,Siti Aminah,Jl. Sudirman No.10,081234567891,150000,2026-10-26\n")
    return Response(content, mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=template-import.csv'})


@app.route('/import_pelanggan', methods=['GET', 'POST'])
def import_pelanggan():
    if request.method == 'GET':
        return render_template_string(HTML_IMPORT, hasil=None, nama_isp=get_nama_isp())
    file = request.files.get('file')
    if not file or not file.filename:
        return render_template_string(HTML_IMPORT, hasil={'error': 'File tidak ditemukan.'}, nama_isp=get_nama_isp())
    if not file.filename.lower().endswith('.csv'):
        return render_template_string(HTML_IMPORT, hasil={'error': 'File harus .csv'}, nama_isp=get_nama_isp())
    try:
        content = file.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        try:
            file.seek(0); content = file.read().decode('latin-1')
        except Exception as e:
            return render_template_string(HTML_IMPORT, hasil={'error': f'Gagal baca: {e}'}, nama_isp=get_nama_isp())
    try:
        reader = csv.DictReader(io.StringIO(content)); rows = list(reader)
    except Exception as e:
        return render_template_string(HTML_IMPORT, hasil={'error': f'Format tidak valid: {e}'}, nama_isp=get_nama_isp())
    if not rows:
        return render_template_string(HTML_IMPORT, hasil={'error': 'File kosong'}, nama_isp=get_nama_isp())
    berhasil = 0; gagal = 0; detail = []
    for i, row in enumerate(rows, start=2):
        nama = (row.get('nama_pppoe') or '').strip()
        password = (row.get('password') or '').strip()
        profil = (row.get('profil') or 'default').strip()
        nama_lengkap = (row.get('nama_lengkap') or '').strip()
        alamat = (row.get('alamat') or '').strip()
        telepon = (row.get('telepon') or '').strip()
        tgl_jt = (row.get('tgl_jatuh_tempo') or '').strip()
        try: harga = int(row.get('harga') or 0)
        except: harga = 0
        if not nama or not password:
            detail.append(f"❌ Baris {i}: nama atau password kosong"); gagal += 1; continue
        if db_get_pelanggan(nama):
            detail.append(f"⚠️ Baris {i}: '{nama}' sudah ada"); gagal += 1; continue
        if profil in PAKET_BANDWIDTH:
            pastikan_profil_ada(profil, PAKET_BANDWIDTH[profil])
        if not mt_tambah_secret(nama, password, profil):
            detail.append(f"❌ Baris {i}: GAGAL MikroTik"); gagal += 1; continue
        try:
            db_tambah_pelanggan(nama, password, profil, nama_lengkap,
                                 alamat, telepon, harga, tgl_jt)
            detail.append(f"✅ Baris {i}: OK — {nama}"); berhasil += 1
        except Exception as ex:
            detail.append(f"❌ Baris {i}: GAGAL DB — {ex}"); gagal += 1
    return render_template_string(HTML_IMPORT, hasil={
        'berhasil': berhasil, 'gagal': gagal, 'total': len(rows), 'detail': detail},
        nama_isp=get_nama_isp())


@app.route('/tambah_pelanggan', methods=['POST'])
def proses_tambah():
    nama = request.form.get('nama_pppoe', '').strip()
    password = request.form.get('password', '').strip()
    paket = request.form.get('paket', 'default').strip()
    profil_manual = request.form.get('profil_manual', '').strip()
    nama_lengkap = request.form.get('nama_lengkap', '').strip()
    alamat = request.form.get('alamat', '').strip()
    telepon = request.form.get('telepon', '').strip()
    harga = int(request.form.get('harga', 0) or 0)
    tgl_jt = request.form.get('tgl_jatuh_tempo', '').strip()
    profil = profil_manual if paket == '__manual__' and profil_manual else (paket if paket != '__manual__' else 'default')
    if not nama or not password: return redirect('/pelanggan?error=tambah-kosong')
    if db_get_pelanggan(nama): return redirect('/pelanggan?error=duplikat')
    if profil in PAKET_BANDWIDTH: pastikan_profil_ada(profil, PAKET_BANDWIDTH[profil])
    if not mt_tambah_secret(nama, password, profil): return redirect('/pelanggan?error=mikrotik')
    try:
        db_tambah_pelanggan(nama, password, profil, nama_lengkap, alamat, telepon, harga, tgl_jt)
    except Exception as ex:
        _log(f"Error SQLite: {ex}"); return redirect('/pelanggan?error=database')
    return redirect('/pelanggan?sukses=tambah')


@app.route('/edit_pelanggan', methods=['POST'])
def proses_edit():
    nama = request.form.get('nama_pppoe', '').strip()
    password = request.form.get('password', '').strip()
    paket = request.form.get('paket', '').strip()
    profil_manual = request.form.get('profil_manual', '').strip()
    nama_lengkap = request.form.get('nama_lengkap', '').strip()
    alamat = request.form.get('alamat', '').strip()
    telepon = request.form.get('telepon', '').strip()
    harga = int(request.form.get('harga', 0) or 0)
    tgl_jt = request.form.get('tgl_jatuh_tempo', '').strip()
    profil = profil_manual if paket == '__manual__' and profil_manual else (paket if paket != '__manual__' else 'default')
    if not nama: return redirect('/pelanggan?error=edit-kosong')
    if profil in PAKET_BANDWIDTH: pastikan_profil_ada(profil, PAKET_BANDWIDTH[profil])
    data = db_get_pelanggan(nama); status = data.get('status') if data else 'aktif'
    if status != 'isolir': mt_edit_secret(nama, password, profil)
    db_edit_pelanggan(nama, password, profil, nama_lengkap, alamat, telepon, harga, tgl_jt, status)
    return redirect('/pelanggan?sukses=edit')


@app.route('/hapus_pelanggan', methods=['POST'])
def proses_hapus():
    nama = request.form.get('nama_pppoe', '').strip()
    if not nama: return redirect('/pelanggan?error=hapus')
    mt_hapus_secret(nama); db_hapus_pelanggan(nama)
    return redirect('/pelanggan?sukses=hapus')


@app.route('/isolir_pelanggan', methods=['POST'])
def proses_isolir():
    nama = request.form.get('nama_pppoe', '').strip()
    if isolir_pelanggan(nama): return redirect('/pelanggan?sukses=isolir')
    return redirect('/pelanggan?error=isolir')


@app.route('/aktifkan_pelanggan', methods=['POST'])
def proses_aktifkan():
    nama = request.form.get('nama_pppoe', '').strip()
    if aktifkan_pelanggan(nama): return redirect('/pelanggan?sukses=aktifkan')
    return redirect('/pelanggan?error=aktifkan')


@app.route('/cek_otomatis', methods=['POST'])
def proses_cek_otomatis():
    diisolir = cek_dan_isolir_otomatis()
    msg = f"Cek selesai. {len(diisolir)} diisolir: {', '.join(diisolir)}" if diisolir else "Cek selesai. Tidak ada yang perlu diisolir."
    return redirect(f'/pelanggan?sukses=cek&msg={quote(msg)}')


@app.route('/<path:path>')
def catch_all(path):
    return redirect('/')


# ============================================================
#   NOTE: Aplikasi dijalankan dari main.py (Kivy) untuk APK
#         Jangan jalankan app.py langsung di Android.
# ============================================================