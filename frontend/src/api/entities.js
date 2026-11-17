import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
export const dp={
 grants:()=>api('/dp/grants'),grant:data=>api('/dp/grants',{method:'POST',body:JSON.stringify(data)}),revoke:id=>api('/dp/grants/'+id+'/revoke',{method:'POST'}),
 budgets:()=>api('/dp/budgets'),setBudget:data=>api('/dp/budgets',{method:'PUT',body:JSON.stringify(data)}),
 consultants:()=>api('/dp/consultants'),
 queries:status=>api('/dp/queries'+(status?'?status='+status:'')),query:data=>api('/dp/queries',{method:'POST',body:JSON.stringify(data)}),retry:id=>api('/dp/queries/'+id+'/retry',{method:'POST'}),
 ledger:()=>api('/dp/ledger')};
