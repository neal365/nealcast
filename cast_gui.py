# -*- coding: utf-8 -*-
"""免费投屏 NealCast —— 图形界面

选设备 -> 开始投屏 -> 结束投屏。不依赖任何厂商客户端，也不往设备里装东西。
"""
import os
import sys
import time
import queue
import threading
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import tkinter as tk
from tkinter import ttk

import discover
import gifcast
import dlna

BG = '#F5F6F8'
CARD = '#FFFFFF'
TEXT = '#1F2329'
MUTED = '#8A9099'
ACCENT = '#2B6CF6'
GREEN = '#2FA84F'
AMBER = '#E8A33D'
RED = '#E4574D'

# 全部按 16:9 出图：画布比例和投影/电视一致，才不会被拉变形
QUALITY = [(1920, 1080), (1280, 720), (960, 540)]
QUALITY_LABELS = ['原画（1920×1080）', '高清（1280×720）', '流畅（960×540）']


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.devices = []
        self.caster = None
        self.worker = None
        self.state = 'idle'

        root.title('免费投屏 NealCast')
        root.geometry('620x560')
        root.minsize(560, 520)
        root.configure(bg=BG)
        self._build()
        self.root.after(80, self._pump)
        self.refresh()

    # ---------------- UI
    def _build(self):
        wrap = tk.Frame(self.root, bg=BG)
        wrap.pack(fill='both', expand=True, padx=18, pady=16)

        head = tk.Frame(wrap, bg=BG)
        head.pack(fill='x')
        tk.Label(head, text='免费投屏', bg=BG, fg=TEXT,
                 font=('Microsoft YaHei UI', 17, 'bold')).pack(side='left')
        tk.Label(head, text='NealCast · 不装客户端，走设备自带 DLNA 能力', bg=BG, fg=MUTED,
                 font=('Microsoft YaHei UI', 9)).pack(side='left', padx=10, pady=(6, 0))

        # 状态卡
        card = tk.Frame(wrap, bg=CARD, highlightthickness=1,
                        highlightbackground='#E6E8EB')
        card.pack(fill='x', pady=(14, 12))
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill='x', padx=16, pady=14)

        self.dot = tk.Canvas(inner, width=14, height=14, bg=CARD,
                             highlightthickness=0)
        self.dot.pack(side='left', padx=(0, 10))
        self._dot = self.dot.create_oval(2, 2, 12, 12, fill=MUTED, outline='')

        self.lbl_state = tk.Label(inner, text='未投屏', bg=CARD, fg=TEXT,
                                  font=('Microsoft YaHei UI', 12, 'bold'))
        self.lbl_state.pack(side='left')
        self.lbl_detail = tk.Label(inner, text='', bg=CARD, fg=MUTED,
                                   font=('Microsoft YaHei UI', 9))
        self.lbl_detail.pack(side='right')

        # 设备列表
        devbox = tk.Frame(wrap, bg=CARD, highlightthickness=1,
                          highlightbackground='#E6E8EB')
        devbox.pack(fill='both', expand=True)
        bar = tk.Frame(devbox, bg=CARD)
        bar.pack(fill='x', padx=14, pady=(12, 6))
        tk.Label(bar, text='投屏到', bg=CARD, fg=TEXT,
                 font=('Microsoft YaHei UI', 10, 'bold')).pack(side='left')
        self.lbl_scan = tk.Label(bar, text='', bg=CARD, fg=MUTED,
                                 font=('Microsoft YaHei UI', 9))
        self.lbl_scan.pack(side='left', padx=8)

        self.lst = tk.Listbox(devbox, bg=CARD, fg=TEXT, bd=0, highlightthickness=0,
                              font=('Microsoft YaHei UI', 11), activestyle='none',
                              selectbackground='#E8F0FF', selectforeground=TEXT,
                              height=6)
        self.lst.pack(fill='both', expand=True, padx=8, pady=(0, 8))

        # 选项
        opt = tk.Frame(wrap, bg=BG)
        opt.pack(fill='x', pady=(10, 0))
        tk.Label(opt, text='清晰度', bg=BG, fg=MUTED,
                 font=('Microsoft YaHei UI', 9)).pack(side='left')
        self.cmb_q = ttk.Combobox(opt, state='readonly', width=16,
                                  values=QUALITY_LABELS,
                                  font=('Microsoft YaHei UI', 9))
        self.cmb_q.current(0)
        self.cmb_q.pack(side='left', padx=6)

        tk.Label(opt, text='   帧率', bg=BG, fg=MUTED,
                 font=('Microsoft YaHei UI', 9)).pack(side='left')
        self.cmb_f = ttk.Combobox(opt, state='readonly', width=8,
                                  values=['8', '10', '12'],
                                  font=('Microsoft YaHei UI', 9))
        self.cmb_f.current(1)
        self.cmb_f.pack(side='left', padx=6)

        # 按钮
        btns = tk.Frame(wrap, bg=BG)
        btns.pack(fill='x', pady=(14, 0))
        self.btn_refresh = self._btn(btns, '重新扫描', self.refresh, ghost=True)
        self.btn_refresh.pack(side='left')
        self.btn_stop = self._btn(btns, '结束投屏', self.stop, ghost=True)
        self.btn_stop.pack(side='left', padx=8)
        self.btn_start = self._btn(btns, '开始投屏', self.start)
        self.btn_start.pack(side='right')

        tk.Label(wrap, text='画面约 1~2 秒延迟，适合看文档、演示、代码；看视频不跟手',
                 bg=BG, fg=MUTED, font=('Microsoft YaHei UI', 8)).pack(anchor='w', pady=(8, 0))

        self._set_state('idle')

    def _btn(self, parent, text, cmd, ghost=False):
        b = tk.Button(parent, text=text, command=cmd, bd=0, relief='flat',
                      font=('Microsoft YaHei UI', 10, 'bold'),
                      padx=18, pady=8, cursor='hand2',
                      bg='#EDF0F4' if ghost else ACCENT,
                      fg=TEXT if ghost else '#FFFFFF',
                      activebackground='#E2E6EC' if ghost else '#1D5AE0',
                      activeforeground=TEXT if ghost else '#FFFFFF')
        return b

    def _set_state(self, s, text=None, detail=''):
        self.state = s
        color = {'idle': MUTED, 'scan': MUTED, 'connect': AMBER,
                 'casting': GREEN, 'error': RED}.get(s, MUTED)
        label = text or {'idle': '未投屏', 'scan': '查找设备中…',
                         'connect': '连接中…', 'casting': '投屏中',
                         'error': '出错了'}.get(s, '')
        self.dot.itemconfigure(self._dot, fill=color)
        self.lbl_state.config(text=label)
        self.lbl_detail.config(text=detail)
        idle = s in ('idle', 'error')
        self.btn_start.config(state='normal' if idle else 'disabled')
        self.btn_refresh.config(state='normal' if idle else 'disabled')
        self.btn_stop.config(state='normal' if s == 'casting' else 'disabled')

    # ---------------- 动作
    def refresh(self):
        if self.state in ('scan', 'connect', 'casting'):
            return
        self._set_state('scan')
        self.lbl_scan.config(text='正在扫描局域网…')
        self.lst.delete(0, 'end')

        def work():
            try:
                devs = discover.discover(progress=lambda m: self.q.put(('progress', m)))
                self.q.put(('devices', devs))
            except Exception as e:
                self.q.put(('scan_error', str(e)))

        threading.Thread(target=work, daemon=True).start()

    def start(self):
        if self.state in ('scan', 'connect', 'casting'):
            return
        sel = self.lst.curselection()
        if sel:
            dev = self.devices[sel[0]]
        else:
            cands = [d for d in self.devices if d.get('dlna')]
            if not cands:
                self._set_state('error', '没有可用设备', '请先开机并停在投屏/等待接收页')
                return
            dev = cands[0]
        if not dev.get('dlna'):
            self._set_state('error', '该设备不支持免费投屏',
                            '这台设备的 DLNA 渲染器不可用')
            return

        self._set_state('connect', '连接中…', dev.get('name', ''))
        qi = self.cmb_q.current()
        size = QUALITY[qi if 0 <= qi < len(QUALITY) else 0]
        fps = int(self.cmb_f.get())

        def work():
            try:
                self.caster = gifcast.GifCaster(
                    dev, secs=2.0, fps=fps, size=size,
                    on_status=lambda m: self.q.put(('status', m)))
                self.q.put(('casting', dev.get('name', '')))
                self.caster.run()
                self.q.put(('stopped', ''))
            except Exception:
                self.q.put(('cast_error', traceback.format_exc(limit=2)))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def stop(self):
        caster = self.caster
        if caster:
            caster.stop()
        self._set_state('idle', '正在结束…')
        dev = caster.dev if caster else None
        worker = self.worker
        self.caster = None

        def fin():
            # 先等推送线程真正退出，再通知设备停止，避免它又拉到一帧
            try:
                if worker and worker.is_alive():
                    worker.join(4)
            except Exception:
                pass
            if dev and dev.get('dlna'):
                try:
                    dlna.do_stop(dev['ip'], dev['dlna']['port'],
                                 dev['dlna'].get('control'))
                except Exception:
                    pass
            self.q.put(('stopped', ''))
        threading.Thread(target=fin, daemon=True).start()

    # ---------------- 消息泵
    def _pump(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == 'progress':
                    self.lbl_scan.config(text=payload)
                elif kind == 'devices':
                    self.devices = payload
                    self.lst.delete(0, 'end')
                    for d in payload:
                        tag = '可投屏' if d.get('dlna') else '无投屏通道'
                        self.lst.insert('end', '  %s    %s    [%s]'
                                        % (d.get('name', '?'), d['ip'], tag))
                    if payload:
                        first = next((i for i, d in enumerate(payload) if d.get('dlna')), 0)
                        self.lst.selection_set(first)
                        self._set_state('idle', '未投屏', '共 %d 台设备' % len(payload))
                    else:
                        self._set_state('idle', '未投屏', '')
                    self.lbl_scan.config(text='' if payload else
                                         '没找到设备，确认投影仪/电视已开机并联网')
                elif kind == 'scan_error':
                    self._set_state('error', '扫描失败', payload[:60])
                    self.lbl_scan.config(text='')
                elif kind == 'casting':
                    self._set_state('casting', '投屏中', payload)
                elif kind == 'status':
                    if self.state == 'connect':
                        self._set_state('casting', '投屏中')
                    self.lbl_detail.config(text=payload[:60])
                elif kind == 'stopped':
                    self._set_state('idle', '未投屏', '')
                elif kind == 'cast_error':
                    self._set_state('error', '投屏中断', payload.splitlines()[-1][:60])
        except queue.Empty:
            pass
        self.root.after(120, self._pump)


def main():
    autostart = '--autostart' in sys.argv
    root = tk.Tk()
    try:
        root.iconbitmap(default='')
    except Exception:
        pass
    app = App(root)
    if autostart:
        def _go():
            dev = None
            for _ in range(60):
                cands = [d for d in app.devices if d.get('dlna')]
                if cands:
                    dev = cands[0]
                    break
                time.sleep(0.25)
            if dev:
                for i, d in enumerate(app.devices):
                    if d is dev:
                        app.lst.selection_clear(0, 'end')
                        app.lst.selection_set(i)
                        break
                app.start()
        threading.Thread(target=_go, daemon=True).start()
    root.mainloop()


if __name__ == '__main__':
    main()
