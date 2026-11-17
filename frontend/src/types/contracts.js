/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean}} ReportSchedule */
/** @typedef {{id:number,week_start:string,epsilon:number,status:'pending'|'published'|'failed',noisy_total?:number,noise_scale?:number,error_radius_95?:number}} DpQuery */
/** @typedef {{fingerprint:string,label:string,clip_bound:number,total_epsilon:number,spent_epsilon:number,reserved_epsilon:number,remaining_epsilon:number}} PrivacyBudget */
/** @typedef {{id:number,consultant_id:number,dataset_id:number,label:string,max_epsilon:number,active:boolean,budget:?PrivacyBudget}} DpGrant */
export {};
