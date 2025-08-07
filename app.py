import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from flask import (
    Flask, jsonify, render_template, request, send_from_directory,
    redirect, url_for, flash, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
#from uploads import get_db_connection
# Cấu hình
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'*', 'txt', 'pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png', 'gif', 'zip', 'rar', 'mp4', 'mp3'}
MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100 MB

app = Flask(__name__)
app.secret_key = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DB_PATH = 'file_share.db'

# --- DB helpers ---
def get_or_create_share_link_for_file(file_id):
    with get_db() as db:
        existing = db.execute("SELECT * FROM share_links WHERE file_id = ?", (file_id,)).fetchone()
        if existing:
            return existing['link_id']
        new_link = generate_link()
        db.execute(
            "INSERT INTO share_links (link_id, file_id, created_at) VALUES (?, ?, ?)",
            (new_link, file_id, datetime.utcnow().isoformat())
        )
        return new_link


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY,
            stored_name TEXT NOT NULL,
            original_name TEXT NOT NULL,
            privacy TEXT NOT NULL,
            expire_date TEXT,
            download_limit INTEGER,
            downloads INTEGER DEFAULT 0,
            allowed_emails TEXT,
            password_hash TEXT,
            folder_id TEXT,
            created_at TEXT NOT NULL
        )
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS share_links (
            link_id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(file_id) REFERENCES files(id)
        )
        """)
init_db()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def is_expired(expire_date_str):
    if not expire_date_str or expire_date_str == "never":
        return False
    try:
        expire_date = datetime.fromisoformat(expire_date_str)
        return datetime.utcnow() > expire_date
    except:
        return False

def generate_link():
    return uuid.uuid4().hex

# --- Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/share_link/<file_id>')
def fetch_share_link(file_id):
    link_id = get_or_create_share_link_for_file(file_id)
    share_url = url_for('access_shared', link_id=link_id, _external=True)
    return jsonify({'share_link': share_url})


@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        if 'file' in request.files:
            file = request.files['file']
            if file and file.filename != '':
                filename = file.filename
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                share_link = request.host_url + 'download/' + filename
                return render_template('upload.html', share_link=share_link)
    return render_template('upload.html')
@app.route('/download')
def download():
    with get_db() as db:
        rows = db.execute("SELECT * FROM files ORDER BY created_at DESC").fetchall()
    files = []
    for r in rows:
        files.append({
            'id': r['id'],
            'original_name': r['original_name'],
            'stored_name': r['stored_name'],
            'privacy': r['privacy'],
            'downloads': r['downloads'],
            'expire_date': r['expire_date'],
            'download_limit': r['download_limit'],
            'allowed_emails': r['allowed_emails'],
            'folder_id': r['folder_id'],
            'is_expired': is_expired(r['expire_date'])
        })
    return render_template('download.html', files=files)

@app.route('/download/<link>', methods=['GET'])
def download_file(link):
    with get_db() as db:
        # cố gắng lấy theo share link
        link_row = db.execute("SELECT * FROM share_links WHERE link_id = ?", (link,)).fetchone()
        if link_row:
            file_row = db.execute("SELECT * FROM files WHERE id = ?", (link_row['file_id'],)).fetchone()
        else:
            # fallback: trực tiếp stored_name
            file_row = db.execute("SELECT * FROM files WHERE stored_name = ?", (link,)).fetchone()

    if not file_row:
        abort(404, "File không tồn tại.")

    if is_expired(file_row['expire_date']):
        abort(403, "File đã hết hạn.")

    if file_row['download_limit'] is not None and file_row['downloads'] >= file_row['download_limit']:
        abort(403, "Đã vượt quá giới hạn lượt tải.")

    if file_row['password_hash']:
        provided = request.args.get('password', '')
        if not check_password_hash(file_row['password_hash'], provided):
            return "Yêu cầu mật khẩu đúng để tải file.", 403

    # (có thể kiểm tra allowed_emails ở đây nếu muốn)

    # tăng lượt tải
    with get_db() as db:
        db.execute("UPDATE files SET downloads = downloads + 1 WHERE id = ?", (file_row['id'],))

    return send_from_directory(app.config['UPLOAD_FOLDER'], file_row['stored_name'], as_attachment=True,
                               download_name=file_row['original_name'])

@app.route('/share/<link_id>', methods=['GET', 'POST'])
def access_shared(link_id):
    with get_db() as db:
        link_row = db.execute("SELECT * FROM share_links WHERE link_id = ?", (link_id,)).fetchone()
        if not link_row:
            abort(404, "Link không tồn tại.")
        file_row = db.execute("SELECT * FROM files WHERE id = ?", (link_row['file_id'],)).fetchone()

    if not file_row:
        abort(404, "File không tồn tại.")

    expired = is_expired(file_row['expire_date'])
    download_disabled = False
    reason = None
    if expired:
        download_disabled = True
        reason = "File đã hết hạn."
    elif file_row['download_limit'] is not None and file_row['downloads'] >= file_row['download_limit']:
        download_disabled = True
        reason = "Đã vượt quá giới hạn lượt tải."

    password_required = bool(file_row['password_hash'])
    password_ok = False
    if request.method == 'POST' and password_required:
        pwd = request.form.get('password', '')
        if check_password_hash(file_row['password_hash'], pwd):
            password_ok = True
        else:
            flash("Mật khẩu không đúng.")
    elif not password_required:
        password_ok = True

    share_link = url_for('access_shared', link_id=link_id, _external=True)
    download_link = url_for('download_file', link=link_id, _external=True)
    file_info = {
        'original_name': file_row['original_name'],
        'privacy': file_row['privacy'],
        'downloads': file_row['downloads'],
        'expire_date': file_row['expire_date'],
        'download_limit': file_row['download_limit'],
        'allowed_emails': file_row['allowed_emails'],
        'password_required': password_required and not password_ok,
        'download_disabled': download_disabled or (password_required and not password_ok),
        'reason': reason,
        'link': download_link
    }

    return render_template('shared_file.html', file_info=file_info, share_link=share_link)

@app.route('/delete/<filename>')
def delete_file(filename):
    with get_db() as db:
        row = db.execute("SELECT * FROM files WHERE stored_name = ?", (filename,)).fetchone()
        if not row:
            flash("Không tìm thấy file!")
            return redirect(url_for('download'))
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], row['stored_name']))
        except:
            pass
        db.execute("DELETE FROM share_links WHERE file_id = ?", (row['id'],))
        db.execute("DELETE FROM files WHERE id = ?", (row['id'],))
        flash("Đã xoá file thành công!")
    return redirect(url_for('download'))

@app.route('/preview/<stored_name>')
def preview(stored_name):
    return send_from_directory(app.config['UPLOAD_FOLDER'], stored_name)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
