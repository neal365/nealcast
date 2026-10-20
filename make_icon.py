# -*- coding: utf-8 -*-
"""生成应用图标：横幅裁成方形 -> 包成 PNG-in-ICO（Vista+ 标准格式）"""
import os, struct, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import util as U

PNG = os.path.join(HERE, 'docs', '_icon.png')
ICO = os.path.join(HERE, 'nealcast.ico')

# 从深色底 + 文字改成纯图标：用横幅的中心区域做方形
subprocess.run([U.FFMPEG, '-y', '-v', 'error', '-f', 'lavfi',
                '-i', 'color=c=0x121722:s=256x256',
                '-vf', ("drawtext=fontfile='C\\:/Windows/Fonts/msyh.ttc':text='免':"
                        "fontcolor=white:fontsize=150:x=(w-text_w)/2:y=(h-text_h)/2-14"),
                '-frames:v', '1', PNG], timeout=60)

data = open(PNG, 'rb').read()
# ICONDIR(6) + ICONDIRENTRY(16) + PNG
entry = struct.pack('<BBBBHHII', 0, 0, 1, 0, 1, 32, len(data), 22)
open(ICO, 'wb').write(struct.pack('<HHH', 0, 1, 1) + entry + data)
print('icon:', ICO, os.path.getsize(ICO))
