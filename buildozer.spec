[app]
title = BDA CONNECTION
package.name = bdaconnection
package.domain = com.bdaconnection

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,ini,db,csv,html,css
source.exclude_dirs = backup,__pycache__,.buildozer,bin,dist,venv

version = 1.9

requirements = python3,kivy==2.2.1,flask,werkzeug,jinja2,itsdangerous,click,markupsafe,routeros_api,requests,urllib3,chardet,idna,certifi,pyjnius,android,plyer,openssl

orientation = portrait
fullscreen = 1

android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a, armeabi-v7a

android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE

android.allow_backup = True
android.presplash_color = #ffffff
android.apptheme = "@android:style/Theme.NoTitleBar"

[buildozer]
log_level = 2
warn_on_root = 1