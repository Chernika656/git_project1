"""Открывает веб-версию и запускает локальный сервер, если он ещё не работает."""
from pathlib import Path
import subprocess
import sys
import time
from http.client import HTTPConnection, HTTPException
import json
import socket
import webbrowser

BASE = Path(__file__).resolve().parent
PORT = 8765
URL = f'http://127.0.0.1:{PORT}'


def running():
    # Локальная проверка не должна зависеть от системного HTTP-прокси.
    connection = HTTPConnection('127.0.0.1', PORT, timeout=3)
    try:
        connection.request('GET', '/api/health')
        response = connection.getresponse()
        return response.status == 200 and json.loads(response.read(4096)).get('app') == 'ProjectWorkspace'
    except (OSError, HTTPException, ValueError, AttributeError):
        return False
    finally:
        connection.close()


def port_in_use():
    try:
        with socket.create_connection(('127.0.0.1', PORT), timeout=1):
            return True
    except OSError:
        return False


if __name__ == '__main__':
    if not running():
        if port_in_use():
            for _ in range(5):
                time.sleep(.5)
                if running():
                    webbrowser.open(URL)
                    raise SystemExit(0)
            raise SystemExit('Порт 8765 занят, но Facet не отвечает. Если запускали web_app.py в PyCharm, остановите его кнопкой Stop и повторите запуск ярлыка.')
        with (BASE/'web-launcher.log').open('ab') as log:
            child = subprocess.Popen([sys.executable, str(BASE/'web_app.py'), '--port', str(PORT)], cwd=BASE,
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        for _ in range(40):
            if running():
                break
            if child.poll() is not None:
                raise SystemExit('Не удалось запустить сервер. См. web-launcher.log; порт 8765 может быть занят.')
            time.sleep(.1)
        else:
            raise SystemExit('Сервер не ответил. Подробности в web-launcher.log.')
    webbrowser.open(URL)
    print('Facet открыта:', URL)
