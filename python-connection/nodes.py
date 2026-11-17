"""Local TCP node transports. No TUN, external core, system proxy or DNS change.

Wire formats: shadowsocks.org/doc/aead.html; anytls/anytls-go docs/protocol.md.
Only TCP is provided. AnyTLS uses standard verified Python TLS, not browser impersonation.
"""
from components import activate
activate()

import asyncio
import base64
import hashlib
import ipaddress
import os
import random
import ssl
import struct
import time

CIPHERS = {'aes-128-gcm': 16, 'aes-256-gcm': 32, 'chacha20-ietf-poly1305': 32}
DEFAULT_PADDING = 'stop=8\n0=30-30\n1=100-400\n2=400-500,c,500-1000,c,500-1000,c,500-1000,c,500-1000\n3=9-9,500-1000\n4=500-1000\n5=500-1000\n6=500-1000\n7=500-1000'


def validate(n):
    if not isinstance(n, dict) or n.get('type') not in ('ss', 'anytls'):
        raise ValueError('暂不支持此协议；支持 SS AEAD、AnyTLS')
    server = n.get('server', '')
    if not isinstance(server, str) or not server or len(server)>253 or any(x.isspace() or x in '/\\@' for x in server):
        raise ValueError('节点地址无效')
    if type(n.get('port')) is not int or not 1 <= n['port'] <= 65535:
        raise ValueError('节点端口无效')
    if not isinstance(n.get('password'), str) or not n['password']:
        raise ValueError('节点缺少认证')
    if n['type']=='ss':
        if n.get('cipher') not in CIPHERS:
            raise ValueError('暂不支持此 SS 加密方式')
        if n.get('plugin'):
            opts=n.get('plugin-opts', {})
            if n['plugin'] not in ('obfs','obfs-local') or opts.get('mode')!='http' or set(opts)-{'mode','host'}:
                raise ValueError('暂不支持此插件；支持 simple-obfs HTTP')
            host=opts.get('host','')
            if not isinstance(host,str) or not host or any(ch.isspace() or ch in '/\\' for ch in host):
                raise ValueError('HTTP 混淆域名无效')
    else:
        if n.get('skip-cert-verify'):
            raise ValueError('该节点要求跳过证书验证，未启用；请选证书有效的节点或 SS')
        sni=n.get('sni') or n.get('servername') or server
        if not isinstance(sni,str) or not sni or any(ch.isspace() or ch in '/\\' for ch in sni):
            raise ValueError('节点证书域名无效')
        if not isinstance(n.get('alpn', []), list) or any(not isinstance(s,str) or not s.isascii() or not 1<=len(s)<=255 for s in n.get('alpn', [])):
            raise ValueError('ALPN 无效')
    if n.get('dialer-proxy') or n.get('network') not in (None, '', 'tcp'):
        raise ValueError('暂不支持此节点的链式连接或传输方式')


def address(host, port):
    try:
        ip=ipaddress.ip_address(host)
        result=bytes([1 if ip.version==4 else 4])+ip.packed
    except ValueError:
        raw=host.encode('idna')
        if not 0<len(raw)<=255:
            raise ValueError('Invalid destination')
        result=b'\x03'+bytes([len(raw)])+raw
    return result+struct.pack('!H',port)


async def connect(n, interface):
    from relay import socket_open, doh
    try:
        ip=str(ipaddress.ip_address(n['server']))
    except ValueError:
        ip=await asyncio.to_thread(doh,n['server'],interface)
    return await socket_open(ip,n['port'],interface)


class SSStream:
    def __init__(self, r, w, n, salts=None):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives import hashes
        self.r,self.w,self.node=r,w,n
        self.salts=salts if salts is not None else set()
        self.size=CIPHERS[n['cipher']]
        derived=b''; block=b''
        while len(derived)<self.size:
            block=hashlib.md5(block+n['password'].encode()).digest();derived+=block
        self.key=derived[:self.size]
        algorithm=ChaCha20Poly1305 if n['cipher']=='chacha20-ietf-poly1305' else AESGCM
        self.derive=lambda salt: algorithm(HKDF(algorithm=hashes.SHA1(),length=self.size,salt=salt,info=b'ss-subkey').derive(self.key))
        self.salt=os.urandom(self.size);self.enc=self.derive(self.salt);self.dec=None
        self.tx=self.rx=0;self.sent=False;self.buffer=b'';self.header=False

    def seal(self,data):
        value=self.enc.encrypt(self.tx.to_bytes(12,'little'),data,None);self.tx+=1;return value

    def write(self,data):
        if not data:return
        raw=b''
        if not self.sent:raw=self.salt
        for off in range(0,len(data),0x3fff):
            part=data[off:off+0x3fff]
            raw+=self.seal(struct.pack('!H',len(part)))+self.seal(part)
        if not self.sent and self.node.get('plugin'):
            host=self.node['plugin-opts']['host'];key=base64.b64encode(os.urandom(16)).decode()
            raw=(f'GET / HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nContent-Length: {len(raw)}\r\n\r\n').encode()+raw
        self.sent=True;self.w.write(raw)

    async def read(self,n=65536):
        if not self.header:
            if self.node.get('plugin'):
                head=await self.r.readuntil(b'\r\n\r\n')
                if not head.startswith(b'HTTP/1.1 '):raise OSError('Invalid obfs response')
            self.header=True
        if self.dec is None:
            salt=await self.r.readexactly(self.size)
            if salt in self.salts:raise OSError("Repeated SS salt")
            if len(self.salts)>=16384:raise OSError("SS session limit; restart this connection")
            self.salts.add(salt)
            self.dec=self.derive(salt)
        while not self.buffer:
            try:raw=await self.r.readexactly(18)
            except asyncio.IncompleteReadError as e:
                if not e.partial:return b''
                raise
            length=self.dec.decrypt(self.rx.to_bytes(12,'little'),raw,None);self.rx+=1
            size=struct.unpack('!H',length)[0]
            if size>0x3fff:raise OSError('Invalid SS chunk')
            raw=await self.r.readexactly(size+16)
            self.buffer=self.dec.decrypt(self.rx.to_bytes(12,'little'),raw,None);self.rx+=1
        result,self.buffer=self.buffer[:n],self.buffer[n:];return result

    async def drain(self):await self.w.drain()
    def close(self):self.w.close()
    async def wait_closed(self):await self.w.wait_closed()
    def get_extra_info(self,name,default=None):return self.w.get_extra_info(name,default)


def frame(cmd,sid=0,data=b''):
    return struct.pack('!BIH',cmd,sid,len(data))+data


def padding_scheme(text):
    if len(text)>8192:raise ValueError('Padding too large')
    result={}
    for line in text.splitlines():
        key,sep,value=line.partition('=')
        if not sep:raise ValueError('Invalid padding')
        if key=='stop':
            stop=int(value)
            if not 0<=stop<=100:raise ValueError('Invalid padding stop')
            result[key]=stop;continue
        index=int(key)
        if not 0<=index<100:raise ValueError('Invalid padding index')
        parts=[]
        for item in value.split(','):
            if item=='c':parts.append('c');continue
            bounds=item.split('-')
            if len(bounds)!=2:raise ValueError('Invalid padding range')
            a,b=map(int,bounds)
            if not 0<=a<=b<=65535:raise ValueError('Invalid padding size')
            parts.append((a,b))
        if len(parts)>32:raise ValueError('Too many padding segments')
        result[index]=parts
    return result


class AnyStream:
    def __init__(self,session,sid):
        self.session,self.sid=session,sid
        self.reader=asyncio.StreamReader(limit=131072)
        self.closed=False;self.remote_closed=False
    async def read(self,n=65536):return await self.reader.read(n)
    def write(self,data):
        if self.closed:raise OSError('Stream closed')
        for off in range(0,len(data),65535):self.session.send(frame(2,self.sid,data[off:off+65535]))
    async def drain(self):await self.session.w.drain()
    def close(self):
        if self.closed:return
        self.closed=True
        if not self.remote_closed and not self.session.dead:
            self.session.send(frame(3,self.sid))
        # Reuse only after server FIN; otherwise late frames cannot pollute a new stream.
        self.session.release(self)
    async def wait_closed(self):
        if not self.session.dead:await self.session.w.drain()
    def get_extra_info(self,name,default=None):return self.session.w.get_extra_info(name,default)


class AnySession:
    def __init__(self,pool,r,w):
        self.pool,self.r,self.w=pool,r,w;self.dead=False;self.stream=None;self.sid=0;self.packet=1;self.expiry=None
        pool.sequence+=1;self.sequence=pool.sequence
        self.task=asyncio.create_task(self.read_loop())
    def send(self,data):
        if self.dead:raise OSError('Session closed')
        scheme=padding_scheme(self.pool.scheme)
        for item in scheme.get(self.packet,[]) if self.packet<scheme.get('stop',0) else []:
            if item=='c':
                if not data:break
                continue
            target=random.randint(*item)
            part,data=data[:target],data[target:]
            remain=target-len(part)
            if remain>=7:part+=frame(0,0,bytes(remain-7))
            if part:self.w.write(part)
        if data:self.w.write(data)
        self.packet+=1
    async def open(self,host,port):
        if self.expiry:self.expiry.cancel();self.expiry=None
        self.sid+=1;stream=AnyStream(self,self.sid);self.stream=stream
        data=frame(1,self.sid)+frame(2,self.sid,address(host,port))
        if self.sid==1:
            settings=f'v=2\nclient=python-connection/0.2\npadding-md5={hashlib.md5(self.pool.scheme.encode()).hexdigest()}'.encode()
            data=frame(4,0,settings)+data
        self.send(data);await self.w.drain();return stream,stream
    def release(self,stream):
        if self.stream is not stream:return
        self.stream=None
        if not self.dead:
            self.pool.idle.append(self)
            self.expiry=asyncio.get_running_loop().call_later(30,self.close)
    async def read_loop(self):
        try:
            while True:
                cmd,sid,size=struct.unpack('!BIH',await self.r.readexactly(7));data=await self.r.readexactly(size)
                stream=self.stream if self.stream and self.stream.sid==sid else None
                if cmd==2 and stream:
                    if len(stream.reader._buffer)+len(data)>2*1024*1024:raise OSError('Receive limit')
                    stream.reader.feed_data(data)
                elif cmd==3 and stream:
                    stream.remote_closed=True;stream.reader.feed_eof()
                    if stream.closed:self.release(stream)
                elif cmd==5:raise OSError('Server alert')
                elif cmd==6:
                    text=data.decode();padding_scheme(text);self.pool.scheme=text
                elif cmd==7 and data and stream:raise OSError('Upstream refused')
                elif cmd==8:self.send(frame(9,sid));await self.w.drain()
                elif cmd not in (0,2,3,6,7,9,10):raise OSError('Invalid AnyTLS command')
        except asyncio.CancelledError:pass
        except Exception:
            if self.stream:self.stream.reader.set_exception(OSError('AnyTLS session ended'))
        finally:self.close()
    def close(self):
        if self.dead:return
        self.dead=True
        if self.expiry:self.expiry.cancel()
        if self in self.pool.idle:self.pool.idle.remove(self)
        self.pool.sessions.discard(self)
        if self.stream:self.stream.reader.feed_eof()
        self.w.close()
        if asyncio.current_task() is not self.task:self.task.cancel()


class NodeTransport:
    def __init__(self,node,interface=''):
        validate(node);self.node=node;self.interface=interface;self.scheme=DEFAULT_PADDING;self.idle=[];self.sessions=set();self.salts=set();self.sequence=0
    async def open(self,host,port):
        n=self.node
        if n['type']=='anytls':
            while self.idle:
                s=max(self.idle,key=lambda item:item.sequence);self.idle.remove(s)
                if not s.dead:return await s.open(host,port)
        r,w=await connect(n,self.interface)
        try:
            if n['type']=='ss':
                stream=SSStream(r,w,n,self.salts);stream.write(address(host,port));await stream.drain();return stream,stream
            context=ssl.create_default_context();context.minimum_version=ssl.TLSVersion.TLSv1_2
            if n.get('alpn'):context.set_alpn_protocols(n['alpn'])
            await w.start_tls(context,server_hostname=n.get('sni') or n.get('servername') or n['server'],ssl_handshake_timeout=12)
            scheme=padding_scheme(self.scheme);size=random.randint(*scheme.get(0,[(30,30)])[0])
            w.write(hashlib.sha256(n['password'].encode()).digest()+struct.pack('!H',size)+bytes(size));await w.drain()
            s=AnySession(self,r,w);self.sessions.add(s)
            return await s.open(host,port)
        except BaseException:
            w.close()
            try:await w.wait_closed()
            except Exception:pass
            raise
    async def close(self):
        sessions=list(self.sessions)
        for s in sessions:s.close()
        await asyncio.gather(*(s.task for s in sessions),return_exceptions=True)
        for s in sessions:
            try:await asyncio.wait_for(s.w.wait_closed(),2)
            except Exception:pass
