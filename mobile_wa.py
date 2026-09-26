# ============================================================
#   mobile_wa.py - Helper WhatsApp untuk Android
#   Menggantikan pywhatkit yang tidak bisa jalan di HP
# ============================================================

from urllib.parse import quote

def kirim_wa_intent(nomor, pesan):
    """
    Buka aplikasi WhatsApp dengan nomor & pesan sudah terisi.
    User tinggal tekan tombol Send di WA.
    
    Di Android  -> pakai Intent (buka app WA langsung)
    Di PC       -> buka browser ke wa.me
    """
    # Bersihkan nomor: wa.me butuh format 628xxx tanpa '+'
    nomor_bersih = ''.join(c for c in str(nomor) if c.isdigit())
    if nomor_bersih.startswith('0'):
        nomor_bersih = '62' + nomor_bersih[1:]

    pesan_enc = quote(pesan)
    url = f"https://wa.me/{nomor_bersih}?text={pesan_enc}"

    # Coba deteksi platform
    try:
        from kivy.utils import platform as kivy_platform
        is_android = (kivy_platform == 'android')
    except Exception:
        is_android = False

    if is_android:
        try:
            from jnius import autoclass
            Intent = autoclass('android.content.Intent')
            Uri    = autoclass('android.net.Uri')
            PythonActivity = autoclass('org.kivy.android.PythonActivity')

            intent = Intent(Intent.ACTION_VIEW)
            intent.setData(Uri.parse(url))
            # Coba langsung ke WhatsApp
            intent.setPackage('com.whatsapp')
            try:
                PythonActivity.mActivity.startActivity(intent)
                return True
            except Exception:
                # Kalau WA tidak ada, coba WA Business
                try:
                    intent.setPackage('com.whatsapp.w4b')
                    PythonActivity.mActivity.startActivity(intent)
                    return True
                except Exception:
                    # Terakhir: buka via browser
                    intent.setPackage(None)
                    PythonActivity.mActivity.startActivity(intent)
                    return True
        except Exception as e:
            print(f"[mobile_wa] Gagal intent: {e}")
            return False
    else:
        # PC / desktop: buka browser
        import webbrowser
        webbrowser.open(url)
        return True