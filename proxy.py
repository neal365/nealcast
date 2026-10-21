# -*- coding: utf-8 -*-
"""代理 / VPN 进程探测与关闭。

Clash、V2Ray、sing-box 这类工具的 TUN（虚拟网卡）模式会把**任意**地址的 TCP
连接都假接受，于是局域网扫描结果全是假的、真实投影仪反而超时不可达。
这里负责把它们找出来，并在用户点一下之后关掉。

注意：只处理本机当前用户的进程，不做任何系统级修改；关掉的都是用户自己开的
代理客户端，随时可以再手动开回来。
"""
import re
import subprocess
import sys

# (进程名关键字, 界面显示名, 是否可一键关闭)
# 最后一列为 False 的是组网类（Tailscale / ZeroTier / WireGuard 等），
# 关掉可能直接断掉远程办公网络，所以只提示、不自动关。
KNOWN = (
    ('clash',            'Clash',        True),
    ('clash-verge',      'Clash Verge',  True),
    ('clash.meta',       'Clash Meta',   True),
    ('verge',            'Clash Verge',  True),
    ('mihomo',           'Mihomo',       True),
    ('v2ray',            'V2Ray',        True),
    ('xray',             'Xray',         True),
    ('sing-box',         'sing-box',     True),
    ('singbox',          'sing-box',     True),
    ('shadowsocks',      'Shadowsocks',  True),
    ('shadowsocksr',     'ShadowsocksR', True),
    ('trojan',           'Trojan',       True),
    ('hysteria',         'Hysteria',     True),
    ('naiveproxy',       'NaiveProxy',   True),
    ('tun2socks',        'tun2socks',    True),
    ('netch',            'Netch',        True),
    ('proxifier',        'Proxifier',    True),
    ('wireguard',        'WireGuard',    False),
    ('openvpn',          'OpenVPN',      False),
    ('zerotier',         'ZeroTier',     False),
    ('tailscale',        'Tailscale',    False),
)

# 这些进程本身不是代理，但名字里可能命中上面的关键字，排除掉
EXCLUDE = ('svchost', 'spoolsv', 'SearchHost', 'ShellExperience')


def _tasklist():
    """返回 [(进程名.exe, pid)]，失败返回 []"""
    if sys.platform != 'win32':
        return []
    try:
        r = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'],
                           capture_output=True, timeout=10)
    except Exception:
        return []
    txt = r.stdout.decode('gbk', 'replace') or r.stdout.decode('utf8', 'replace')
    out = []
    for line in txt.splitlines():
        m = re.match(r'^\s*"([^"]+)"\s*,\s*"(\d+)"', line)
        if m:
            out.append((m.group(1), int(m.group(2))))
    return out


def running():
    """找出正在运行的代理 / VPN。

    返回 {'closable': [(显示名, [exe...])], 'manual': [显示名]}
    """
    res, manual, seen = [], [], {}
    for exe, pid in _tasklist():
        low = exe.lower()
        if any(e.lower() in low for e in EXCLUDE):
            continue
        base = low[:-4] if low.endswith('.exe') else low
        for key, label, closable in KNOWN:
            if key in base:
                if not closable:
                    if label not in manual:
                        manual.append(label)
                else:
                    seen.setdefault(label, set()).add(exe)
                break
    for label, exes in seen.items():
        res.append((label, sorted(exes)))
    res.sort()
    return {'closable': res, 'manual': manual}


def names(apps):
    """把扫描结果拼成一句人话：'Clash' / 'Clash 和 V2Ray'"""
    ls = [n for n, _ in apps.get('closable', [])]
    ls += [n for n in apps.get('manual', [])]
    if not ls:
        return ''
    if len(ls) == 1:
        return ls[0]
    return '、'.join(ls[:-1]) + ' 和 ' + ls[-1]


def kill(apps):
    """关掉所有可一键关闭的代理进程。返回 (成功数, [失败名])"""
    if sys.platform != 'win32':
        return 0, []
    exes = []
    for _label, group in apps.get('closable', []):
        for e in group:
            if e not in exes:
                exes.append(e)
    ok, fail = 0, []
    for exe in exes:
        try:
            r = subprocess.run(['taskkill', '/F', '/T', '/IM', exe],
                               capture_output=True, timeout=15)
            if r.returncode == 0:
                ok += 1
            else:
                fail.append(exe)
        except Exception:
            fail.append(exe)
    return ok, fail


if __name__ == '__main__':
    a = running()
    print('检测到:', a)
    print('显示名:', names(a))
