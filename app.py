from flask import Flask, render_template, request, send_from_directory, redirect, url_for, flash
import os

# Cấu hình
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png', 'gif', 'zip', 'rar', 'mp4', 'mp3'}
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB

app = Flask(__name__)
app.secret_key = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

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
    files = os.listdir(app.config['UPLOAD_FOLDER'])
    return render_template('download.html', files=files)

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

@app.route('/delete/<filename>')
def delete_file(filename):
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(path):
        os.remove(path)
        flash("Đã xoá file thành công!")
    else:
        flash("Không tìm thấy file!")
    return redirect(url_for('download'))

@app.route('/share/<filename>')
def share_link(filename):
    link = request.host_url.rstrip('/') + url_for('download_file', filename=filename)
    flash(f"Link chia sẻ: {link}")
    return redirect(url_for('download'))

if __name__ == '__main__':
    app.run(debug=True)