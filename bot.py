import os
import time
from flask import Flask, Response, send_file

app = Flask(__name__)
LOG_FILE = "logs/casino_bot.log"

@app.route('/')
def index():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Логи казино-бота</title>
        <style>
            body {
                background: #1e1e1e;
                color: #d4d4d4;
                font-family: 'Consolas', monospace;
                padding: 20px;
            }
            .log-container {
                background: #2d2d2d;
                border-radius: 8px;
                padding: 15px;
                height: 80vh;
                overflow-y: auto;
                white-space: pre-wrap;
                word-wrap: break-word;
            }
            .log-line {
                border-bottom: 1px solid #3d3d3d;
                padding: 4px 0;
                font-size: 12px;
            }
            .info { color: #4ec9b0; }
            .warning { color: #dcdcaa; }
            .error { color: #f48771; }
            h1 {
                color: #569cd6;
                margin-top: 0;
            }
            .status {
                background: #3d3d3d;
                padding: 8px 15px;
                border-radius: 5px;
                margin-bottom: 15px;
            }
        </style>
    </head>
    <body>
        <h1>📊 Логи казино-бота (в реальном времени)</h1>
        <div class="status">
            🟢 Логи обновляются автоматически | Обновлено: <span id="timestamp"></span>
        </div>
        <div class="log-container" id="logs">
            Загрузка логов...
        </div>
        
        <script>
            function updateLogs() {
                fetch('/api/logs')
                    .then(response => response.text())
                    .then(data => {
                        const logsDiv = document.getElementById('logs');
                        logsDiv.innerHTML = data.split('\\n').map(line => {
                            let className = 'log-line';
                            if (line.includes('ERROR') || line.includes('❌')) className += ' error';
                            else if (line.includes('WARNING') || line.includes('⚠️')) className += ' warning';
                            else if (line.includes('INFO')) className += ' info';
                            return `<div class="${className}">${escapeHtml(line)}</div>`;
                        }).join('\\n');
                        logsDiv.scrollTop = logsDiv.scrollHeight;
                        document.getElementById('timestamp').textContent = new Date().toLocaleTimeString();
                    });
            }
            
            function escapeHtml(text) {
                const div = document.createElement('div');
                div.textContent = text;
                return div.innerHTML;
            }
            
            setInterval(updateLogs, 1000);
            updateLogs();
        </script>
    </body>
    </html>
    '''

@app.route('/api/logs')
def get_logs():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            # Возвращаем последние 500 строк
            lines = f.readlines()
            return '\n'.join(lines[-500:])
    return "Логи не найдены"

if __name__ == '__main__':
    print("🌐 Веб-сервер логов запущен на http://localhost:5000")
    print("📡 Откройте этот адрес в браузере для просмотра логов в реальном времени")
    app.run(host='0.0.0.0', port=5000, debug=False)
