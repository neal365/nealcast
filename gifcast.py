# -*- coding: utf-8 -*-
"""免费投屏 NealCast 引擎：动画 GIF 分段投屏

为什么用 GIF：
  绝大多数 DLNA 渲染器只对 image/* 真正回源，视频流(mp4/ts/HLS)会被假接受。
  而动画 GIF 能让「一次加载、多帧播放」，把设备每帧重建会话的开销摊薄，
  帧率从 2fps 提升到 8~10fps，且不再每帧黑一下。

工作方式：
  ffmpeg 抓一小段屏幕 -> 生成循环 GIF（一张图里播多帧）-> 推给设备；
  设备播放这一段的 1~2 秒里，我们同时在生产下一段，无缝接力。
  画面静止时不推新段，设备循环旧段，零闪烁。
"""
import os
import sys
import time
import threading
import subprocess
import http.server
import socketserver
import tempfile
import queue

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import util as U
import dlna as L

HTTP_PORT = 8899


class GifServer:
    """把最新一段 GIF 交给设备来拉；端口固定 8899"""

    def __init__(self, port=HTTP_PORT):
        self.data = b''
        self.lock = threading.Lock()
        self.hits = 0
        self.last_hit = 0.0
        s = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.0'

            def log_message(self, *a):
                pass

            def do_GET(self):
                with s.lock:
                    d = s.data
                    s.hits += 1
                    s.last_hit = time.time()
                if not d:
                    self.send_error(404)
                    return
                try:
                    self.send_response(200)
                    self.send_header('Content-Type', 'image/gif')
                    self.send_header('Content-Length', str(len(d)))
                    self.send_header('Cache-Control', 'no-store, no-cache')
                    self.end_headers()
                    self.wfile.write(d)
                except Exception:
                    pass

        class T(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.t = T(('0.0.0.0', port), H)
        threading.Thread(target=self.t.serve_forever, daemon=True).start()

    def put(self, d):
        with self.lock:
            self.data = d

    def stop(self):
        try:
            self.t.shutdown()
        except Exception:
            pass


class GifCaster:
    def __init__(self, dev, secs=2.0, fps=10, size=(1920, 1080), colors=160,
                 on_status=None):
        self.dev = dev
        self.secs = secs
        self.fps = fps
        self.w, self.h = size
        self.colors = colors
        self.say = on_status or (lambda m: print(m, flush=True))
        self.srv = None
        self.stop_ev = threading.Event()
        self.ip = dev['ip']
        dl = dev.get('dlna') or {}
        self.dlna_port = dl.get('port', 49152)
        self.control = dl.get('control') or L.DEFAULT_CONTROL
        self.tmpdir = tempfile.mkdtemp(prefix='castgif_')
        self.stats = {'segments': 0, 'bytes': 0, 'kbps': 0.0, 't0': time.time()}
        self.mp4_q = queue.Queue(maxsize=2)

    # ---------------- GIF 生成
    def _grab_mp4(self, out, nframes):
        # 16:9 画布 + 等比缩放 + 黑边，保证不变形、内容不被裁掉
        vf = ('scale=%d:%d:force_original_aspect_ratio=decrease:flags=fast_bilinear,'
              'pad=%d:%d:(ow-iw)/2:(oh-ih)/2:black' % (self.w, self.h, self.w, self.h))
        cmd = [U.FFMPEG, '-y', '-v', 'error',
               '-f', 'gdigrab', '-framerate', str(self.fps), '-i', 'desktop',
               '-frames:v', str(nframes), '-vf', vf,
               '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
               '-pix_fmt', 'yuv420p', out]
        if sys.platform == 'win32':
            # 0x08000000 = CREATE_NO_WINDOW
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=40, creationflags=0x08000000)
        else:
            cmd[cmd.index('-f') + 1] = 'x11grab' if sys.platform != 'darwin' else 'avfoundation'
            cmd[cmd.index('-i') + 1] = ':0.0' if sys.platform != 'darwin' else '1'
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=40)

    def _sig(self, mp4):
        """画面指纹：抽中段一帧缩成 32x18 灰度。用来判断画面有没有变。"""
        raw = mp4 + '.raw'
        mid = max(0, int(self.secs * self.fps) // 2)
        cmd = [U.FFMPEG, '-y', '-v', 'error', '-i', mp4,
               '-vf', 'select=eq(n\\,%d),scale=32:18,format=gray' % mid,
               '-frames:v', '1', '-f', 'rawvideo', raw]
        self._run(cmd, 20)
        try:
            return open(raw, 'rb').read()
        except Exception:
            return b''

    @staticmethod
    def _changed(a, b):
        """两段指纹差异超过阈值就认为画面变了（屏幕时钟跳动不算）"""
        if not a or not b or len(a) != len(b):
            return True
        diff = sum(1 for x, y in zip(a, b) if abs(x - y) > 12)
        return diff / float(len(a)) > 0.012

    def _mp4_to_gif(self, src, out):
        vf = ('fps=%d,split[a][b];[a]palettegen=max_colors=%d:stats_mode=diff[p];'
              '[b][p]paletteuse=dither=none:diff_mode=rectangle'
              % (self.fps, self.colors))
        self._run([U.FFMPEG, '-y', '-v', 'error', '-i', src, '-vf', vf,
                   '-f', 'gif', '-loop', '0', out], 40)

    @staticmethod
    def _run(cmd, timeout):
        if sys.platform == 'win32':
            return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  timeout=timeout, creationflags=0x08000000)
        return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=timeout)

    def make_segment(self, idx):
        n = max(2, int(round(self.secs * self.fps)))
        mp4 = os.path.join(self.tmpdir, 's%d.mp4' % (idx % 2))
        gif = os.path.join(self.tmpdir, 's%d.gif' % (idx % 2))
        self._grab_mp4(mp4, n)
        self._mp4_to_gif(mp4, gif)
        if not os.path.exists(gif):
            return None
        return open(gif, 'rb').read()

    # ---------------- 采集线程：连续抓段，不停顿
    def _grabber(self):
        n = max(2, int(round(self.secs * self.fps)))
        i = 0
        while not self.stop_ev.is_set():
            i += 1
            mp4 = os.path.join(self.tmpdir, 'g%d.mp4' % (i % 3))
            self._grab_mp4(mp4, n)
            try:
                self.mp4_q.put_nowait((i, mp4))
            except Exception:
                # 队列满：丢掉最旧的一段，保证播放的都是新画面
                try:
                    self.mp4_q.get_nowait()
                    self.mp4_q.put_nowait((i, mp4))
                except Exception:
                    pass

    # ---------------- 主循环
    def run(self, duration=0):
        my = U.local_ip_for(self.ip)
        self.srv = GifServer()
        threading.Thread(target=self._grabber, daemon=True).start()
        t0 = time.time()
        idx = 0          # 已推送段数
        ok = False
        last_sig = b''
        last_url = ''
        idle_rounds = 0  # 连续跳过（画面没变）
        fails = 0
        seg_path = os.path.join(self.tmpdir, 'p.gif')
        last_seg_at = time.time()
        while not self.stop_ev.is_set():
            try:
                seg_id, mp4 = self.mp4_q.get(timeout=0.5)
                last_seg_at = time.time()
            except queue.Empty:
                # 采集一段要 secs 秒，短暂空转是正常的；真卡住才报
                if time.time() - last_seg_at > max(6.0, self.secs * 4):
                    self.say('采集没有输出，重试…')
                    last_seg_at = time.time()
                continue

            sig = self._sig(mp4)
            # 画面没变：什么都不用做，设备正在循环播放上一段
            if idx > 0 and not self._changed(last_sig, sig):
                idle_rounds += 1
                if idle_rounds in (1, 5) or idle_rounds % 30 == 0:
                    self.say('画面未变化，保持当前画面')
                if duration and time.time() - t0 > duration:
                    break
                continue
            idle_rounds = 0

            t_enc = time.time()
            self._mp4_to_gif(mp4, seg_path)
            if not os.path.exists(seg_path):
                continue
            data = open(seg_path, 'rb').read()

            # 新内容先就位，再通知设备来拉，避免它拉到旧图
            self.srv.put(data)
            idx += 1
            enc = time.time() - t_enc
            self.stats['segments'] = idx
            self.stats['bytes'] += len(data)
            el = max(0.001, time.time() - t0)
            self.stats['kbps'] = self.stats['bytes'] * 8 / el / 1000.0

            url = 'http://%s:%d/live.gif?v=%d' % (my, HTTP_PORT, idx)
            got = False
            for attempt in range(3):
                if self.stop_ev.is_set():
                    break
                if L.set_uri(self.ip, self.dlna_port, self.control, url):
                    got = True
                    break
                time.sleep(0.35 * (attempt + 1))
            if not got:
                fails += 1
                if fails == 1:
                    self.say('设备没响应，重试中…')
                if fails >= 6:
                    self.say('连不上设备：请把投影仪停在「投屏/等待接收」页再试一次')
                    break
                time.sleep(0.8)
                continue
            fails = 0
            last_url = url
            L.do_play(self.ip, self.dlna_port, self.control)
            last_sig = sig
            if not ok:
                ok = True
                self.say('已连接，开始投屏')
            self.say('第 %d 段  %dKB  编码 %.1fs' % (idx, len(data) // 1024, enc))

            if duration and time.time() - t0 > duration:
                break
        if self.srv:
            self.srv.stop()
        return self.stats

    def stop(self):
        self.stop_ev.set()


def run(dev, secs=2.0, fps=10, size=(1920, 1080), colors=160,
        duration=0, stop_event=None, on_status=None):
    c = GifCaster(dev, secs=secs, fps=fps, size=size, colors=colors, on_status=on_status)
    if stop_event is not None:
        threading.Thread(target=lambda: (stop_event.wait(), c.stop()), daemon=True).start()
    return c.run(duration=duration)


if __name__ == '__main__':
    import discover as D
    devs = [d for d in D.discover(progress=print) if d.get('dlna')]
    if not devs:
        print('没找到支持 DLNA 的设备')
        sys.exit(1)
    dur = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    run(devs[0], duration=dur)
