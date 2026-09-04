# ui/theme.py — стили главного окна

WINDOW_QSS = """
    QMainWindow { background-color: #1e1e1e; }
    QTextBrowser { background-color: #2d2d2d; color: #f0f0f0; border: 1px solid #444; border-radius: 6px; }
    QLineEdit { background-color: #2d2d2d; color: #f0f0f0; border: 1px solid #444; padding: 8px; border-radius: 6px; }
    QPushButton { background-color: #3a3a3a; color: #f0f0f0; border: 1px solid #555; padding: 6px 10px; border-radius: 5px; }
    QPushButton:hover { background-color: #4a4a4a; }
    QPushButton:disabled { background-color: #2a2a2a; color: #777; }
"""

STATUS_STYLES = {
    "idle": ("#0f0", "готово"),
    "listening": ("#0af", "слушаю…"),
    "thinking": ("#ff0", "думаю…"),
    "searching": ("#fa0", "ищу…"),
    "speaking": ("#c6f", "говорю…"),
    "error": ("#f44", "ошибка"),
    "offline": ("#888", "офлайн"),
}
