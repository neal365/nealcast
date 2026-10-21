# -*- coding: utf-8 -*-
"""免费投屏 NealCast —— 图形界面

选设备 -> 开始投屏 -> 结束投屏。不依赖任何厂商客户端，也不往设备里装东西。
"""
import ctypes
import math
import os
import queue
import sys
import threading
import time
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)


def _enable_hidpi():
    """Windows 高 DPI：必须在任何窗口创建之前声明感知方式。

    不声明的话系统会按 96dpi 渲染窗口再整体位图拉伸到屏幕缩放比，
    字就是放大后的模糊像素。返回当前屏幕 DPI。
    """
    if sys.platform != 'win32':
        return 96
    try:
        # PER_MONITOR_AWARE_V2 —— Windows 10 1703+ / Win11 推荐
        ctypes.windll.shcore.SetProcessDpiAwarenessContext(-4)
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)   # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return dpi or 96
    except Exception:
        return 96


SC = max(1.0, _enable_hidpi() / 96.0)


def P(v):
    """把 96dpi 下的设计像素换算到真实像素，保证 175%/200% 屏幕上等大且清晰"""
    return int(round(v * SC))


import tkinter as tk                       # noqa: E402
import tkinter.messagebox as messagebox    # noqa: E402

import discover                            # noqa: E402
import gifcast                             # noqa: E402
import dlna                                # noqa: E402
import proxy                               # noqa: E402
import updater                             # noqa: E402

BG = '#F4F6FA'
CARD = '#FFFFFF'
LINE = '#E3E8EF'
TEXT = '#151A21'
SUB = '#5A6472'
MUTED = '#8B95A3'
ACCENT = '#2E6BE6'
ACCENT_D = '#2559C4'
ACCENT_L = '#E8F0FF'
SOFT = '#F5F7FB'
GREEN = '#12A150'
GREEN_L = '#F1FBF5'
GREEN_B = '#BCE6CE'
AMBER = '#D98A16'
AMBER_L = '#FFF8EC'
AMBER_B = '#F3DCAE'
RED = '#DC4B41'
RED_L = '#FDF4F3'
RED_B = '#F3CBC7'
DIS_BG = '#EDF0F4'
DIS_FG = '#A6ADB7'

QUALITY = [(1920, 1080), (1280, 720), (960, 540)]
QUALITY_LABELS = ['原画（1920×1080）', '高清（1280×720）', '流畅（960×540）']

FAMILY = 'Microsoft YaHei UI'


def F(size, bold=False):
    # Tk 里正数=磅（会再乘一次 tk scaling），负数=像素。统一按 96dpi 的磅折算成像素，
    # 这样字号在 100%/125%/175% 屏幕上都是等大且按物理像素直接渲染，不会发虚。
    return (FAMILY, -int(round(size * 96.0 / 72.0 * SC)),
            'bold' if bold else 'normal')


def _poly(c, box, r, **kw):
    """真圆角多边形（比 smooth=True 的多边形更规整）"""
    x1, y1, x2, y2 = box
    r = max(0.0, min(r, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    pts = []
    for cx, cy, a0 in ((x2 - r, y1 + r, -90), (x2 - r, y2 - r, 0),
                       (x1 + r, y2 - r, 90), (x1 + r, y1 + r, 180)):
        for i in range(19):
            a = math.radians(a0 + i * 5)
            pts += [cx + r * math.cos(a), cy + r * math.sin(a)]
    kw.setdefault('width', P(1))
    return c.create_polygon(pts, smooth=False, **kw)


class Card(tk.Canvas):
    """圆角白卡。外壳用 Canvas 画圆角，内容放在 inset 的内框里，四角不会露出直角"""

    def __init__(self, master, fill=CARD, outline=LINE, radius=14, pad=14,
                 height=None, bg=BG):
        self._fill, self._ol = fill, outline
        self._r, self._pad = P(radius), P(pad)
        tk.Canvas.__init__(self, master, bg=bg, bd=0, highlightthickness=0,
                           height=P(height) if height else P(20))
        self._auto = False
        self.content = tk.Frame(self, bg=fill)
        self._follow = [self.content]
        self.content.bind('<Configure>', self._on_content)
        self._win = self.create_window(self._pad, self._pad, anchor='nw',
                                       window=self.content)
        self.bind('<Configure>', self._paint)

    def fit(self):
        """按内容实际需要的高度收口，避免不同 DPI 下把内容裁掉"""
        self._auto = True
        self.update_idletasks()
        self.configure(height=self.content.winfo_reqheight() + 2 * self._pad)

    def _on_content(self, e=None):
        """内容变高（文字变长、换字体）时卡片自己长高，避免子控件溢出压到下一张卡"""
        if not self._auto:
            return
        need = self.content.winfo_reqheight() + 2 * self._pad
        if abs(need - self.winfo_height()) > P(2):
            self.configure(height=need)

    def follow(self, *widgets):
        self._follow.extend(widgets)

    def theme(self, fill=CARD, outline=LINE):
        self._fill, self._ol = fill, outline
        for w in self._follow:
            try:
                w.configure(bg=fill)
            except Exception:
                pass
        self._paint()

    def _paint(self, e=None):
        w, h = self.winfo_width(), self.winfo_height()
        self.delete('__bg')
        if w > 4 and h > 4:
            _poly(self, (1, 1, w - 1, h - 1), self._r, fill=self._fill,
                  outline=self._ol, tags='__bg')
            self.tag_lower('__bg')
        self.coords(self._win, self._pad, self._pad)
        need = self.content.winfo_reqheight()
        self.itemconfigure(self._win,
                           width=max(10, w - 2 * self._pad),
                           height=max(P(10), need, h - 2 * self._pad))


class Btn(tk.Canvas):
    """自绘按钮：正常 / 悬停 / 按下 / 禁用 四态，圆角"""

    def __init__(self, master, text, cmd, kind='primary', height=42, width=0):
        self._h, self._w = P(height), P(width)
        try:
            bg = master.cget('bg')
        except Exception:
            bg = BG
        tk.Canvas.__init__(self, master, bg=bg, bd=0, highlightthickness=0,
                           height=self._h, width=self._w or P(120))
        self.text, self.cmd, self.kind = text, cmd, kind
        self.enabled, self.hover, self.press = True, False, False
        self.bind('<Configure>', lambda e: self.draw())
        self.bind('<Enter>', self._enter)
        self.bind('<Leave>', self._leave)
        self.bind('<ButtonPress-1>', self._down)
        self.bind('<ButtonRelease-1>', self._up)

    def set_enabled(self, v):
        self.enabled = bool(v)
        self.cursor = 'hand2' if v else 'arrow'
        self.configure(cursor=self.cursor)
        self.draw()

    def set_kind(self, kind):
        self.kind = kind
        self.draw()

    def set_text(self, t):
        self.text = t
        self.draw()

    def _enter(self, e):
        self.hover = True
        self.draw()

    def _leave(self, e):
        self.hover, self.press = False, False
        self.draw()

    def _down(self, e):
        self.press = True
        self.draw()

    def _up(self, e):
        pressed = self.press
        self.press = False
        self.draw()
        if pressed and self.enabled and self.cmd:
            self.cmd()

    def draw(self):
        w = self.winfo_width() or self._w or P(120)
        h = self._h
        self.delete('all')
        if not self.enabled:
            fill, fg = DIS_BG, DIS_FG
        elif self.kind == 'primary':
            fill = ACCENT_D if (self.hover or self.press) else ACCENT
            fg = '#FFFFFF'
        elif self.kind == 'danger':
            fill = '#C33F36' if (self.hover or self.press) else RED
            fg = '#FFFFFF'
        else:                                   # ghost
            fill = '#E3E7EE' if self.hover else DIS_BG
            fg = TEXT
        _poly(self, (1, 1, w - 1, h - 1), P(10), fill=fill, outline=fill)
        self.create_text(w / 2.0, h / 2.0, text=self.text,
                         fill=fg, font=F(11, True))
        self.configure(cursor='hand2' if self.enabled else 'arrow')


class DevList(tk.Canvas):
    """自绘设备列表：两行文字 + 图标 + 圆角选中态 + 悬停态"""

    def __init__(self, master, on_select=None, on_activate=None):
        tk.Canvas.__init__(self, master, bg=CARD, bd=0, highlightthickness=0,
                           height=P(150))
        self.items, self.sel, self.hover = [], -1, -1
        self.hint = ''
        self.tip = ''
        self.row = P(58)
        self.on_select, self.on_activate = on_select, on_activate
        self.bind('<Configure>', lambda e: self.draw())
        self.bind('<Motion>', self._motion)
        self.bind('<Leave>', self._leave)
        self.bind('<ButtonPress-1>', self._press)
        self.bind('<Double-Button-1>', self._dbl)
        self.bind('<MouseWheel>', self._wheel)

    def fill(self, items, hint='', tip=None):
        self.hint = hint or ''
        self.tip = ('确认投影仪 / 电视已开机并连上同一个 Wi-Fi'
                    if tip is None else tip)
        self.items, self.sel, self.hover = items, -1, -1
        try:
            self.yview_moveto(0)
        except Exception:
            pass
        self.draw()

    def select_only_ok(self):
        for i, it in enumerate(self.items):
            if it.get('ok'):
                self.sel = i
                break
        self.draw()

    def _idx(self, ev):
        y = self.canvasy(ev.y)
        i = int(y // self.row)
        return i if 0 <= i < len(self.items) else -1

    def _motion(self, ev):
        i = self._idx(ev)
        if i != self.hover:
            self.hover = i
            self.draw()
            self.configure(cursor='hand2' if i >= 0 else '')

    def _leave(self, ev):
        if self.hover != -1:
            self.hover = -1
            self.draw()
        self.configure(cursor='')

    def _press(self, ev):
        i = self._idx(ev)
        if i >= 0 and i != self.sel:
            self.sel = i
            self.draw()
            if self.on_select:
                self.on_select(i)

    def _dbl(self, ev):
        if self._idx(ev) >= 0 and self.on_activate:
            self.on_activate()

    def _wheel(self, ev):
        top, bot = self.yview()
        if bot - top >= 0.999:
            return
        self.yview_scroll(-1 * int(ev.delta / 120), 'units')

    def draw(self):
        self.delete('all')
        w = self.winfo_width() or P(380)
        if not self.items:
            h = self.winfo_height() or P(150)
            self.create_text(w / 2.0, h * 0.44, text='还没发现设备',
                             fill=SUB, font=F(11, True))
            if self.tip:
                self.create_text(w / 2.0, h * 0.44 + P(26), text=self.tip,
                                 fill=MUTED, font=F(9))
            if self.hint:
                self.create_text(w / 2.0, h * 0.44 + P(58), text=self.hint,
                                 fill=RED, font=F(9), width=max(P(240), w - P(80)),
                                 justify='center')
            self.configure(scrollregion=(0, 0, w, self.winfo_height()))
            return

        x0, x1 = P(8), max(P(40), w - P(8))
        y = P(4)
        for i, it in enumerate(self.items):
            top, bot = y, y + self.row - P(6)
            ok = it.get('ok')
            state_bg = ACCENT_L if i == self.sel else (SOFT if i == self.hover else '')
            if state_bg:
                _poly(self, (x0, top, x1, bot), P(10), fill=state_bg, outline=state_bg)
            if i == self.sel:
                _poly(self, (x0, top + P(12), x0 + P(3), bot - P(12)), P(2),
                      fill=ACCENT, outline=ACCENT)
            s = P(34)
            iy = top + (self.row - P(6) - s) / 2.0
            _poly(self, (x0 + P(10), iy, x0 + P(10) + s, iy + s), P(9),
                  fill='#FFFFFF' if i == self.sel else '#EAEEF5', outline='')
            self.create_text(x0 + P(10) + s / 2.0, iy + s / 2.0,
                             text=(it.get('name', '?')[:1] or '?').upper(),
                             fill=ACCENT if ok else MUTED, font=F(12, True))
            tx = x0 + P(54)
            self.create_text(tx, top + P(13), anchor='nw', text=it.get('name', '?'),
                             fill=TEXT if ok else MUTED, font=F(11, True))
            self.create_text(tx, bot - P(21), anchor='nw', text=it.get('sub', ''),
                             fill=MUTED, font=F(9))
            self.create_text(x1 - P(12), (top + bot) / 2.0, anchor='e',
                             text=it.get('tag', ''),
                             fill=GREEN if ok else RED, font=F(9, True))
            y += self.row
        self.configure(scrollregion=(0, 0, w, y + P(4)))


class Select(tk.Canvas):
    """自绘下拉选择。ttk.Combobox 在高 DPI 下会把文字裁掉，也难统一配色"""

    def __init__(self, master, values, index=0, on_change=None, height=34):
        self._h = P(height)
        try:
            bg = master.cget('bg')
        except Exception:
            bg = CARD
        tk.Canvas.__init__(self, master, bg=bg, bd=0, highlightthickness=0,
                           height=self._h)
        self.values, self.index = list(values), index
        self.on_change, self.hover = on_change, False
        self.bind('<Configure>', lambda e: self.draw())
        self.bind('<Enter>', lambda e: (setattr(self, 'hover', True), self.draw()))
        self.bind('<Leave>', lambda e: (setattr(self, 'hover', False), self.draw()))
        self.bind('<Button-1>', self._popup)

    def get(self):
        return self.values[self.index] if self.values else ''

    def current(self):
        return self.index

    def _popup(self, e=None):
        m = tk.Menu(self, tearoff=0, font=F(10), bg=CARD, fg=TEXT,
                    activebackground=ACCENT_L, activeforeground=TEXT,
                    bd=0, activeborderwidth=0, relief='flat',
                    selectcolor=ACCENT)
        for i, v in enumerate(self.values):
            m.add_command(label=('✓  ' if i == self.index else '    ') + v,
                          command=lambda i=i: self._pick(i))
        try:
            m.tk_popup(self.winfo_rootx(),
                       self.winfo_rooty() + self._h + P(3))
        finally:
            m.grab_release()

    def _pick(self, i):
        self.index = i
        self.draw()
        if self.on_change:
            self.on_change(i)

    def draw(self):
        w = self.winfo_width() or P(200)
        h = self._h
        self.delete('all')
        fill = '#F2F5FA' if self.hover else '#F7F9FC'
        _poly(self, (1, 1, w - 1, h - 1), P(9), fill=fill, outline=LINE)
        self.create_text(P(11), h / 2.0, anchor='w', text=self.get(),
                         fill=TEXT, font=F(10))
        ax, ay = w - P(16), h / 2.0
        self.create_line(ax - P(4), ay - P(2), ax, ay + P(3), ax + P(4), ay - P(2),
                         fill=SUB, width=max(1, P(1)), capstyle='round',
                         joinstyle='round')
        self.configure(cursor='hand2')


class UpdateDialog(tk.Toplevel):
    """升级弹窗：新旧版本 + 更新日志 + 下载进度"""

    def __init__(self, master, info, notes_text, on_start, on_close, busy=''):
        tk.Toplevel.__init__(self, master)
        self.transient(master)
        self.title('发现新版本')
        self.configure(bg=BG)
        try:
            self.iconbitmap(os.path.join(BASE, 'nealcast.ico'))
        except Exception:
            pass
        self.resizable(False, False)
        self.info, self.on_start, self.on_close = info, on_start, on_close
        self.protocol('WM_DELETE_WINDOW', self._cancel)
        self._done = False

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill='both', expand=True, padx=P(18), pady=P(16))
        tk.Label(wrap, text='发现新版本 %s' % info['version'], bg=BG, fg=TEXT,
                 font=F(14, True), anchor='w').pack(anchor='w')
        tk.Label(wrap, text='当前 v%s · 更新过程约半分钟%s'
                            % (updater.APP_VERSION, busy),
                 bg=BG, fg=MUTED, font=F(9), anchor='w').pack(anchor='w', pady=(P(4), 0))

        body = Card(wrap, pad=12)
        body.pack(fill='x', pady=(P(12), 0))
        txt = (notes_text or '').strip() or '本次更新的具体说明见项目 README 的「更新日志」。'
        tk.Label(body.content, text=txt, bg=CARD, fg=SUB, font=F(9), anchor='w',
                 justify='left', wraplength=P(390)).pack(anchor='w')
        body.fit()

        self.bar = tk.Canvas(wrap, bg=BG, highlightthickness=0, height=P(8))
        self.lbl_prog = tk.Label(wrap, text='', bg=BG, fg=ACCENT, font=F(9), anchor='w')

        btns = tk.Frame(wrap, bg=BG)
        btns.pack(fill='x', pady=(P(14), 0))
        self.btn_later = Btn(btns, '以后再说', self._cancel, kind='ghost',
                             height=38, width=P(120))
        self.btn_later.pack(side='left')
        self.btn_go = Btn(btns, '立即更新', self._go, kind='primary', height=38)
        self.btn_go.pack(side='left', fill='x', expand=True, padx=(P(10), 0))

        self.update_idletasks()
        self._center(master)

    def _center(self, master):
        try:
            self.update_idletasks()
            w, h = self.winfo_width(), self.winfo_height()
            mx, my = master.winfo_rootx(), master.winfo_rooty()
            mw, mh = master.winfo_width(), master.winfo_height()
            self.geometry('+%d+%d' % (mx + (mw - w) // 2, my + (mh - h) // 2))
        except Exception:
            pass

    def _go(self):
        if self.on_start:
            self.on_start()

    def _cancel(self):
        if self._done:
            return                      # 已经进入安装阶段，别让用户关掉
        if self.on_close:
            self.on_close()
        try:
            self.destroy()
        except Exception:
            pass

    def started(self):
        self.btn_go.set_enabled(False)
        self.btn_later.set_enabled(False)
        self.btn_go.set_text('下载中')
        self.bar.pack(fill='x', pady=(P(12), 0), before=self.btn_later.master)
        self.lbl_prog.pack(fill='x', pady=(P(5), 0), before=self.btn_later.master)
        self.lbl_prog.configure(text='正在连接…', fg=ACCENT)

    def progress(self, got, total):
        w = self.bar.winfo_width() or P(390)
        h = P(8)
        self.bar.delete('all')
        _poly(self.bar, (0, 0, w, h), h / 2.0, fill=LINE, outline=LINE)
        if total:
            r = max(0.0, min(1.0, got / float(total)))
            _poly(self.bar, (0, 0, max(2, int(w * r)), h), h / 2.0,
                  fill=ACCENT, outline=ACCENT)
            self.lbl_prog.configure(text='正在下载… %.1f / %.1f MB'
                                         % (got / 1048576.0, total / 1048576.0))
        else:
            self.lbl_prog.configure(text='正在下载… %.1f MB' % (got / 1048576.0))

    def done(self, path, manual_install=False):
        self._done = True
        self.btn_later.set_enabled(False)
        self.btn_go.set_enabled(False)
        if manual_install:
            self.lbl_prog.configure(text='已下载到 %s，双击安装即可' % path, fg=GREEN)
            self.btn_go.set_text('打开文件夹')
            self.btn_go.cmd = lambda: self._open_dir(path)
            self.btn_go.set_enabled(True)
            self.btn_later.set_text('关闭')
            self.btn_later.cmd = self._cancel
            self.btn_later.set_enabled(True)
        else:
            self.lbl_prog.configure(text='下载完成，正在安装并重启…', fg=GREEN)
            self.btn_go.set_text('安装中')

    def _open_dir(self, path):
        try:
            os.startfile(os.path.dirname(path))
        except Exception:
            pass

    def fail(self, msg):
        self.lbl_prog.configure(text='更新失败：%s' % msg[:60], fg=RED)
        self.btn_go.set_text('重试')
        self.btn_go.set_enabled(True)
        self.btn_later.set_enabled(True)


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.devices = []
        self.caster = None
        self.worker = None
        self.state = 'idle'
        self.proxy_apps = None
        self.pending_update = None
        self.upd_dlg = None
        self._checking = False

        root.title('免费投屏 NealCast')
        root.configure(bg=BG)
        root.geometry('%dx%d' % (P(660), P(628)))
        root.minsize(P(578), P(618))
        self._build()
        self.root.after(90, self._pump)
        self.root.after(2500, lambda: self.check_update(False))
        self.refresh()

    # ---------------- UI
    def _build(self):
        wrap = tk.Frame(self.root, bg=BG)
        wrap.pack(fill='both', expand=True, padx=P(16), pady=P(14))

        # ---- 头部
        head = Card(wrap, pad=16)
        head.pack(fill='x')
        hc = head.content
        logo = tk.Canvas(hc, bg=CARD, highlightthickness=0, bd=0,
                         width=P(46), height=P(46))
        logo.pack(side='left', padx=(0, P(12)))
        self._logo(logo, P(46))
        texts = tk.Frame(hc, bg=CARD)
        texts.pack(side='left', fill='y', pady=P(6))
        tk.Label(texts, text='免费投屏', bg=CARD, fg=TEXT, font=F(17, True),
                 anchor='w').pack(anchor='w')
        tk.Label(texts, text='NealCast · 不装客户端 · 走设备自带 DLNA',
                 bg=CARD, fg=MUTED, font=F(9), anchor='w').pack(anchor='w', pady=(P(3), 0))
        self.lbl_ver = tk.Label(hc, text='v' + updater.APP_VERSION, bg=CARD,
                                fg=MUTED, font=F(9))
        self.lbl_ver.pack(side='right', anchor='ne')
        head.follow(logo, texts, self.lbl_ver)

        # ---- 状态
        st = Card(wrap, pad=15)
        st.pack(fill='x', pady=(P(10), 0))
        self.card_state = st
        sc = st.content
        self.dot = tk.Canvas(sc, bg=CARD, highlightthickness=0, bd=0,
                             width=P(12), height=P(12))
        self.dot.pack(side='left', padx=(0, P(9)))
        self._dotid = self.dot.create_oval(1, 1, P(12) - 1, P(12) - 1,
                                           fill=MUTED, outline='')
        self.lbl_state = tk.Label(sc, text='未投屏', bg=CARD, fg=TEXT, font=F(13, True))
        self.lbl_state.pack(side='left')
        self.lbl_detail = tk.Label(sc, text='', bg=CARD, fg=SUB, font=F(9))
        self.lbl_detail.pack(side='right')
        st.follow(self.dot, self.lbl_state, self.lbl_detail)

        # ---- 设备
        dev = Card(wrap, pad=12)
        dev.pack(fill='both', expand=True, pady=(P(10), 0))
        dc = dev.content
        top = tk.Frame(dc, bg=CARD)
        top.pack(fill='x', padx=P(4), pady=(0, P(8)))
        tk.Label(top, text='投屏到', bg=CARD, fg=TEXT, font=F(11, True)).pack(side='left')
        self.lbl_scan = tk.Label(top, text='', bg=CARD, fg=MUTED, font=F(9))
        self.lbl_scan.pack(side='left', padx=P(8), pady=(P(2), 0))
        self.btn_refresh_c = Btn(top, '重新扫描', self.refresh, kind='ghost',
                                 height=28, width=P(92))
        self.btn_refresh_c.pack(side='right')
        self.lst = DevList(dc, on_select=lambda i: None,
                           on_activate=lambda: self.state == 'idle' and self.start())
        self.lst.pack(fill='both', expand=True)
        dev.follow(top, self.lbl_scan)

        # ---- 代理/VPN 提示条（只在扫描疑似被 TUN 接管时出现，平时不占位）
        self.card_proxy = Card(wrap, fill=AMBER_L, outline=AMBER_B, pad=12)
        pc = self.card_proxy.content
        ptxt = tk.Frame(pc, bg=AMBER_L)
        ptxt.pack(side='left', fill='x', expand=True, padx=(P(2), P(10)))
        self.lbl_proxy = tk.Label(ptxt, text='', bg=AMBER_L, fg='#8A5A08',
                                  font=F(10, True), anchor='w', justify='left')
        self.lbl_proxy.pack(anchor='w', fill='x')
        self.lbl_proxy2 = tk.Label(ptxt, text='', bg=AMBER_L, fg='#A97A2E',
                                   font=F(9), anchor='w', justify='left')
        self.lbl_proxy2.pack(anchor='w', fill='x', pady=(P(3), 0))
        self.btn_proxy = Btn(pc, '关闭并重试', self._close_proxy,
                             kind='primary', height=36, width=P(122))
        self.btn_proxy.configure(bg=AMBER_L)
        self.btn_proxy.pack(side='right')
        self.card_proxy.follow(ptxt, self.lbl_proxy, self.lbl_proxy2, self.btn_proxy)

        # ---- 选项
        opt = Card(wrap, pad=14)
        opt.pack(fill='x', pady=(P(10), 0))
        self.card_opt = opt
        oc = opt.content
        oc.columnconfigure(0, weight=2, uniform='c')
        oc.columnconfigure(1, weight=1, uniform='c')
        col1 = tk.Frame(oc, bg=CARD)
        col1.grid(row=0, column=0, sticky='ew')
        tk.Label(col1, text='清晰度', bg=CARD, fg=SUB, font=F(9)).pack(anchor='w')
        self.cmb_q = Select(col1, QUALITY_LABELS, 0, height=34)
        self.cmb_q.pack(fill='x', pady=(P(5), 0))
        col2 = tk.Frame(oc, bg=CARD)
        col2.grid(row=0, column=1, sticky='ew', padx=(P(14), 0))
        tk.Label(col2, text='帧率', bg=CARD, fg=SUB, font=F(9)).pack(anchor='w')
        self.cmb_f = Select(col2, ['8', '10', '12'], 1, height=34)
        self.cmb_f.pack(fill='x', pady=(P(5), 0))

        # ---- 按钮
        btns = tk.Frame(wrap, bg=BG)
        btns.pack(fill='x', pady=(P(12), 0))
        self.btn_stop = Btn(btns, '结束投屏', self.stop, kind='ghost', width=132)
        self.btn_stop.pack(side='left')
        self.btn_start = Btn(btns, '开始投屏', self.start, kind='primary')
        self.btn_start.pack(side='left', fill='x', expand=True, padx=(P(10), 0))

        foot = tk.Frame(wrap, bg=BG)
        foot.pack(fill='x', pady=(P(8), 0))
        tk.Label(foot, text='画面约 1~2 秒延迟，适合文档 / 演示 / 代码；看视频不跟手',
                 bg=BG, fg=MUTED, font=F(8), anchor='w',
                 justify='left').pack(side='left')
        self.lbl_update = tk.Label(foot, text='检查更新', bg=BG, fg=ACCENT,
                                   font=F(8), cursor='hand2')
        self.lbl_update.pack(side='right')
        self.lbl_update.bind('<Button-1>', lambda e: self.check_update(True))

        for c in (head, st, opt):
            c.fit()
        self._set_state('idle')

    def _logo(self, c, size):
        u = size / 46.0
        _poly(c, (0, 0, size, size), 11 * u, fill=ACCENT, outline=ACCENT)
        # 屏幕
        _poly(c, (10 * u, 11 * u, 30 * u, 25 * u), 3 * u, fill='#FFFFFF', outline='#FFFFFF')
        # 播放三角
        c.create_polygon([20 * u, 15 * u, 20 * u, 21.5 * u, 25.5 * u, 18.25 * u],
                         fill=ACCENT, outline='')
        # 投屏波纹
        for i, x in enumerate((32 * u, 36 * u, 40 * u)):
            c.create_arc(x, 26 * u, x + 8 * u, 40 * u, start=-52, extent=104,
                         style='arc', outline='#FFFFFF',
                         width=max(1, round((1.8 - i * 0.35) * u * SC)))

    def _set_state(self, s, text=None, detail=''):
        self.state = s
        theme = {'idle': (MUTED, CARD, LINE),
                 'scan': (ACCENT, CARD, LINE),
                 'connect': (AMBER, AMBER_L, AMBER_B),
                 'casting': (GREEN, GREEN_L, GREEN_B),
                 'error': (RED, RED_L, RED_B)}.get(s, (MUTED, CARD, LINE))
        color, card_fill, line = theme
        label = text or {'idle': '未投屏', 'scan': '查找设备中…', 'connect': '连接中…',
                         'casting': '投屏中', 'error': '出错了'}.get(s, '')
        self.dot.itemconfigure(self._dotid, fill=color, outline='')
        self.lbl_state.configure(text=label, fg=color if s in ('casting', 'error', 'connect') else TEXT)
        self.lbl_detail.configure(text=detail)
        self.card_state.theme(card_fill, line)
        for w in (self.dot, self.lbl_state, self.lbl_detail):
            try:
                w.configure(bg=card_fill)
            except Exception:
                pass

        idle = s in ('idle', 'error')
        self.btn_stop.set_kind('primary' if s == 'casting' else 'ghost')
        self.btn_start.set_enabled(idle)
        self.btn_refresh_c.set_enabled(idle and s != 'scan')
        self.btn_stop.set_enabled(s == 'casting')
        self.btn_start.set_text('投屏中' if s == 'casting' else '开始投屏')

    # ---------------- 动作
    def refresh(self, keep_proxy=False):
        if self.state in ('scan', 'connect', 'casting'):
            return
        if not keep_proxy:
            self._hide_proxy_bar()
        self._set_state('scan')
        self.lbl_scan.configure(text='正在扫描局域网…')
        self.lst.fill([], tip='')

        def work():
            try:
                devs = discover.discover(progress=lambda m: self.q.put(('progress', m)))
                self.q.put(('devices', devs))
            except Exception as e:
                self.q.put(('scan_error', str(e)))

        threading.Thread(target=work, daemon=True).start()

    # ---------------- 在线升级
    def check_update(self, manual=True):
        if getattr(self, '_checking', False):
            return
        self._checking = True
        self.lbl_update.configure(text='检查中…', fg=MUTED, cursor='')

        def work():
            info, ns = None, ''
            try:
                info = updater.latest()
                if updater.has_update(info):
                    ns = updater.notes()
            except Exception:
                info = None
            self.q.put(('update', (info, ns, manual)))

        threading.Thread(target=work, daemon=True).start()

    def _open_update(self, info, ns):
        if getattr(self, 'upd_dlg', None):
            try:
                self.upd_dlg.lift()
                return
            except Exception:
                self.upd_dlg = None
        busy = '，会先结束当前投屏' if self.state == 'casting' else ''
        self.upd_dlg = UpdateDialog(self.root, info, ns, self._do_update,
                                    self._close_upd, busy=busy)

    def _close_upd(self):
        self.upd_dlg = None

    def _do_update(self):
        info = self.pending_update
        if not info or not self.upd_dlg:
            return
        self.upd_dlg.started()
        if self.state == 'casting':
            self.stop()

        def work():
            try:
                path = updater.download(
                    info,
                    progress=lambda g, t: self.q.put(('uprog', (g, t))))
                self.q.put(('udone', path))
            except Exception as e:
                self.q.put(('ufail', str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _install_update(self, path):
        # 源码运行时不擅自把用户装成 exe，只把安装包交到手上
        if not getattr(sys, 'frozen', False):
            if self.upd_dlg:
                self.upd_dlg.done(path, manual_install=True)
            return
        if self.upd_dlg:
            self.upd_dlg.done(path)
        try:
            updater.install_and_restart(path, app=sys.executable)
        except Exception:
            pass
        self.root.after(400, lambda: updater.quit_self(self.root))

    # ---------------- 代理 / VPN 一键关闭
    def _show_proxy_bar(self):
        """扫描结果疑似被 TUN 接管时，在设备列表下方给出一键关闭入口"""
        self.proxy_apps = None
        self.lbl_proxy.configure(text='代理 / VPN 正在接管局域网')
        self.lbl_proxy2.configure(text='正在识别是哪个软件…')
        self.btn_proxy.set_enabled(False)
        self.btn_proxy.set_text('识别中…')
        self.card_proxy.pack(fill='x', pady=(P(10), 0), before=self.card_opt)
        self.card_proxy.fit()
        self._reserve_proxy(True)

        def work():
            try:
                apps = proxy.running()
            except Exception:
                apps = {'closable': [], 'manual': []}
            self.q.put(('proxy_apps', apps))

        threading.Thread(target=work, daemon=True).start()

    def _hide_proxy_bar(self):
        was = bool(self.card_proxy.winfo_manager())
        try:
            self.card_proxy.pack_forget()
        except Exception:
            pass
        if was:
            self._reserve_proxy(False)

    def _reserve_proxy(self, on):
        """提示条出现时把窗口撑高，收起来时还回去，别把底部按钮挤扁"""
        if getattr(self, '_proxy_reserved', False) == on:
            return
        self._proxy_reserved = on
        try:
            self.root.update_idletasks()
            w = self.root.winfo_width()
            h = self.root.winfo_height() + (P(80) if on else -P(80))
            self.root.geometry('%dx%d' % (w, h))
        except Exception:
            pass

    def _close_proxy(self):
        apps = self.proxy_apps or {'closable': [], 'manual': []}
        if not apps.get('closable'):          # 只认得组网类软件，不敢自动关
            self._hide_proxy_bar()
            self.refresh()
            return
        nm = proxy.names(apps)
        self.btn_proxy.set_enabled(False)
        self.btn_proxy.set_text('正在关闭…')
        self.lbl_proxy.configure(text='正在关闭 %s…' % nm)
        self.lbl_proxy2.configure(text='等几秒让虚拟网卡撤销，随后自动重新扫描')

        def work():
            try:
                ok, fail = proxy.kill(apps)
            except Exception:
                ok, fail = 0, ['?']
            time.sleep(2.5)                    # 等路由表恢复，别立刻扫
            self.q.put(('proxy_closed', (ok, fail)))

        threading.Thread(target=work, daemon=True).start()

    def _selected_dev(self):
        i = self.lst.sel
        if 0 <= i < len(self.lst.items):
            dev = self.lst.items[i]['dev']
        else:
            dev = next((it['dev'] for it in self.lst.items if it.get('ok')), None)
        return dev

    def start(self):
        if self.state in ('scan', 'connect', 'casting'):
            return
        dev = self._selected_dev()
        if dev is None:
            self._set_state('error', '没有可用设备', '请先开机并停在投屏 / 等待接收页')
            return
        if not dev.get('dlna'):
            self._set_state('error', '该设备暂不支持', '这台设备没有可用的 DLNA 渲染器')
            return

        self._set_state('connect', '连接中…', dev.get('name', ''))
        qi = self.cmb_q.current()
        size = QUALITY[qi if 0 <= qi < len(QUALITY) else 0]
        try:
            fps = int(self.cmb_f.get())
        except Exception:
            fps = 10

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
        dev = caster.dev if caster else None
        worker = self.worker
        self.caster = None
        self._set_state('idle', '正在结束…')

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
            for _ in range(60):
                kind, payload = self.q.get_nowait()
                if kind == 'progress':
                    self.lbl_scan.configure(text=payload)
                elif kind == 'devices':
                    self.devices = payload
                    rows = []
                    for d in payload:
                        ok = bool(d.get('dlna'))
                        rows.append({
                            'name': d.get('name', '未知设备'),
                            'sub': '%s · %s' % (d['ip'], 'DLNA 渲染器' if ok else '未开放 DLNA'),
                            'tag': '可投屏' if ok else '不可用',
                            'ok': ok,
                            'dev': d,
                        })
                    rows.sort(key=lambda r: (not r['ok'], r['name']))
                    hijack = bool(getattr(discover, 'last_hijack', False)) and not rows
                    self.lst.fill(rows, hint='' if hijack else discover.last_note,
                                  tip='' if hijack else None)
                    self.lst.select_only_ok()
                    if hijack:
                        self._show_proxy_bar()
                    else:
                        self._hide_proxy_bar()
                    if payload:
                        self._set_state('idle', '未投屏', '共 %d 台设备' % len(payload))
                        self.lbl_scan.configure(text='')
                    else:
                        self._set_state('idle', '未投屏', '')
                        self.lbl_scan.configure(text='')
                elif kind == 'proxy_apps':
                    self.proxy_apps = payload
                    n = proxy.names(payload)
                    closable = bool(payload.get('closable'))
                    if closable:
                        self.lbl_proxy.configure(text='%s 正在接管局域网' % n)
                        self.lbl_proxy2.configure(
                            text='扫描结果全是假的，关掉它才会找到投影仪')
                        self.btn_proxy.set_text('关闭 %s' % n)
                    elif n:
                        self.lbl_proxy.configure(text='%s 正在接管局域网' % n)
                        self.lbl_proxy2.configure(
                            text='它是组网工具，关掉可能断开远程办公，请自行判断后手动退出')
                        self.btn_proxy.set_text('重新扫描')
                    else:
                        self.lbl_proxy.configure(text='局域网疑似被代理 / VPN 接管')
                        self.lbl_proxy2.configure(
                            text='没认出是哪个软件，请手动退出代理后点重新扫描')
                        self.btn_proxy.set_text('重新扫描')
                    self.btn_proxy.set_enabled(True)
                    self.card_proxy.fit()
                elif kind == 'proxy_closed':
                    _ok, fail = payload
                    if fail:
                        self.proxy_apps = None      # 自动关闭失败，改由用户手动处理
                        self.lbl_proxy.configure(text='自动关闭失败')
                        self.lbl_proxy2.configure(
                            text='请手动退出 %s 后重新扫描' % '、'.join(fail[:2]))
                        self.btn_proxy.set_text('重新扫描')
                        self.btn_proxy.set_enabled(True)
                        self.card_proxy.fit()
                    else:
                        self._hide_proxy_bar()
                        self.refresh(keep_proxy=True)
                elif kind == 'update':
                    self._checking = False
                    info, ns, manual = payload
                    self.pending_update = info
                    if info is None:
                        self.lbl_update.configure(
                            text='检查更新失败', fg=RED, cursor='arrow')
                        if manual:
                            messagebox.showinfo(
                                '免费投屏', '没连上更新服务器，稍后再试')
                    elif updater.has_update(info):
                        self.lbl_update.configure(
                            text='有新版本 %s · 点此更新' % info['version'],
                            fg=GREEN, cursor='hand2')
                        if manual or self.state == 'idle':
                            self._open_update(info, ns)
                    else:
                        self.lbl_update.configure(text='已是最新版', fg=MUTED,
                                                  cursor='')
                        if manual:
                            messagebox.showinfo('免费投屏', '当前已经是最新版本')
                elif kind == 'uprog':
                    if self.upd_dlg:
                        try:
                            self.upd_dlg.progress(*payload)
                        except Exception:
                            pass
                elif kind == 'udone':
                    self._install_update(payload)
                elif kind == 'ufail':
                    if self.upd_dlg:
                        self.upd_dlg.fail(payload)
                elif kind == 'scan_error':
                    self._set_state('error', '扫描失败', payload[:48])
                    self.lbl_scan.configure(text='')
                elif kind == 'casting':
                    self._set_state('casting', '投屏中', payload)
                elif kind == 'status':
                    if self.state == 'connect':
                        self._set_state('casting', '投屏中')
                    self.lbl_detail.configure(text=payload[:48])
                elif kind == 'stopped':
                    self._set_state('idle', '未投屏', '')
                elif kind == 'cast_error':
                    last = payload.strip().splitlines()[-1] if payload.strip() else ''
                    self._set_state('error', '投屏中断', last[:48])
        except queue.Empty:
            pass
        self.root.after(120, self._pump)


def main():
    autostart = '--autostart' in sys.argv
    root = tk.Tk()
    try:
        ico = os.path.join(BASE, 'nealcast.ico')
        if os.path.exists(ico):
            root.iconbitmap(ico)
    except Exception:
        pass
    app = App(root)
    root.update_idletasks()
    w, h = P(660), P(628)
    x = max(0, (root.winfo_screenwidth() - w) // 2)
    y = max(0, (root.winfo_screenheight() - h) // 3)
    root.geometry('%dx%d+%d+%d' % (w, h, x, y))

    if autostart:
        def _go():
            for _ in range(80):
                if app.lst.items and app.state == 'idle':
                    break
                time.sleep(0.25)
            if app.state == 'idle':
                app.root.after(0, app.start)
        threading.Thread(target=_go, daemon=True).start()
    root.mainloop()


if __name__ == '__main__':
    main()
