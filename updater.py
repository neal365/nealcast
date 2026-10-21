# -*- coding: utf-8 -*-
"""在线升级：检测新版本 -> 下载安装包 -> 静默安装并重启。

不需要任何自建服务端，也不需要一个中心服务器：
  * 版本号直接读 Gitee / GitHub 的公开 tags 接口（匿名可读）
  * 安装包就放在仓库 release/ 目录里，随 tag 一起发布，
    下载时取该 tag 的源码归档 zip，从里面把安装包解出来

两条通道互为备份：Gitee 优先，失败自动走 GitHub。
"""

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

APP_VERSION = '1.2.1'

GITEE_TAGS = 'https://gitee.com/api/v5/repos/diuber/nealcast/tags'
GITHUB_TAGS = 'https://api.github.com/repos/neal365/nealcast/tags'
GITEE_ARCHIVE = 'https://gitee.com/diuber/nealcast/archive/refs/tags/{tag}.zip'
GITHUB_ARCHIVE = 'https://github.com/neal365/nealcast/archive/refs/tags/{tag}.zip'
GITEE_CONTENTS = 'https://gitee.com/api/v5/repos/diuber/nealcast/contents/README.md?ref=main'
GITEE_README = 'https://gitee.com/diuber/nealcast/raw/main/README.md'
GITHUB_README = 'https://raw.githubusercontent.com/neal365/nealcast/main/README.md'

UA = 'NealCast/%s' % APP_VERSION


def _get(url, timeout=8):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def ver_tuple(v):
    ns = re.findall(r'\d+', v or '')
    return tuple(int(n) for n in ns[:3]) or (0,)


def latest(timeout=8):
    """查最新已发布版本。返回 {'version','tag','source'}，查不到返回 None"""
    err = None
    for source, api, arch in (('gitee', GITEE_TAGS, GITEE_ARCHIVE),
                              ('github', GITHUB_TAGS, GITHUB_ARCHIVE)):
        try:
            data = json.loads(_get(api, timeout).decode('utf8', 'replace'))
            tags = [t.get('name', '') for t in data
                    if re.match(r'^v\d', t.get('name', ''))]
            if not tags:
                continue
            tags.sort(key=ver_tuple, reverse=True)
            tag = tags[0]
            return {'version': tag.lstrip('vV'), 'tag': tag,
                    'source': source, 'url': arch.format(tag=tag)}
        except Exception as e:
            err = e
    return None


def has_update(info, current=APP_VERSION):
    return bool(info) and ver_tuple(info.get('version')) > ver_tuple(current)


def _readme_text(timeout=8):
    """读仓库里的 README。先走 contents API（匿名稳定），再退到 raw，最后 GitHub"""
    try:
        d = json.loads(_get(GITEE_CONTENTS, timeout).decode('utf8', 'replace'))
        txt = base64.b64decode(d.get('content') or '').decode('utf8', 'replace')
        if txt:
            return txt
    except Exception:
        pass
    for u in (GITEE_README, GITHUB_README):
        try:
            txt = _get(u, timeout).decode('utf8', 'replace')
            if txt:
                return txt
        except Exception:
            continue
    return ''


def notes(timeout=8):
    """取 README 里最新一版的更新日志，失败返回空串（不阻断升级）"""
    txt = _readme_text(timeout)
    if not txt:
        return ''
    m = re.search(r'##\s*更新日志\s*\n(.*?)(?=\n##\s|\Z)', txt, re.S)
    if not m:
        return ''
    out = []
    for line in m.group(1).splitlines():
        t = line.strip()
        if not t:
            if out:
                break           # 只取最新一个版本块
            continue
        out.append(t.replace('**', ''))
    return ''.join(out)


def _tmpdir():
    d = os.path.join(tempfile.gettempdir(), 'NealCast-Update')
    os.makedirs(d, exist_ok=True)
    return d


def download(info, progress=None, cancel=None, timeout=90):
    """下载 tag 归档并解出安装包，返回本地 exe 路径"""
    urls = [info['url']]
    urls.append(GITHUB_ARCHIVE if info['source'] == 'gitee' else GITEE_ARCHIVE)
    urls[-1] = urls[-1].format(tag=info['tag'])
    last = None
    for u in urls:
        try:
            return _fetch_and_unpack(u, info, progress, cancel, timeout)
        except Exception as e:
            last = e
    raise RuntimeError(str(last) if last else '下载失败')


def _fetch_and_unpack(url, info, progress, cancel, timeout):
    d = _tmpdir()
    zp = os.path.join(d, '%s.zip' % info['tag'])
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        total = int(r.headers.get('Content-Length') or 0)
        got = 0
        with open(zp, 'wb') as f:
            while True:
                if cancel and cancel():
                    f.close()
                    os.remove(zp)
                    raise RuntimeError('已取消')
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if progress:
                    progress(got, total)
    try:
        ver = info['version']
        want = 'NealCast-Setup-%s.exe' % ver
        with zipfile.ZipFile(zp) as z:
            names = [n for n in z.namelist() if n.endswith(want)]
            if not names:
                names = [n for n in z.namelist()
                         if n.lower().endswith('.exe') and 'Setup' in n]
            if not names:
                raise RuntimeError('归档里没有安装包')
            name = names[0]
            out = os.path.join(d, os.path.basename(name))
            with z.open(name) as src, open(out, 'wb') as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
        if not os.path.getsize(out):
            raise RuntimeError('解出的安装包是空的')
    finally:
        try:
            os.remove(zp)
        except Exception:
            pass
    return out


def installed_dir():
    return os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'NealCast')


def install_and_restart(setup, app=None):
    """退出自己后静默安装，装完自动启动新版本。

    不能直接 Popen 安装包再退出：Inno 会检测到 NealCast.exe 仍被占用。
    所以写一个 bat：先等几秒让本进程退出，再 /wait 安装，最后启动新版。
    """
    app = app or os.path.join(installed_dir(), 'NealCast.exe')
    bat = os.path.join(_tmpdir(), 'do_update.bat')
    lines = [
        '@echo off',
        'ping -n 3 127.0.0.1 >nul',
        'start "" /wait "%s" /VERYSILENT /SUPPRESSMSGBOXES /NOCANCEL /NORESTART' % setup,
    ]
    lines.append('if exist "%s" start "" "%s"' % (app, app))
    lines.append('del "%%~f0"')
    with open(bat, 'w', encoding='gbk', errors='replace') as f:
        f.write('\r\n'.join(lines) + '\r\n')
    subprocess.Popen(['cmd', '/c', bat],
                     creationflags=0x00000008 | 0x00000200,
                     close_fds=True)
    return bat


def quit_self(root=None):
    """关掉界面再硬退出，给 bat 让路"""
    try:
        if root is not None:
            root.destroy()
    except Exception:
        pass
    try:
        os._exit(0)
    except Exception:
        sys.exit(0)


if __name__ == '__main__':
    print('当前版本', APP_VERSION)
    info = latest()
    print('线上最新', info)
    print('需要更新 =', has_update(info))
    if info:
        print('更新日志:\n' + (notes() or '(无)'))
