"""Private subscription catalog: bounded import, stable node IDs, explicit selection."""
from components import activate
activate()

import base64
import copy
import hashlib
import ipaddress
import json
import re
import ssl
import urllib.parse
import urllib.request

import profiles
import nodes

LIMIT=2*1024*1024
NODE_FIELDS={'name','type','server','port','password','cipher','plugin','plugin-opts','sni','servername','skip-cert-verify','alpn','client-fingerprint','dialer-proxy','network'}


def decode64(value):
    return base64.urlsafe_b64decode(value+'='*((-len(value))%4)).decode('utf-8-sig')


def uri_node(line):
    if not line.startswith('ss://'):raise ValueError('只支持 SS URI 或 Clash YAML/JSON 订阅')
    # SIP002 and legacy base64(method:password@server:port).
    raw=line[5:];body,_,label=raw.partition('#')
    if '@' not in body:body=decode64(body)
    u=urllib.parse.urlsplit('ss://'+body)
    auth=body.rsplit('@',1)[0]
    auth=urllib.parse.unquote(auth) if ':' in auth else decode64(auth)
    cipher,sep,password=auth.partition(':')
    if not sep:raise ValueError('SS URI 无效')
    n={'name':urllib.parse.unquote(label) or 'SS 节点','type':'ss','server':u.hostname,'port':u.port,'cipher':cipher,'password':password}
    plugin=urllib.parse.parse_qs(u.query).get('plugin',[])
    if plugin:
        values=plugin[0].split(';');n['plugin']=values[0];opts={}
        for part in values[1:]:
            key,_,value=part.partition('=');opts[{'obfs':'mode','obfs-host':'host'}.get(key,key)]=value
        n['plugin-opts']=opts
    return n


def parse(text):
    if not isinstance(text,str) or len(text.encode())>LIMIT:raise ValueError('订阅过大')
    text=text.lstrip('\ufeff').strip()
    if not text:raise ValueError('订阅为空')
    if not text.startswith(('ss://','{','[','proxies:','---')) and '\n' not in text:
        try:text=decode64(text.strip())
        except Exception:pass
    if text.startswith('ss://'):
        raw=[uri_node(line.strip()) for line in text.splitlines() if line.strip()]
    else:
        try:data=json.loads(text)
        except json.JSONDecodeError:
            try:import yaml
            except ImportError:raise ValueError('请先安装节点支持组件') from None
            # No aliases: prevent cyclic structures and expansion bombs.
            if any(isinstance(t,(yaml.tokens.AliasToken,yaml.tokens.AnchorToken)) for t in yaml.scan(text)):
                raise ValueError('订阅含 YAML 引用；请导出不带引用的节点列表')
            data=yaml.safe_load(text)
        raw=data.get('proxies') if isinstance(data,dict) else data
    if not isinstance(raw,list) or not 1<=len(raw)<=2000:raise ValueError('没有找到有效节点列表（最多 2000 个）')
    rows=[];seen=set()
    for item in raw:
        if not isinstance(item,dict):continue
        n={k:copy.deepcopy(v) for k,v in item.items() if k in NODE_FIELDS}
        n['name']=str(n.get('name') or '未命名节点')[:120]
        if re.search(r'^(?:Traffic Reset|Expire Date|官网[：:]|永久流量[：:]|剩余流量|\d+(?:\.\d+)?\s*[GMT]B?\s*\|)',n['name'],re.I):continue
        if not isinstance(n.get('type'),str):n['type']='unknown'
        # ID excludes passwords so provider credential rotation preserves references.
        ident=hashlib.sha256(json.dumps([n.get(k) for k in ('name','type','server','port','cipher','plugin','plugin-opts','sni','servername')],sort_keys=True).encode()).hexdigest()[:20]
        if ident in seen:continue
        seen.add(ident)
        try:nodes.validate(n);reason=''
        except (ValueError,TypeError,KeyError):
            try:nodes.validate(n)
            except ValueError as e:reason=str(e)
            except Exception:reason='节点字段格式无效'
        rows.append({'id':ident,'node':n,'reason':reason})
    if not rows:raise ValueError('没有找到节点')
    return rows


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*_):raise ValueError('订阅发生跳转，请使用服务商的最终 HTTPS 订阅地址')


def fetch(url):
    u=urllib.parse.urlsplit(url)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.fragment or len(url)>8192:
        raise ValueError('请输入完整 HTTPS 订阅地址')
    try:addr=ipaddress.ip_address(u.hostname)
    except ValueError:addr=None
    if (addr and not addr.is_global) or u.hostname=='localhost' or u.hostname.endswith(('.local','.localhost')):
        raise ValueError('不支持内网订阅地址')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    req=urllib.request.Request(url,headers={'User-Agent':'Clash/1.18 Python-Connection','Accept':'application/yaml, application/json, text/plain'})
    try:
        with opener.open(req,timeout=20) as r:
            body=r.read(LIMIT+1)
        if len(body)>LIMIT:raise ValueError('订阅过大')
        return body.decode('utf-8-sig')
    except Exception:raise ValueError('订阅获取失败；检查地址、有效期及网络，也可以粘贴配置内容') from None


def store_path():return profiles.ROOT/'.subscriptions.json'

def catalog():
    p=store_path()
    return json.loads(p.read_text()) if p.exists() else {'version':1,'sources':{}}

def view():
    result=[]
    for ident,s in catalog()['sources'].items():
        result.append({'id':ident,'name':s['name'],'can_update':bool(s.get('url')),'nodes':[{'id':r['id'],'name':r['node']['name'],'type':r['node']['type'],'supported':not r['reason'],'reason':r['reason']} for r in s['nodes']]})
    return result


def import_source(name,text='',url='',ident=None):
    c=catalog()
    if ident:
        if ident not in c['sources']:raise ValueError('订阅不存在')
        old=c['sources'][ident];name=old['name'];url=old.get('url','')
        if not url:raise ValueError('粘贴导入的订阅请重新导入内容')
    else:ident='sub-'+__import__('secrets').token_hex(6)
    if not isinstance(name,str) or not name.strip() or len(name)>80:raise ValueError('请填写订阅名称（最多 80 字）')
    rows=parse(fetch(url) if url else text)
    if ident in c['sources'] and not any(not r['reason'] for r in rows):
        raise ValueError('更新后的订阅没有支持的节点；保留原节点，请检查订阅类型')
    c['sources'][ident]={'name':name.strip(),'url':url,'nodes':rows}
    profiles.atomic_json(store_path(),c)
    return {'id':ident,'count':len(rows),'supported':sum(not r['reason'] for r in rows)}


def node(source,node_id):
    s=catalog()['sources'].get(source)
    if not s:raise ValueError('订阅不存在')
    row=next((r for r in s['nodes'] if r['id']==node_id),None)
    if not row:raise ValueError('订阅中已没有此节点，请重新选择')
    if row['reason']:raise ValueError(row['reason'])
    return row['node']


def select(source,node_id):
    n=node(source,node_id)
    ident='node-'+hashlib.sha256((source+node_id).encode()).hexdigest()[:16]
    if ident in profiles.list_profiles():
        c,creds,_=profiles.load(ident);rev=profiles.revision(ident)
    else:
        c={'name':n['name'],'connection_type':'node','default':'proxy','direct':['localhost','127.0.0.0/8','::1/128','10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'],'proxy':[],'block':[],'interface':'','company_dns':{'domains':[],'servers':[]},'china_routing':{'enabled':False}}
        creds={};rev=None
    c['subscription_ref']={'source':source,'node':node_id}
    creds={'node':n}
    profiles.save(ident,c,creds,rev)
    return {'id':ident,'name':c['name']}
