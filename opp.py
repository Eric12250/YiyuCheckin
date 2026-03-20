from flask import Flask, render_template, request, jsonify
from datetime import datetime
import sqlite3
import os
import sys
import qrcode
import zipfile
import io
import shutil

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# 設定 template_folder 指向正確的位置
app = Flask(__name__, template_folder=resource_path('templates'))

# 初始化資料庫：模擬從收費系統匯入名單
def init_db():
    conn = sqlite3.connect('yiyu_event.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendees (
            id TEXT PRIMARY KEY,
            name TEXT,
            is_checked_in INTEGER DEFAULT 0,
            check_in_time TEXT
        )
    ''')
    # 從 txt 檔案讀取名單 (格式: QR代碼,姓名)
    test_data = []
    try:
        with open(resource_path('attendees.txt'), 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and ',' in line:
                    qr_id, name = line.split(',', 1)
                    test_data.append((qr_id.strip(), name.strip()))
    except FileNotFoundError:
        pass

    if test_data:
        cursor.execute("DELETE FROM attendees") # 每次重啟或上傳都清空原有資料
        cursor.executemany('INSERT OR IGNORE INTO attendees (id, name, is_checked_in) VALUES (?, ?, 0)', test_data)
        
        # 產生 QR Code 圖片
        if os.path.exists('qrcodes'):
            shutil.rmtree('qrcodes')
        os.makedirs('qrcodes')
            
        print("開始產生 QR Code...")
        for qr_id, name in test_data:
            # 設定安全的檔名，避免特殊字元
            safe_name = "".join(x for x in name if x.isalnum() or x in " _-")
            filename = os.path.join("qrcodes", f"{qr_id}_{safe_name}.png")
            
            # 給強制覆蓋
            try:
                img = qrcode.make(qr_id)
                img.save(filename)
            except Exception as e:
                print(f"❌ 無法產生 {name} 的 QR Code: {e}")
                    
    conn.commit()
    conn.close()

from flask import send_file

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin')
def admin_page():
    return render_template('admin.html')

@app.route('/status')
def system_status():
    conn = sqlite3.connect('yiyu_event.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM attendees')
    total = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM attendees WHERE is_checked_in = 1')
    arrived = cursor.fetchone()[0]
    conn.close()
    return jsonify({"total": total, "arrived": arrived})

@app.route('/admin/status')
def admin_status():
    return system_status()

@app.route('/admin/upload', methods=['POST'])
def admin_upload():
    content = request.json.get('data', '')
    if not content.strip():
        return jsonify({"status": "error", "message": "內容不可為空！"})
        
    try:
        with open(resource_path('attendees.txt'), 'w', encoding='utf-8') as f:
            f.write(content.strip())
        init_db()  # 寫入後立即觸發初始化資料庫與產生 QR Code
        return jsonify({"status": "success", "message": "名單更新成功並已產生全新 QR Code！"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"發生錯誤：{str(e)}"})

@app.route('/admin/download_qrcodes')
def download_qrcodes():
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        if os.path.exists('qrcodes'):
            for root, dirs, files in os.walk('qrcodes'):
                for file in files:
                    file_path = os.path.join(root, file)
                    zf.write(file_path, arcname=file)
    memory_file.seek(0)
    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name='Yiyu_QRCodes.zip'
    )

@app.route('/checkin', methods=['POST'])
def checkin():
    ticket_id = request.json.get('ticket_id')
    conn = sqlite3.connect('yiyu_event.db')
    cursor = conn.cursor()

    # 查詢票券
    cursor.execute('SELECT name, is_checked_in FROM attendees WHERE id = ?', (ticket_id,))
    result = cursor.fetchone()

    if not result:
        return jsonify({"status": "fail", "message": "無效票券！"})

    name, is_checked_in = result
    if is_checked_in:
        return jsonify({"status": "warning", "message": f"重複！{name} 已於剛才報到"})

    # 更新狀態
    now = datetime.now().strftime("%H:%M:%S")
    cursor.execute('UPDATE attendees SET is_checked_in = 1, check_in_time = ? WHERE id = ?', (now, ticket_id))
    conn.commit()

    # 計算統計人數
    cursor.execute('SELECT COUNT(*) FROM attendees')
    total = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM attendees WHERE is_checked_in = 1')
    arrived = cursor.fetchone()[0]

    conn.close()
    return jsonify({
        "status": "success",
        "name": name,
        "total": total,
        "arrived": arrived
    })

@app.route('/reset', methods=['POST'])
def reset_checkins():
    conn = sqlite3.connect('yiyu_event.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE attendees SET is_checked_in = 0, check_in_time = NULL')
    conn.commit()
    
    # 重新計算總人數
    cursor.execute('SELECT COUNT(*) FROM attendees')
    total = cursor.fetchone()[0]
    conn.close()
    
    return jsonify({"status": "success", "message": "所有報到紀錄已清除！", "total": total})

if __name__ == '__main__':
    init_db()
    # 既然轉為雲端部署，這裡移除 Serveo 的本地執行，由服務商負責網路曝光
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, use_reloader=False, host='0.0.0.0', port=port)