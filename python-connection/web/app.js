const $ = id => document.getElementById(id);
const fragment = new URLSearchParams(location.hash.slice(1));
const token = fragment.get('token') || sessionStorage.getItem('connection-token') || '';
if (token) sessionStorage.setItem('connection-token', token);
let selected = fragment.get('profile') || sessionStorage.getItem('connection-profile') || '', revision = null, config = {}, dirty = false, busy = false;
let sourceMode='cloud', sources=[], sourceId='', nodeId='', allProfiles=[];
history.replaceState(null, '', location.pathname);
const fields = ['name','server_ip','server_port','server_name','interface','direct','proxy','block','default','company_domains','company_servers','china_enabled','username','password','routing_mode'];
function routingHint() {
  $('routing_hint').textContent=$('routing_mode').value==='proxy_all'?'进入本工具的请求全部交给节点，阻止规则仍生效。直连及公司 DNS 规则暂不使用，配置保留；访问内网请切回规则分流。':'按下方规则决定直连、代理或阻止；不修改其他应用的网络。';
}
function notice(message, error=false) { $('notice').textContent=message; $('notice').className=error?'error':''; }
async function api(path, body) {
  const response = await fetch('/api/'+path, {method:body===undefined?'GET':'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});
  const data=await response.json(); if(!response.ok) throw new Error(data.error||'操作未完成'); return data;
}
function lines(id) { return $(id).value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean); }
function fill(view) {
  selected=view.id||'';if(selected)sessionStorage.setItem('connection-profile',selected);revision=view.revision||null;config=view.config||{};
  for(const k of ['name','server_ip','server_port','server_name','interface']) $(k).value=config[k]??'';
  for(const k of ['direct','proxy','block']) $(k).value=(config[k]||[]).join('\n');
  $('default').value=config.default||'proxy';
  $('routing_mode').value=config.routing_mode||'rules';routingHint();
  $('company_domains').value=(config.company_dns?.domains||[]).join('\n');
  $('company_servers').value=(config.company_dns?.servers||[]).join('\n');
  const available=!!(config.china_routing?.domains_file&&config.china_routing?.ip_file);
  $('china_enabled').disabled=!available;$('china_enabled').checked=!!config.china_routing?.enabled;
  $('china_hint').textContent=available?'使用此方案已有的规则文件。':'此方案未导入国内规则文件；不会自动下载。';
  $('username').value='';$('password').value='';$('endpoint').open=!selected;
  $('edit_connection').open=!selected;$('endpoint').hidden=config.connection_type==='node';
  dirty=false;$('save_hint').textContent='修改只影响新启动的会话。';
}
async function load(id) { fill(await api('profile?id='+encodeURIComponent(id)));$('profiles').value=id; }
function bytes(n) { return n<1024?n+' B':n<1048576?(n/1024).toFixed(1)+' KB':(n/1048576).toFixed(1)+' MB'; }
async function refresh() {
  const data=await api('state');
  allProfiles=data.profiles;
  const cloudProfiles=data.profiles.filter(p=>p.type!=='node');
  const ids=data.profiles.map(p=>p.id);
  if(!selected && !dirty && sourceMode==='cloud' && cloudProfiles.length && !revision) selected=cloudProfiles[0].id;
  const old=$('profiles').value;
  $('profiles').replaceChildren(...cloudProfiles.map(p=>{const o=document.createElement('option');o.value=p.id;o.textContent=p.name;return o;}));
  if(!selected){const o=document.createElement('option');o.value='';o.textContent='新方案（未保存）';$('profiles').prepend(o);}
  $('profiles').value=!selected?'':ids.includes(selected)?selected:old;
  const active=data.active, running=active.state!=='stopped';
  const labels={stopped:'已停止',waiting:'本地待命',connected:'上游已连接',transferring:'正在传输'};
  $('state').textContent=labels[active.state]||'未知';
  $('connections').textContent=active.active_connections||0;
  $('upload').textContent=bytes(active.upload_bytes||0);$('download').textContent=bytes(active.download_bytes||0);
  $('last').textContent=active.last_activity?new Date(active.last_activity*1000).toLocaleTimeString():'—';
  const name=data.profiles.find(p=>p.id===active.profile)?.name||active.profile;
  $('resident_details').textContent=running?`${name} · 127.0.0.1:${active.port} · 等待连接 ${active.pending_connections} · 使用启动时的配置`:'没有常驻代理。';
  $('last_error').textContent=active.last_error?'最近连接错误：'+active.last_error:'';
  const desktop=data.desktop||{}, desktopRunning=desktop.state==='running';
  $('desktop_state').textContent=desktopRunning?(desktop.mode==='isolated'?'独立测试窗口运行中':'Codex 运行中'):'未打开';
  $('desktop_info').textContent=desktop.available?'Mac 客户端 · 代理链路仍需在应用内验收。':(desktop.message||'客户端入口不可用。');
  const dc=desktop.connection||{};
  $('desktop_metrics').textContent=desktopRunning?`${data.profiles.find(p=>p.id===desktop.profile)?.name||desktop.profile} · 本地代理 127.0.0.1:${dc.port} · 活动连接 ${dc.active_connections||0}`:'';
  $('desktop_open').disabled=!desktop.available||desktopRunning||!selected||busy;
  $('desktop_close').disabled=!desktopRunning||busy;
  $('desktop_password').disabled=!desktopRunning||busy;
  $('desktop_mode').disabled=desktopRunning||busy;
  $('start').disabled=running||!selected||busy;$('stop').disabled=!running||busy;
  $('test').disabled=!selected||data.diagnostic.state==='running'||busy;
  $('cancel_test').disabled=data.diagnostic.state!=='running';
  const d=data.diagnostic.profile===selected?data.diagnostic:(data.diagnostics?.[selected]||{state:'idle'});
  if(d.state==='running') $('diagnostic').textContent='正在检测入口、认证与目标响应…';
  else if(d.state==='response') $('diagnostic').textContent=`收到 HTTP ${d.http_status} · ${d.elapsed_ms} ms。${d.http_status==='403'?'目标拒绝访问，需要进一步检查。':'网络响应已收到。'}尚未验证模型调用。`;
  else if(d.state==='failed') $('diagnostic').textContent='检测失败：'+(d.error||'请求超时或目标不可达')+'。未自动直连。';
  else if(d.state==='cancelled') $('diagnostic').textContent='检测已取消。';
  else $('diagnostic').textContent='尚未检测当前节点。';
  $('node_result').textContent=d.profile===selected?$('diagnostic').textContent:'尚未检测当前节点。';
  $('node_test').disabled=!selected||sourceMode!=='subscription'||config.connection_type!=='node'||d.state==='running'||busy;
  $('node_cancel').disabled=d.state!=='running';
  $('install_components').disabled=data.components==='installing'||busy;
  $('update_subscription').disabled=busy||!sources.find(s=>s.id===sourceId)?.can_update;
  $('china_enabled').disabled=!(config.china_routing?.domains_file&&config.china_routing?.ip_file);
  $('components_panel').hidden=data.components==='ready';
  $('components_hint').textContent=data.components==='installing'?'正在安装本目录的 Python 库，请稍候…':data.components==='failed'?'组件安装失败，请检查网络和 pip 后重试。':'第一次导入 YAML / 使用 SS 需要安装两个 Python 库。仅写入工具目录，不安装代理 EXE。';
  return data;
}
async function action(fn) { if(busy)return;busy=true;const controls=[...document.querySelectorAll('button,input,select,textarea')].map(el=>[el,el.disabled]);controls.forEach(([el])=>el.disabled=true);try{await fn();}catch(e){notice(e.message,true);}finally{controls.forEach(([el,was])=>el.disabled=was);busy=false;await refresh().catch(()=>{});} }
fields.forEach(id=>$(id).addEventListener('input',()=>{dirty=true;$('save_hint').textContent='有未保存修改；检测和启动使用已保存的方案。';}));
$('routing_mode').addEventListener('change',routingHint);
async function chooseSource(mode){
  if(dirty&&!confirm('放弃未保存的修改？'))return;
  sourceMode=mode;dirty=false;
  $('source_cloud').setAttribute('aria-pressed',String(mode==='cloud'));$('source_subscription').setAttribute('aria-pressed',String(mode==='subscription'));
  $('cloud_flow').hidden=mode!=='cloud';$('subscription_panel').hidden=mode!=='subscription';
  if(mode==='subscription'){await loadSubscriptions();if(sourceId&&nodeId)await selectNode();else {selected='';config={};}}
  else {const p=allProfiles.find(p=>p.type!=='node');if(p)await load(p.id);else {selected='';config={};}}
  await refresh();
}
$('source_cloud').onclick=()=>action(()=>chooseSource('cloud'));
$('source_subscription').onclick=()=>action(()=>chooseSource('subscription'));
function renderNodes(){
  const source=sources.find(s=>s.id===sourceId),rows=source?.nodes||[],query=$('node_filter').value.trim().toLowerCase();
  const normalize=s=>s.toLowerCase().replaceAll('香港','hong kong').replaceAll('日本','japan').replaceAll('新加坡','singapore').replaceAll('美国','usa');
  const visible=rows.filter(n=>!query||normalize(n.name).includes(normalize(query))),matchCount=visible.length;
  if(!rows.some(n=>n.id===nodeId&&n.supported))nodeId=rows.find(n=>n.supported)?.id||'';
  const current=rows.find(n=>n.id===nodeId);
  if(current&&!visible.some(n=>n.id===nodeId))visible.unshift(current);
  $('nodes').replaceChildren(...visible.map(n=>{const o=document.createElement('option');o.value=n.id;o.disabled=!n.supported;o.textContent=(query&&!normalize(n.name).includes(normalize(query))?'[当前] ':'')+n.name+' · '+n.type.toUpperCase()+(n.supported?'':' · '+n.reason);return o;}));
  $('nodes').value=nodeId;
  $('node_hint').textContent=rows.length?`${rows.filter(n=>n.supported).length} / ${rows.length} 个节点协议兼容。${query?'筛选显示 '+matchCount+' 个。':''}尚未检测的节点不代表可连接。`:'此订阅没有节点。';
  $('update_subscription').disabled=!source?.can_update;
}
async function loadSubscriptions(){
  sources=(await api('subscriptions')).sources;
  if(!sources.some(s=>s.id===sourceId))sourceId=sources[0]?.id||'';
  $('subscriptions').replaceChildren(...sources.map(s=>{const o=document.createElement('option');o.value=s.id;o.textContent=s.name;return o;}));
  $('subscriptions').value=sourceId;$('subscription_import').open=!sources.length;renderNodes();
}
async function selectNode(){
  if(!sourceId||!nodeId)return;
  const p=await api('subscriptions/select',{source:sourceId,node:nodeId});await load(p.id);
  notice('已选择节点。只影响之后启动的会话，现有窗口不切换。');
}
$('node_filter').oninput=()=>{renderNodes();};
$('subscriptions').onchange=()=>action(async()=>{sourceId=$('subscriptions').value;nodeId='';$('node_filter').value='';renderNodes();selected='';if(nodeId)await selectNode();});
$('nodes').onchange=()=>action(async()=>{nodeId=$('nodes').value;await selectNode();});
$('add_subscription').onclick=()=>{$('subscription_import').open=true;$('subscription_name').focus();};
$('install_components').onclick=()=>action(async()=>{await api('components/install',{});notice('正在安装可选 Python 库，不修改系统 Python。');});
$('import_subscription').onclick=()=>action(async()=>{
  notice('正在导入订阅，请稍候…');
  const result=await api('subscriptions/import',{name:$('subscription_name').value.trim(),url:$('subscription_url').value.trim(),text:$('subscription_text').value});
  $('subscription_url').value='';$('subscription_text').value='';sourceId=result.id;nodeId='';await loadSubscriptions();if(nodeId)await selectNode();
  notice(`已导入 ${result.count} 个节点，其中 ${result.supported} 个协议兼容。选择节点后点击检测。`);
});
$('update_subscription').onclick=()=>action(async()=>{notice('正在获取订阅更新，请稍候…');await api('subscriptions/import',{id:sourceId});await loadSubscriptions();if(nodeId)await selectNode();notice('订阅已更新；现有会话保持原节点。');});
$('node_test').onclick=()=>action(async()=>{await api('diagnose',{id:selected});});
$('node_cancel').onclick=()=>action(async()=>{await api('cancel-diagnostic',{});});
$('edit').onclick=()=>{document.querySelector('.advanced').open=true;$('edit_connection').open=true;$('edit_connection').scrollIntoView({behavior:'smooth',block:'start'});};
$('desktop_mode').onchange=()=>{const isolated=$('desktop_mode').value==='isolated';$('history_hint').textContent=isolated?'独立排错窗口，不显示原来的聊天记录；原账号与记录不变。':'沿用原来的账号、项目和聊天记录。若 Codex 正在运行，请先从菜单退出，再从这里重新打开。';$('desktop_open').textContent=isolated?'打开独立测试窗口':'打开 Codex · 保留记录';};
$('profiles').onchange=()=>action(async()=>{if(dirty&&!confirm('放弃未保存的修改？')){$('profiles').value=selected;return;}await load($('profiles').value);notice('已载入方案。');});
$('reload').onclick=()=>action(async()=>{if(dirty&&!confirm('放弃未保存的修改？'))return;if(selected)await load(selected);});
$('new').onclick=()=>action(async()=>{if(dirty&&!confirm('放弃未保存的修改？'))return;fill({config:{name:'新的云节点',server_port:443,default:'proxy',direct:['localhost','127.0.0.0/8','::1/128','10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'],company_dns:{domains:[],servers:[]},china_routing:{enabled:false}}});dirty=true;document.querySelector('.advanced').open=true;$('edit_connection').scrollIntoView({behavior:'smooth',block:'start'});notice('填写连接设置后保存，原方案不会修改。');});
$('save').onclick=()=>action(async()=>{
  const edited={...config};for(const k of ['name','interface'])edited[k]=$(k).value.trim();
  if(config.connection_type!=='node'){for(const k of ['server_ip','server_name'])edited[k]=$(k).value.trim();edited.server_port=Number($('server_port').value);}
  edited.default=$('default').value;
  edited.routing_mode=$('routing_mode').value;
  for(const k of ['direct','proxy','block'])edited[k]=lines(k);
  edited.company_dns={domains:lines('company_domains'),servers:lines('company_servers')};
  edited.china_routing={...config.china_routing,enabled:$('china_enabled').checked};
  const payload={id:selected,revision,config:edited};
  if(config.connection_type!=='node'&&($('username').value||$('password').value||!selected))payload.credentials={username:$('username').value,password:$('password').value};
  fill(await api('save',payload));notice('已保存。新启动的会话生效；已有常驻连接需要停止后重新启动。');
});
$('start').onclick=()=>action(async()=>{await api('start',{id:selected});notice('常驻代理已在本地待命；应用接入尚未配置，不代表客户端已经在使用。');});
$('stop').onclick=()=>action(async()=>{if(!confirm('停止会断开使用此常驻代理的请求。继续？'))return;await api('stop',{});notice('常驻代理已停止。独立 CLI 会话不受影响。');});
$('test').onclick=()=>action(async()=>{await api('diagnose',{id:selected});});
$('cancel_test').onclick=()=>action(async()=>{await api('cancel-diagnostic',{});});
$('desktop_open').onclick=()=>action(async()=>{if(dirty)throw new Error('请先保存方案，再打开客户端。');const mode=$('desktop_mode').value;await api('desktop/start',{id:selected,mode});notice(mode==='existing'?'已按原数据目录打开 Codex，请检查原记录并发送一条消息验收。':'已打开独立测试窗口，不显示原记录。');});
$('desktop_close').onclick=()=>action(async()=>{if(!confirm('退出本次由这里打开的 Codex，会中断其中的请求。已保存的记录保留。继续？'))return;await api('desktop/stop',{});notice('本次客户端与对应代理已退出，已保存的记录保留。');});
$('desktop_password').onclick=()=>action(async()=>{const credential=await api('desktop/credential',{});await navigator.clipboard.writeText(credential.password);notice(`已复制本次本地密码，仅用于 127.0.0.1:${credential.port} 的代理认证，用户名 local。`);});
$('quit').onclick=()=>action(async()=>{await api('quit',{});clearInterval(poll);notice('管理已退出，可以关闭此页面。');});
let poll;
(async()=>{try{const state=await refresh();if(state.profiles.some(p=>p.id===selected))await load(selected);else if(state.profiles.length)await load(state.profiles[0].id);else $('new').click();if(config.connection_type==='node'){sourceId=config.subscription_ref?.source||'';nodeId=config.subscription_ref?.node||'';await chooseSource('subscription');}poll=setInterval(()=>{if(!busy)refresh().catch(()=>notice('管理连接已关闭，请从启动器重新打开。',true));},2000);}catch(e){notice(e.message,true);}})();
