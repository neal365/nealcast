# -*- coding: utf-8 -*-
"""工具：定位 ffmpeg、选择本机与设备通信的网卡地址

ffmpeg 不随本仓库分发，请自行安装（winget install ffmpeg / brew install ffmpeg）。
查找顺序：脚本目录下的 ffmpeg.exe -> imageio_ffmpeg 自带的 -> PATH 里。
"""
import os
import sys
import socket


def _app_dir():
    """脚本/exe 所在目录（PyInstaller 打包后 __file__ 在临时目录，要用 sys.executable）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


_FFMPEG_CANDIDATES = [
    os.path.join(_app_dir(), 'ffmpeg.exe'),
]


def _find_ffmpeg():
    for p in _FFMPEG_CANDIDATES:
        if os.path.exists(p):
            return p
    try:
        import imageio_ffmpeg
        p = imageio_ffmpeg.get_ffmpeg_exe()
        if p and os.path.exists(p):
            return p
    except Exception:
        pass
    for d in os.environ.get('PATH', '').split(os.pathsep):
        p = os.path.join(d, 'ffmpeg.exe')
        if os.path.exists(p):
            return p
    return 'ffmpeg.exe'


FFMPEG = _find_ffmpeg()


def local_ip_for(dev_ip):
    """走 UDP connect 探测本机到目标设备用的是哪个地址（多网卡时很关键）"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((dev_ip, 80))
        return s.getsockname()[0]
    finally:
        s.close()
