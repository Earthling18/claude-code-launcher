"""Native WebView2 regression on a disposable GitHub Windows runner only.
Uses tauri-driver's standard WebDriver HTTP API; does not touch local user data.
"""
import base64
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

if os.name != 'nt' or os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Run only on a disposable Windows GitHub Actions runner')

out=Path('qa-artifacts');out.mkdir(exist_ok=True)
config_dir=Path(os.environ['APPDATA'])/'CCLauncher'
if (config_dir/'config.json').exists():
    raise SystemExit('Refusing to replace an existing user configuration')
config_dir.mkdir(parents=True,exist_ok=True)
config={'mode':'codex','proxy':'','model':'','base_url':'','token':'','skip_permissions':False,'codex_api_key':'','custom_cli':'codex'}
projects=[{'id':f'qa-{i}','name':f'UI Test {i+1:02d}','working_directory':str(Path.cwd()),'config':config,'is_default':i==0,'created_at':0,'updated_at':0,'is_pinned':False,'sort_order':i} for i in range(48)]
(config_dir/'config.json').write_text(json.dumps({'version':2,'projects':projects,'has_seen_onboarding':True}),encoding='utf-8')
(config_dir/'presets.json').write_text(json.dumps({'proxies':[],'models':[],'last_used_config':None}),encoding='utf-8')
log=(out/'tauri-driver.log').open('w',encoding='utf-8')
proc=subprocess.Popen(['tauri-driver','--native-driver',str(Path('msedgedriver.exe').resolve())],stdout=log,stderr=log)
session=None

def request(method,path,data=None):
    raw=json.dumps(data).encode() if data is not None else None
    req=urllib.request.Request('http://127.0.0.1:4444'+path,data=raw,method=method,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=90) as response:value=json.load(response)['value']
    if isinstance(value,dict) and 'error' in value:raise RuntimeError(value)
    return value

def call(method,path,data=None):return request(method,'/session/'+session+path,data)
def js(script,*args):return call('POST','/execute/sync',{'script':script,'args':list(args)})
def wait(check,seconds=35):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        try:
            result=check()
            if result:return result
        except Exception:pass
        time.sleep(.1)
    raise AssertionError('UI condition timed out')
def element(value,using='css selector'):
    return call('POST','/element',{'using':using,'value':value})['element-6066-11e4-a52e-4f735466cecf']
def click(value,using='css selector'):
    el=element(value,using);call('POST',f'/element/{el}/click',{})
def button(text):click(f'//button[normalize-space()="{text}"]','xpath')

try:
    wait(lambda:request('GET','/status'))
    result=request('POST','/session',{'capabilities':{'alwaysMatch':{'browserName':'wry','tauri:options':{'application':str(Path('src-tauri/target/release/cc-launcher-tauri.exe').resolve())}}}})
    session=result['sessionId']
    js("localStorage.setItem('local_deps_ok','1'); location.reload();")
    wait(lambda:js("return document.querySelectorAll('[data-project-id]').length===48"))
    results=[]
    for action in ['返回','取消','保存修改','返回','保存修改']:
        js("document.querySelector('[data-project-id=qa-26]').scrollIntoView({block:'center'});")
        time.sleep(.2)
        expected=js("return document.querySelector('[data-testid=project-list-scroll]').scrollTop")
        assert expected>500
        js("""
        window.navProof={expected:arguments[0],first:null,blank:0,wrong:0,frames:0,armed:false,done:false};
        const p=window.navProof;
        function sample(){if(p.done)return;
          const el=document.querySelector('[data-testid=project-list-scroll]');
          if(!el)p.armed=true;
          if(p.armed&&el){
            if(p.first===null)p.first=el.scrollTop;
            p.frames++;
            if(!el.querySelector('[data-project-id]'))p.blank++;
            if(Math.abs(el.scrollTop-p.expected)>1)p.wrong++;
          }
          requestAnimationFrame(sample);
        }requestAnimationFrame(sample);
        """,expected)
        click('[data-project-id=qa-26] .project-card')
        wait(lambda:js("return [...document.querySelectorAll('h2')].some(x=>x.textContent==='编辑项目')"))
        if action=='保存修改':
            field=element('input[type=text]')
            call('POST',f'/element/{field}/clear',{})
            call('POST',f'/element/{field}/value',{'text':'UI Test 27 saved'})
        button(action)
        wait(lambda:js("return window.navProof.frames>=60"))
        result=js('window.navProof.done=true;return window.navProof;')
        assert result['blank']==0 and result['wrong']==0,result
        result['action']=action;results.append(result)
    stored=json.loads((config_dir/'config.json').read_text(encoding='utf-8'))
    assert next(p for p in stored['projects'] if p['id']=='qa-26')['name']=='UI Test 27 saved'
    image=call('GET','/screenshot');(out/'windows-native-navigation.png').write_bytes(base64.b64decode(image))
    (out/'windows-native-navigation.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print('WINDOWS_NATIVE_NAVIGATION_OK',json.dumps(results,ensure_ascii=False))
finally:
    if session:
        try:call('DELETE','')
        except Exception:pass
    proc.terminate()
    try:proc.wait(timeout=5)
    except subprocess.TimeoutExpired:proc.kill();proc.wait()
    log.close()
