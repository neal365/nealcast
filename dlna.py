# -*- coding: utf-8 -*-
"""DLNA/UPnP AVTransport 客户端

只用标准 SOAP 动作：SetAVTransportURI / Play / Stop。
设备端是标准 DMR（Digital Media Renderer），不依赖任何厂商私有协议。
"""
import http.client

DEFAULT_CONTROL = '/_urn:schemas-upnp-org:service:AVTransport_control'


def soappost(ip, port, action, args, control):
    control = control or DEFAULT_CONTROL
    if not control.startswith('/'):
        control = '/' + control
    env = ('<?xml version="1.0" encoding="utf-8"?>'
           '<s:Envelope s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" '
           'xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
           f'<u:{action} xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">{args}</u:{action}>'
           '</s:Body></s:Envelope>')
    try:
        c = http.client.HTTPConnection(ip, port, timeout=6)
        c.request('POST', control, body=env.encode('utf8'),
                  headers={'Content-Type': 'text/xml; charset="utf-8"',
                           'SOAPACTION': f'"urn:schemas-upnp-org:service:AVTransport:1#{action}"',
                           'User-Agent': 'NealCast/1.0 UPnP/1.1'})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, body
    except Exception as e:
        return 0, str(e).encode()


def set_uri(ip, port, control, url):
    st, _ = soappost(ip, port, 'SetAVTransportURI',
                     f'<InstanceID>0</InstanceID><CurrentURI>{url}</CurrentURI>'
                     f'<CurrentURIMetaData></CurrentURIMetaData>', control)
    return st == 200


def do_play(ip, port, control):
    st, _ = soappost(ip, port, 'Play', '<InstanceID>0</InstanceID><Speed>1</Speed>', control)
    return st == 200


def do_stop(ip, port, control):
    try:
        soappost(ip, port, 'Stop', '<InstanceID>0</InstanceID>', control)
    except Exception:
        pass
