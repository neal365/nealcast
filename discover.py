# -*- coding: utf-8 -*-
"""免费投屏 NealCast 设备发现 —— 不绑定任何品牌和型号

三条发现通道并行，结果合并：
  1. SSDP/UPnP 多播（几乎所有 DLNA 接收端）
  2. mDNS 多播（_airplay / _raop / 各家私有服务）
  3. 网段直连端口探测（兜底：设备可能因为防火墙不响应多播）

返回统一结构：
  {'ip', 'name', 'airplay': port|0, 'dlna': {'port','control'} , 'via': [...],
   'best': 'airplay'|'dlna'}
"""
import socket, struct, threading, concurrent.futures as futures
import urllib.request, re

# 常见 AirPlay RTSP 端口（标准 7000；乐播类设备常见 52244/49999/52070）
AIRPLAY_PORTS = (7000, 52244, 49999, 52070, 52999, 52888, 49153)
# 常见 DLNA 描述端口（UPnP 标准随机高端口；山寨设备固定这几个）
DLNA_PROBE_PORTS = (49152, 49153, 2869, 5000, 1901, 8080, 8200, 9090)

SSDP_ST = ('urn:schemas-upnp-org:device:MediaRenderer:1',
           'urn:schemas-upnp-org:service:AVTransport:1',
           'urn:dial-multiscreen-org:service:dial:1',
           'upnp:rootdevice',
           'ssdp:all')


# ---------------------------------------------------------------- utils
def local_ips():
    out = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            out.add(info[4][0])
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        out.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return sorted(out)


def _http_text(url, timeout=2.5):
    try:
        # 强制直连：Clash/系统代理会把局域网请求劫持走，导致全部超时
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(url, headers={'User-Agent': 'NealCast/1.0 UPnP/1.1'})
        with opener.open(req, timeout=timeout) as r:
            return r.read().decode('utf8', 'replace')
    except Exception:
        return ''


# ---------------------------------------------------------------- SSDP
def _ssdp_one(st, wait=2.4):
    msg = ('M-SEARCH * HTTP/1.1\r\n'
           'HOST: 239.255.255.250:1900\r\n'
           'MAN: "ssdp:discover"\r\n'
           f'MX: {int(wait)}\r\n'
           f'ST: {st}\r\n'
           'USER-AGENT: Cast/1.0 UPnP/1.1\r\n\r\n').encode()
    hits = {}
    for ip in local_ips():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.settimeout(0.4)
            s.bind((ip, 0))
            s.sendto(msg, ('239.255.255.250', 1900))
            end = time_end(wait)
            while True:
                left = end - _now()
                if left <= 0:
                    break
                s.settimeout(left)
                try:
                    data, addr = s.recvfrom(4096)
                except socket.timeout:
                    break
                except Exception:
                    break
                txt = data.decode('utf8', 'replace')
                m = re.search(r'^LOCATION:\s*(\S+)', txt, re.M | re.I)
                if m:
                    hits[addr[0]] = m.group(1)
            s.close()
        except Exception:
            pass
    return hits


def _now():
    import time
    return time.time()


def time_end(sec):
    import time
    return time.time() + sec


def ssdp_scan(wait=1.2):
    """一次把多个 ST 的 M-SEARCH 全发出去，统收 wait 秒。返回 {ip: location_url}"""
    hits = {}
    for ip in local_ips():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((ip, 0))
            for st in SSDP_ST:
                msg = ('M-SEARCH * HTTP/1.1\r\n'
                       'HOST: 239.255.255.250:1900\r\n'
                       'MAN: "ssdp:discover"\r\n'
                       'MX: 1\r\n'
                       f'ST: {st}\r\n'
                       'USER-AGENT: Cast/1.0 UPnP/1.1\r\n\r\n').encode()
                try:
                    s.sendto(msg, ('239.255.255.250', 1900))
                except Exception:
                    pass
            end = time_end(wait)
            while True:
                left = end - _now()
                if left <= 0:
                    break
                s.settimeout(left)
                try:
                    data, addr = s.recvfrom(4096)
                except Exception:
                    break
                txt = data.decode('utf8', 'replace')
                m = re.search(r'^LOCATION:\s*(\S+)', txt, re.M | re.I)
                if m:
                    hits[addr[0]] = m.group(1)
            s.close()
        except Exception:
            pass
    return hits


# ---------------------------------------------------------------- mDNS
def mdns_scan(wait=3.0):
    """返回 {ip: {'name': str, 'ports': {service: port}}}"""
    services = ('_airplay._tcp.local', '_raop._tcp.local', '_companion-link._tcp.local',
                '_lebo._tcp.local', '_hpplay._tcp.local', '_leboremote._tcp.local',
                '_googlecast._tcp.local')
    pkt = _mdns_query(services)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
    try:
        s.bind(('', 5353))
    except Exception:
        try:
            s.bind(('', 0))
        except Exception:
            return {}
    s.settimeout(0.6)
    try:
        s.sendto(pkt, ('224.0.0.251', 5353))
    except Exception:
        pass
    out = {}
    end = time_end(wait)
    while True:
        left = end - _now()
        if left <= 0:
            break
        s.settimeout(left)
        try:
            data, addr = s.recvfrom(9000)
        except Exception:
            continue
        ip = addr[0]
        rec = out.setdefault(ip, {'ports': {}, 'names': set()})
        try:
            for r in _parse_mdns(data):
                if r[0] == 'SRV':
                    svc = r[1].split('._')[0] + '.' + r[1].split('.')[0]
                    rec['ports'][r[1]] = r[2]
                    rec['names'].add(r[1])
                elif r[0] == 'TXT':
                    t = dict(_kv(x) for x in r[2] if '=' in x)
                    if t.get('model') and not rec.get('model'):
                        rec['model'] = t['model']
                    if t.get('fn') or t.get('md'):
                        rec['fn'] = t.get('fn') or t.get('md')
        except Exception:
            pass
    s.close()
    return out


def _kv(x):
    k, _, v = x.partition('=')
    return k, v


def _mdns_query(names):
    tid = b'\xab\xcd'
    hdr = tid + b'\x00\x00' + struct.pack('>HHHH', len(names), 0, 0, 0)
    q = b''
    for n in names:
        for p in n.split('.'):
            q += bytes([len(p)]) + p.encode()
        q += b'\x00' + struct.pack('>HH', 12, 1)
    return hdr + q


def _rdname(data, off):
    labels = []
    jumped = False
    while True:
        if off >= len(data):
            break
        ln = data[off]
        if ln == 0:
            off += 1
            break
        if ln & 0xC0 == 0xC0:
            # 压缩指针：低位是相对报文头部的偏移
            ptr = ((ln & 0x3F) << 8) | (data[off + 1] if off + 1 < len(data) else 0)
            if not jumped:
                off += 2
                jumped = True
            sub = _rdname(data, ptr)[0]
            if sub:
                labels.append(sub)
            break
        labels.append(data[off + 1:off + 1 + ln].decode('utf8', 'ignore'))
        off += 1 + ln
    return '.'.join(labels), off


def _parse_mdns(data):
    out = []
    qd, an, ns, ar = struct.unpack('>HHHH', data[4:12])
    off = 12
    for _ in range(qd):
        _, off = _rdname(data, off)
        off += 4
    for _ in range(an + ns + ar):
        name, off = _rdname(data, off)
        if off + 10 > len(data):
            break
        rtype, rclass, ttl, rdlen = struct.unpack('>HHIH', data[off:off + 10])
        off += 10
        rdata = data[off:off + rdlen]
        if rtype == 16:
            txts, i = [], 0
            while i < len(rdata):
                ln = rdata[i]
                txts.append(rdata[i + 1:i + 1 + ln].decode('utf8', 'ignore'))
                i += 1 + ln
            out.append(('TXT', name, txts))
        elif rtype == 33 and rdlen >= 6:
            out.append(('SRV', name, struct.unpack('>HHH', rdata[:6])[2], ''))
        elif rtype == 1 and rdlen == 4:
            out.append(('A', name, '.'.join(str(b) for b in rdata)))
        off += rdlen
    return out


# ---------------------------------------------------------------- 直连探测
def _tcp_open(ip, port, t=0.45):
    s = socket.socket()
    s.settimeout(t)
    r = s.connect_ex((ip, port))
    s.close()
    return r == 0


def _dlna_of(ip, ports=None):
    """拿 DMR 描述，返回 (name, port, control_url, xml)"""
    for port in (ports or DLNA_PROBE_PORTS):
        if not _tcp_open(ip, port, 0.35):
            continue
        txt = _http_text(f'http://{ip}:{port}/description.xml', 2.0)
        if not txt or '<device' not in txt:
            continue
        nm = re.search(r'<friendlyName>([^<]+)</friendlyName>', txt)
        avt = re.search(r'AVTransport:1</serviceType>.*?<controlURL>([^<]+)<', txt, re.S)
        # 没有 AVTransport 就不是能投屏的 DMR，不能光看端口开着
        if not avt:
            continue
        return (nm.group(1).strip() if nm else f'DLNA@{ip}'), port, avt.group(1), txt
    return None


SCAN_PORTS = (49152, 52244, 7000, 49153, 8080)


def _probe_ip(ip, t=0.3):
    """快速探活：只有常见投屏端口开着才继续深挖，避免 254 个地址逐个全端口扫"""
    hit = [p for p in SCAN_PORTS if _tcp_open(ip, p, t)]
    if not hit:
        return None
    air = next((p for p in hit if p in AIRPLAY_PORTS), 0)
    d = None
    if any(p in DLNA_PROBE_PORTS for p in hit):
        d = _dlna_of(ip, ports=[p for p in hit if p in DLNA_PROBE_PORTS])
    if not air and not d:
        return None
    return ip, air, d


def primary_ip():
    """本机用于局域网通信的地址（排除 APIPA 169.254.x 和回环）"""
    best = None
    for ip in local_ips():
        if ip.startswith('169.254.') or ip.startswith('127.'):
            continue
        if ip.startswith(('192.168.', '10.')) or re.match(r'172\.(1[6-9]|2\d|3[01])\.', ip):
            return ip
        best = best or ip
    return best or '192.168.1.1'


def _scan_subnet(cands):
    """网段直连探测，返回 [(ip, air, dlna)]"""
    out = []
    with futures.ThreadPoolExecutor(max_workers=160) as ex:
        for r in ex.map(_probe_ip, cands):
            if r:
                out.append(r)
    return out


def discover(timeout=6.0, subnet=None, progress=None):
    """主入口。三条通道并行跑，返回设备列表"""
    found = {}
    ips = set()

    def note_progress(msg):
        if progress:
            progress(msg)

    base = subnet or (primary_ip().rsplit('.', 1)[0] + '.')
    cands = [base + str(n) for n in range(1, 255)]

    note_progress('正在查找设备…')
    res = {}

    def do_ssdp():
        try:
            res['ssdp'] = ssdp_scan(1.2)
        except Exception:
            res['ssdp'] = {}

    def do_mdns():
        try:
            res['mdns'] = mdns_scan(1.4)
        except Exception:
            res['mdns'] = {}

    def do_scan():
        try:
            res['scan'] = _scan_subnet(cands)
        except Exception:
            res['scan'] = []

    ths = [threading.Thread(target=f, daemon=True) for f in (do_ssdp, do_mdns, do_scan)]
    for t in ths:
        t.start()
    for t in ths:
        t.join(max(1.0, timeout))

    for ip, loc in (res.get('ssdp') or {}).items():
        ips.add(ip)
        found.setdefault(ip, {'ip': ip, 'via': [], 'loc': loc})

    for ip, info in (res.get('mdns') or {}).items():
        ips.add(ip)
        d = found.setdefault(ip, {'ip': ip, 'via': [], 'loc': None})
        d['mdns'] = info

    for item in (res.get('scan') or []):
        ip, air, dl = item
        d = found.setdefault(ip, {'ip': ip, 'via': [], 'loc': None})
        d['_air'] = air
        d['_dl'] = dl

    # 汇总成统一结构
    devs = []
    for ip, d in found.items():
        dev = {'ip': ip, 'name': '', 'airplay': 0, 'dlna': None, 'via': []}
        air = d.get('_air') or 0
        dl = d.get('_dl')

        md = d.get('mdns') or {}
        for svc, port in (md.get('ports') or {}).items():
            if 'airplay' in svc.lower() or 'raop' in svc.lower():
                air = port
        if air:
            dev['airplay'] = air
            dev['via'].append('airplay')
        if not dl and d.get('loc'):
            txt = _http_text(d['loc'], 1.5)
            nm = re.search(r'<friendlyName>([^<]+)</friendlyName>', txt or '')
            avt = re.search(r'AVTransport:1</serviceType>.*?<controlURL>([^<]+)<', txt or '', re.S)
            # 没有 AVTransport 的 UPnP 设备（路由/打印机/摄像头…）不算可投屏
            if avt:
                from urllib.parse import urlparse
                pu = urlparse(d['loc'])
                dl = (nm.group(1).strip() if nm else '', pu.port or 80, avt.group(1), txt)
        if dl:
            dev['dlna'] = {'name': dl[0], 'port': dl[1], 'control': dl[2]}
            dev['via'].append('dlna')
        nm_dl = (dl[0] if dl else '').strip()
        nm_md = (md.get('fn') or '').strip()
        # DLNA 的 friendlyName 最可靠；mDNS 名字常有截断或乱码，只作兜底
        if not nm_dl or len(nm_dl) < 2:
            nm_dl = ''
        if not nm_md or len(nm_md) < 3 or not any(c.isalnum() for c in nm_md):
            nm_md = ''
        dev['name'] = nm_dl or nm_md or (md.get('model') or '').strip() or f'设备 {ip}'
        dev['best'] = 'airplay' if dev['airplay'] else ('dlna' if dev['dlna'] else None)
        # 本工具走 DLNA 投屏，只列出真正能投的设备（端口开着≠能投）
        if dev['dlna']:
            devs.append(dev)
    devs.sort(key=lambda x: (not x['dlna'], x['ip']))
    note_progress('完成')
    return devs


if __name__ == '__main__':
    import time, pprint
    t = time.time()
    for d in discover(progress=lambda m: print('  ' + m)):
        print('%-16s %-28s airplay=%-6s dlna=%s' %
              (d['ip'], d['name'], d['airplay'] or '-',
               (d['dlna'] or {}).get('port', '-')))
    print('用时 %.1fs' % (time.time() - t))
