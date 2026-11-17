import {dp,datasets} from '../api/entities.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {esc,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {DpStatus,LedgerAction} from '../constants/enums.js';
let requestKey=crypto.randomUUID(),filter='';
const weekEnd=w=>{const d=new Date(w+'T00:00:00');d.setDate(d.getDate()+6);return d.toISOString().slice(0,10);};
const statusOf=q=>'<span class="status '+(q.status==='failed'?'failed':'')+'">'+DpStatus[q.status]+'</span>';
const resultOf=q=>q.status==='published'?'<strong>'+q.noisy_total+'</strong> 份<small>（噪声尺度 b='+q.noise_scale+'，95% 误差 ≤ ±'+q.error_radius_95+'）</small>':(q.status==='failed'?'<small>'+esc(q.error||'计算失败，预扣已退还')+'</small>':'<small>等待计算</small>');
function queryRows(list,reveal){
 return list.map(q=>'<tr><td>#'+q.id+'</td><td>'+esc(q.week_start)+' ~ '+weekEnd(q.week_start)+'</td><td>'+q.epsilon+'</td><td>'+statusOf(q)+'</td><td>'+resultOf(q)+'</td>'+(reveal?'<td>'+(q.exact_total??'—')+'</td>':'')+'<td>'+date(q.created_at)+'</td><td>'+(q.status!=='published'?'<button class="text-button" data-retry="'+q.id+'">恢复/重试</button>':'')+'</td></tr>').join('');
}
function queryTable(list,reveal){
 const shown=filter?list.filter(q=>q.status===filter):list;
 const counts=s=>list.filter(q=>q.status===s).length;
 return '<div class="section-title"><h2>查询核对</h2><span><button class="text-button" data-filter="">全部 '+list.length+'</button> · <button class="text-button" data-filter="pending">待处理 '+counts('pending')+'</button> · <button class="text-button" data-filter="published">已发布 '+counts('published')+'</button> · <button class="text-button" data-filter="failed">失败 '+counts('failed')+'</button></span></div><div class="table-wrap"><table><thead><tr><th>编号</th><th>自然周</th><th>ε</th><th>状态</th><th>加噪结果</th>'+(reveal?'<th>精确值（仅负责人）</th>':'')+'<th>提交时间</th><th></th></tr></thead><tbody>'+(queryRows(shown,reveal)||'<tr><td colspan="'+(reveal?8:7)+'">暂无查询</td></tr>')+'</tbody></table></div>';
}
async function consultantView(){
 const [grants,queries]=await Promise.all([dp.grants(),dp.queries()]);
 const last=queries.find(q=>q.status==='published');
 return heading('01 / PRIVACY QUERIES','自然周加噪总量查询','按自然周查询获授权批次的加噪领餐总量。每日份数先按上限截断，再以拉普拉斯机制加噪；噪声尺度与 95% 误差半径随结果列明。')
 +'<div class="dataset-grid"><section class="panel"><div class="section-title"><h2>我的授权</h2><span>'+grants.length+' 项有效</span></div>'
 +(grants.map(g=>'<article class="batch-item"><strong>'+esc(g.label)+'</strong><span>单次 ε 上限 '+g.max_epsilon+' · 截断上限 '+(g.budget?g.budget.clip_bound:'—')+' 份/天</span><small>剩余预算 ε '+(g.budget?g.budget.remaining_epsilon:'—')+' / 总 '+ (g.budget?g.budget.total_epsilon:'—')+'</small></article>').join('')||'<p class="empty">尚无授权，请联系负责人。</p>')
 +'<div class="section-title"><h2>发起查询</h2></div><form id="dp-form"><label>数据批次<select name="dataset_id" id="dp-dataset">'+grants.map(g=>'<option value="'+g.dataset_id+'" data-max="'+g.max_epsilon+'">'+esc(g.label)+'</option>').join('')+'</select></label><label>自然周周一<input name="week_start" type="date" required></label><label>本次 epsilon<input name="epsilon" type="number" step="0.05" min="0.05" value="0.5" required></label><label>请求编号（重试同一请求不重复扣费）<input name="request_key" value="'+requestKey+'" readonly></label><button type="submit" class="primary" '+(grants.length?'':'disabled')+'>预扣并查询 ↗</button><p class="hint">按原请求重试返回同一结果；同一编号更换条件将被拒绝。结果可查时才确认花费，公开前失败自动退还。</p></form></section>'
 +'<section class="panel"><div class="section-title"><h2>最近发布结果</h2></div>'+(last?'<div class="metrics"><div><span>自然周</span><strong>'+esc(last.week_start)+'</strong></div><div><span>加噪周总量</span><strong>'+last.noisy_total+'<small>份</small></strong></div><div><span>噪声尺度 b</span><strong>'+last.noise_scale+'</strong></div><div><span>95% 误差半径</span><strong>±'+last.error_radius_95+'<small>份</small></strong></div></div><p class="hint">拉普拉斯机制：每日截断至 '+last.clip_bound+' 份，敏感度 '+last.clip_bound+'，b = 截断上限 / ε = '+last.noise_scale+'；本次消耗 ε '+last.epsilon+'。</p>':'<p class="empty">还没有已发布的查询结果。</p>')
 +queryTable(queries,false)+'</section></div>';
}
async function adminView(){
 const [budgets,grants,queries,ledger,consultants,allDatasets]=await Promise.all([dp.budgets(),dp.grants(),dp.queries(),dp.ledger(),dp.consultants(),datasets.list()]);
 return heading('06 / PRIVACY BUDGET','隐私预算与顾问授权','负责人设定单次与总隐私预算、授予顾问查询权限，并核对待处理、已发布、失败查询与预算去向。')
 +'<div class="report-grid"><section class="panel"><div class="section-title"><h2>设定数据预算</h2></div><form id="budget-form"><label>数据批次<select name="dataset_id">'+allDatasets.map(d=>'<option value="'+d.id+'">'+esc(d.name)+'</option>').join('')+'</select></label><div class="parameter-grid"><label>总隐私预算 ε<input name="total_epsilon" type="number" step="0.5" min="0" value="5" required></label><label>每日截断上限（份）<input name="clip_bound" type="number" step="10" min="1" value="600" required></label></div><button type="submit" class="primary">保存预算</button><p class="hint">相同数据换名或乱序导入共用同一余额；已有查询后截断上限不可变更。</p></form>'
 +'<div class="section-title"><h2>授予顾问权限</h2></div><form id="grant-form"><label>顾问<select name="consultant_id">'+consultants.map(c=>'<option value="'+c.id+'">'+esc(c.name)+'（'+esc(c.email)+'）</option>').join('')+'</select></label><label>数据批次<select name="dataset_id">'+allDatasets.map(d=>'<option value="'+d.id+'">'+esc(d.name)+'</option>').join('')+'</select></label><label>单次 epsilon 上限<input name="max_epsilon" type="number" step="0.1" min="0.05" value="0.5" required></label><button type="submit" class="primary" '+(consultants.length?'':'disabled')+'>授权</button></form>'
 +'<div class="section-title"><h2>有效授权</h2><span>'+grants.filter(g=>g.active).length+' 项</span></div><div class="schedule-list">'+grants.map(g=>'<article><div><strong>'+esc(g.label)+'</strong><p>顾问 #'+g.consultant_id+' · 单次 ε 上限 '+g.max_epsilon+' · '+(g.active?'有效':'已收回')+'</p><small>指纹 '+esc(g.fingerprint.slice(0,18))+'… · '+date(g.created_at)+'</small></div>'+(g.active?'<button class="button small" data-revoke="'+g.id+'">收回</button>':'')+'</article>').join('')+'</div></section>'
 +'<section><div class="section-title"><h2>预算余额</h2><span>'+budgets.length+' 个数据指纹</span></div><div class="table-wrap"><table><thead><tr><th>数据</th><th>截断上限</th><th>总预算 ε</th><th>已花费</th><th>已预扣</th><th>剩余</th></tr></thead><tbody>'+budgets.map(b=>'<tr><td>'+esc(b.label)+'<br><small>'+esc(b.fingerprint.slice(0,16))+'…</small></td><td>'+b.clip_bound+'</td><td>'+b.total_epsilon+'</td><td>'+b.spent_epsilon+'</td><td>'+b.reserved_epsilon+'</td><td><strong>'+b.remaining_epsilon+'</strong></td></tr>').join('')+'</tbody></table></div>'
 +queryTable(queries,true)
 +'<div class="section-title"><h2>预算去向</h2><span>逐笔台账</span></div><div class="table-wrap"><table><thead><tr><th>时间</th><th>动作</th><th>金额 ε</th><th>已花费</th><th>已预扣</th><th>操作者</th><th>关联查询</th><th>备注</th></tr></thead><tbody>'+(ledger.map(e=>'<tr><td>'+date(e.at)+'</td><td>'+(LedgerAction[e.action]||e.action)+'</td><td>'+e.amount+'</td><td>'+e.spent_after+'</td><td>'+e.reserved_after+'</td><td>'+esc(e.actor)+'</td><td>'+(e.query_id?'#'+e.query_id:'—')+'</td><td>'+esc(e.note)+'</td></tr>').join('')||'<tr><td colspan="8">暂无台账记录</td></tr>')+'</tbody></table></div></section></div>';
}
export async function privacyPage(){return session.user.role==='consultant'?consultantView():adminView();}
export function bindPrivacy(refresh){
 document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{filter=b.dataset.filter;refresh();});
 document.querySelectorAll('[data-retry]').forEach(b=>b.onclick=async()=>{try{const q=await dp.retry(b.dataset.retry);notify(q.status==='published'?'查询已恢复并发布':'恢复失败：'+(q.error||'请稍后再试'),q.status!=='published');await refresh();}catch(e){notify(e.message,true);}});
 const dpForm=document.querySelector('#dp-form');
 if(dpForm){
  dpForm.querySelectorAll('select,input').forEach(el=>el.addEventListener('change',()=>{if(el.name!=='request_key'){requestKey=crypto.randomUUID();dpForm.querySelector('[name=request_key]').value=requestKey;}}));
  submit(dpForm,async f=>{const q=await dp.query({dataset_id:Number(f.get('dataset_id')),week_start:f.get('week_start'),epsilon:Number(f.get('epsilon')),request_key:f.get('request_key')});notify(q.status==='published'?'查询已发布，确认花费 ε '+q.epsilon:(q.status==='failed'?'查询失败，预扣已退还':'查询已受理'),q.status==='failed');await refresh();});
 }
 const budgetForm=document.querySelector('#budget-form');
 if(budgetForm)submit(budgetForm,async f=>{await dp.setBudget({dataset_id:Number(f.get('dataset_id')),total_epsilon:Number(f.get('total_epsilon')),clip_bound:Number(f.get('clip_bound'))});notify('预算已保存');await refresh();});
 const grantForm=document.querySelector('#grant-form');
 if(grantForm)submit(grantForm,async f=>{await dp.grant({consultant_id:Number(f.get('consultant_id')),dataset_id:Number(f.get('dataset_id')),max_epsilon:Number(f.get('max_epsilon'))});notify('授权已保存');await refresh();});
 document.querySelectorAll('[data-revoke]').forEach(b=>b.onclick=async()=>{try{await dp.revoke(b.dataset.revoke);notify('授权已收回');await refresh();}catch(e){notify(e.message,true);}});
}
