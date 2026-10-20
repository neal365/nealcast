# -*- coding: utf-8 -*-
"""生成 README 用的宣传图（横幅）"""
import os, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import util as U

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs', 'banner.jpg')
FONT = r'C\:/Windows/Fonts/msyh.ttc'
vf = ("drawtext=fontfile='%s':text='免费投屏  NealCast':fontcolor=white:"
      "fontsize=110:x=(w-text_w)/2:y=(h-text_h)/2-70,"
      "drawtext=fontfile='%s':text='不装客户端 · 标准 DLNA · 开源免费':"
      "fontcolor=0x9FB2C8:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2+90" % (FONT, FONT))
subprocess.run([U.FFMPEG, '-y', '-v', 'error', '-f', 'lavfi',
                '-i', 'color=c=0x121722:s=1920x1080',
                '-vf', vf, '-frames:v', '1', '-q:v', '2', OUT], timeout=60)
print('banner:', os.path.exists(OUT), os.path.getsize(OUT) if os.path.exists(OUT) else 0)
