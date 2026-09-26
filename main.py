# ============================================================
#   main.py - Entry point APK Android
#   Menjalankan Flask di background + menampilkan WebView
# ============================================================

import os
import sys
import time
import threading

# ============================================================
# 1. SETUP PATH & PERMISSION (harus SEBELUM import app.py)
# ============================================================
try:
    from kivy.utils import platform
except ImportError:
    platform = 'linux'

if platform == 'android':
    # Minta izin Android
    try:
        from android.permissions import request_permissions, Permission
        request_permissions([
            Permission.INTERNET,
            Permission.ACCESS_NETWORK_STATE,
            Permission.ACCESS_WIFI_STATE,
            Permission.READ_EXTERNAL_STORAGE,
            Permission.WRITE_EXTERNAL_STORAGE,
        ])
    except Exception as e:
        print(f"[main] permission error: {e}")

    # Pindah ke folder data aplikasi
    try:
        from android.storage import app_storage_path
        DATA_DIR = app_storage_path()
    except Exception:
        DATA_DIR = os.path.abspath('.')
else:
    DATA_DIR = os.path.abspath('.')

os.makedirs(DATA_DIR, exist_ok=True)
os.chdir(DATA_DIR)
print(f"[main] Working dir: {os.getcwd()}")

# ============================================================
# 2. IMPORT FLASK APP
# ============================================================
from app import app as flask_app
from app import init_db, pastikan_pool_ada, mulai_auto_backup, _log

FLASK_PORT = 5000

# ============================================================
# 3. JALANKAN FLASK DI THREAD
# ============================================================
def run_flask():
    try:
        _log("=" * 60)
        _log("MAIN: memulai Flask...")
        init_db()
        try:
            pastikan_pool_ada()
        except Exception as e:
            _log(f"[WARN] Pool gagal: {e}")
        mulai_auto_backup()
        _log(f"MAIN: Flask listen di 127.0.0.1:{FLASK_PORT}")
        flask_app.run(
            host='127.0.0.1',
            port=FLASK_PORT,
            debug=False,
            use_reloader=False,
            threaded=True,
        )
    except Exception as e:
        _log(f"[FATAL] Flask error: {e}")
        import traceback
        _log(traceback.format_exc())

# ============================================================
# 4. WEBVIEW ANDROID
# ============================================================
def buka_webview_android(url):
    from jnius import autoclass
    from android.runnable import run_on_ui_thread

    @run_on_ui_thread
    def _show():
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        WebView        = autoclass('android.webkit.WebView')
        WebViewClient  = autoclass('android.webkit.WebViewClient')
        ViewGroup      = autoclass('android.view.ViewGroup')
        LayoutParams   = autoclass('android.view.ViewGroup$LayoutParams')

        activity = PythonActivity.mActivity
        wv = WebView(activity)

        # Konfigurasi WebView
        settings = wv.getSettings()
        settings.setJavaScriptEnabled(True)
        settings.setDomStorageEnabled(True)
        settings.setAllowFileAccess(True)
        settings.setLoadWithOverviewMode(True)
        settings.setUseWideViewPort(True)
        settings.setBuiltInZoomControls(True)
        settings.setDisplayZoomControls(False)

        wv.setWebViewClient(WebViewClient())
        wv.loadUrl(url)

        params = LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT,
        )
        activity.addContentView(wv, params)

    _show()

# ============================================================
# 5. KIVY APP
# ============================================================
from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.core.window import Window

class SplashScreen(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation='vertical', padding=40, spacing=20, **kw)
        Window.clearcolor = (1, 1, 1, 1)

        self.add_widget(Label(
            text='[b]BDA CONNECTION[/b]',
            markup=True,
            font_size='28sp',
            color=(0.8, 0.0, 0.2, 1),
        ))
        self.add_widget(Label(
            text='Internet Service Provider',
            font_size='14sp',
            color=(0.4, 0.4, 0.4, 1),
        ))
        self.status = Label(
            text='Memuat aplikasi...',
            font_size='13sp',
            color=(0.5, 0.5, 0.5, 1),
        )
        self.add_widget(self.status)

class ISPApp(App):
    def build(self):
        self.title = 'BDA CONNECTION'
        return SplashScreen()

    def on_start(self):
        # Jalankan Flask di thread terpisah
        threading.Thread(target=run_flask, daemon=True).start()
        # Tunggu 4 detik lalu buka WebView
        Clock.schedule_once(self.buka_webview, 4)

    def buka_webview(self, *args):
        url = f'http://127.0.0.1:{FLASK_PORT}/'
        if platform == 'android':
            try:
                buka_webview_android(url)
            except Exception as e:
                self.root.status.text = f'Gagal buka UI: {e}'
        else:
            import webbrowser
            webbrowser.open(url)


if __name__ == '__main__':
    ISPApp().run()