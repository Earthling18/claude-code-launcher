import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch,AsyncMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import nodes,profiles,subscriptions,manager
from resident import Resident

SS={'name':'日本 测试','type':'ss','server':'example.com','port':443,'cipher':'aes-128-gcm','password':'private-secret','plugin':'obfs','plugin-opts':{'mode':'http','host':'cdn.example.com'}}

class CatalogTests(unittest.TestCase):
    def test_import_redaction_update_and_snapshot_preserve_rules(self):
        with tempfile.TemporaryDirectory() as td,patch.object(profiles,'ROOT',Path(td)):
            result=subscriptions.import_source('测试',text=json.dumps({'proxies':[SS,dict(SS,type='vless',name='不支持')]}))
            rows=subscriptions.view()[0]['nodes']
            self.assertEqual(result['supported'],1)
            self.assertFalse(rows[1]['supported'])
            self.assertNotIn('private-secret',json.dumps(subscriptions.view()))
            chosen=subscriptions.select(result['id'],rows[0]['id'])['id']
            c,creds,_=profiles.load(chosen);self.assertNotIn('server_ip',c)
            c['direct']=['*.internal'];profiles.save(chosen,c,creds,profiles.revision(chosen))
            db=subscriptions.catalog();db['sources'][result['id']]['nodes'][0]['node']['password']='rotated'
            profiles.atomic_json(subscriptions.store_path(),db)
            self.assertEqual(profiles.load(chosen)[1]['node']['password'],'private-secret')
            subscriptions.select(result['id'],rows[0]['id'])
            c,creds,_=profiles.load(chosen)
            self.assertEqual(c['direct'],['*.internal']);self.assertEqual(creds['node']['password'],'rotated')
            self.assertNotIn('rotated',json.dumps(manager.profile_view(chosen)))
            self.assertEqual(subscriptions.parse(json.dumps([dict(SS,password='rotated')]))[0]['id'],rows[0]['id'])
            if os.name!='nt':self.assertEqual(subscriptions.store_path().stat().st_mode&0o777,0o600)

    def test_failed_import_is_atomic(self):
        with tempfile.TemporaryDirectory() as td,patch.object(profiles,'ROOT',Path(td)):
            subscriptions.import_source('ok',text=json.dumps([SS]));before=subscriptions.store_path().read_bytes()
            for text in ['bad','proxies: &x [*x]', '!!python/object/apply:os.system [echo bad]']:
                with self.assertRaises(Exception):subscriptions.import_source('bad',text=text)
                self.assertEqual(before,subscriptions.store_path().read_bytes())

    def test_update_with_only_unsupported_protocols_preserves_catalog(self):
        with tempfile.TemporaryDirectory() as td,patch.object(profiles,'ROOT',Path(td)):
            result=subscriptions.import_source('test',text=json.dumps([SS]))
            c=subscriptions.catalog();c['sources'][result['id']]['url']='https://example.com/subscription'
            profiles.atomic_json(subscriptions.store_path(),c);before=subscriptions.store_path().read_bytes()
            with patch.object(subscriptions,'fetch',return_value=json.dumps([dict(SS,type='vless')])):
                with self.assertRaises(ValueError):subscriptions.import_source('',ident=result['id'])
            self.assertEqual(before,subscriptions.store_path().read_bytes())

    def test_uri_base64_and_unsupported_plugins(self):
        auth=base64.urlsafe_b64encode(b'aes-128-gcm:secret').decode().rstrip('=')
        uri=f'ss://{auth}@example.com:443#Test'
        for text in [uri,base64.b64encode(uri.encode()).decode()]:
            self.assertTrue(subscriptions.parse(text)[0]['reason']=='')
        self.assertTrue(subscriptions.parse(json.dumps([dict(SS,plugin='v2ray-plugin')]))[0]['reason'])
        self.assertTrue(subscriptions.parse(json.dumps([dict(SS,type='anytls',**{'skip-cert-verify':True})]))[0]['reason'])
        with self.assertRaises(ValueError):subscriptions.fetch('https://127.0.0.1/secret')

class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_ss_aead_fragmentation_and_tamper(self):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives import hashes
        class Writer:
            def __init__(self):self.data=bytearray()
            def write(self,b):self.data.extend(b)
        r=asyncio.StreamReader();w=Writer();client=nodes.SSStream(r,w,SS)
        payload=nodes.address('chatgpt.com',443)+b'x'*20000;client.write(payload)
        head,raw=bytes(w.data).split(b'\r\n\r\n',1);self.assertIn(b'Host: cdn.example.com',head)
        salt,raw=raw[:16],raw[16:];key=hashlib.md5(SS['password'].encode()).digest()
        aead=AESGCM(HKDF(algorithm=hashes.SHA1(),length=16,salt=salt,info=b'ss-subkey').derive(key));nonce=0;decoded=b''
        while raw:
            length=struct.unpack('!H',aead.decrypt(nonce.to_bytes(12,'little'),raw[:18],None))[0];nonce+=1;raw=raw[18:]
            decoded+=aead.decrypt(nonce.to_bytes(12,'little'),raw[:length+16],None);nonce+=1;raw=raw[length+16:]
        self.assertEqual(decoded,payload)
        salt=b'a'*16;rx=AESGCM(HKDF(algorithm=hashes.SHA1(),length=16,salt=salt,info=b'ss-subkey').derive(key))
        response=b'HTTP/1.1 101 Switching Protocols\r\n\r\n'+salt+rx.encrypt(bytes(12),b'\x00\x05',None)+rx.encrypt((1).to_bytes(12,'little'),b'hello',None)
        task=asyncio.create_task(client.read(3))
        for i in range(0,len(response),3):r.feed_data(response[i:i+3]);await asyncio.sleep(0)
        self.assertEqual(await task,b'hel');self.assertEqual(await client.read(9),b'lo')
        r.feed_data(rx.encrypt((2).to_bytes(12,'little'),b'\x00\x01',None)+b'\0'*17)
        with self.assertRaises(Exception):await client.read()

    async def test_anytls_reuse_padding_update_and_shutdown(self):
        received=[];connections=[];handlers=[]
        async def server(r,w):
            handlers.append(asyncio.current_task());connections.append(w)
            try:
                while True:
                    cmd,sid,size=struct.unpack('!BIH',await r.readexactly(7));data=await r.readexactly(size)
                    received.append((cmd,sid))
                    if cmd==4:
                        w.write(nodes.frame(10,0,b'v=2')+nodes.frame(6,0,b'stop=1\n0=30-30'))
                    if cmd==2:
                        w.write(nodes.frame(2,sid,b'reply')+nodes.frame(3,sid))
                    await w.drain()
            except (asyncio.IncompleteReadError,ConnectionError):pass
            finally:w.close();await w.wait_closed()
        listener=await asyncio.start_server(server,'127.0.0.1',0)
        n={'type':'anytls','server':'localhost','port':443,'password':'test'};pool=nodes.NodeTransport(n)
        r,w=await asyncio.open_connection('127.0.0.1',listener.sockets[0].getsockname()[1]);session=nodes.AnySession(pool,r,w);pool.sessions.add(session)
        try:
            for number in range(2):
                if number==0:rr,ww=await session.open('example.com',443)
                else:rr,ww=await pool.open('example.com',443)
                self.assertEqual(await rr.read(5),b'reply');self.assertEqual(await rr.read(5),b'');ww.close();await ww.wait_closed()
            self.assertEqual(len(connections),1);self.assertEqual([sid for cmd,sid in received if cmd==1],[1,2])
            self.assertEqual(pool.scheme,'stop=1\n0=30-30')
        finally:
            await pool.close();listener.close();await listener.wait_closed();await asyncio.gather(*handlers)
        self.assertFalse(pool.sessions);self.assertFalse(pool.idle)

    async def test_failed_node_does_not_fallback_or_leave_tasks(self):
        with tempfile.TemporaryDirectory() as td,patch.object(profiles,'ROOT',Path(td)):
            imported=subscriptions.import_source('test',text=json.dumps([SS]));row=subscriptions.view()[0]['nodes'][0]
            ident=subscriptions.select(imported['id'],row['id'])['id'];resident=Resident();state=await resident.start(ident)
            try:
                with patch.object(nodes.NodeTransport,'open',new_callable=AsyncMock,side_effect=OSError()),patch('relay.socket_open',new_callable=AsyncMock) as direct:
                    r,w=await asyncio.open_connection('127.0.0.1',state['port']);w.write(f'CONNECT example.com:443 HTTP/1.1\r\nProxy-Authorization: {resident.relay.local_auth}\r\n\r\n'.encode());await w.drain()
                    self.assertIn(b'502',await r.read());direct.assert_not_called();w.close();await w.wait_closed()
            finally:await resident.stop()
            with self.assertRaises(OSError):await asyncio.open_connection('127.0.0.1',state['port'])

if __name__=='__main__':unittest.main()
