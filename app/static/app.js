'use strict';
const $=s=>document.querySelector(s);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let config, templates=[], current=null, validation=null, selected=null, leftTab='outline', rightTab='edit', history=[];
const modal=$('#modal');
let toastTimer;
function toast(message,error=false){const el=$('#toast');el.textContent=message;el.className='show'+(error?' error':'');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.className='',6000);}
async function busy(fn,label='처리 중입니다…'){if(!$('#busy').hidden)return;$('#busyText').textContent=label;$('#busy').hidden=false;try{return await fn();}catch(e){toast(e.message,true);}finally{$('#busy').hidden=true;}}
async function api(url,method='GET',body){const headers={'X-Report-Client':'studio-v1'};if(body&&!(body instanceof FormData))headers['Content-Type']='application/json';const response=await fetch('/api'+url,{method,headers,body:body instanceof FormData?body:body?JSON.stringify(body):undefined});if(!response.ok){let data;try{data=await response.json();}catch{throw Error('서버 응답을 읽지 못했습니다.');}let detail=data.detail;if(Array.isArray(detail))detail=detail.map(x=>x.loc.join('.')+': '+x.msg).join('\n');throw Error(detail||'요청에 실패했습니다.');}return response.json();}
function openModal(title,html,wide=false){$('#modalTitle').textContent=title;$('#modalBody').innerHTML=html;modal.style.width=wide?'1000px':'560px';if(!modal.open)modal.showModal();}
$('#closeModal').onclick=()=>modal.close();
function report(){return current?.report;}
function profile(){return templates.find(t=>t.id===report()?.template_id)?.profile||templates[0]?.profile;}
function field(label,id,value='',type='text'){return '<label>'+label+'<input id="'+id+'" type="'+type+'" value="'+esc(value)+'"></label>';}
function area(label,id,value='',rows=4){return '<label>'+label+'<textarea id="'+id+'" rows="'+rows+'">'+esc(value)+'</textarea></label>';}
function options(obj,value){return Object.entries(obj).map(([k,v])=>'<option value="'+esc(k)+'"'+(k===value?' selected':'')+'>'+esc(v)+'</option>').join('');}
function selectField(label,id,obj,value){return '<label>'+label+'<select id="'+id+'">'+options(obj,value)+'</select></label>';}
function check(label,id,value=false){return '<label class="check"><input type="checkbox" id="'+id+'"'+(value?' checked':'')+'>'+label+'</label>';}
async function refreshList(){const list=await api('/reports');$('#reportSelect').innerHTML='<option value="">보고서 선택</option>'+list.map(r=>'<option value="'+r.id+'"'+(r.id===current?.id?' selected':'')+'>'+esc(r.title)+(r.stage==='approved'?' · 승인':'')+'</option>').join('');}
async function accept(item){current=item;validation=await api('/reports/'+item.id+'/validation');if(!report().blocks.some(b=>b.id===selected))selected=report().blocks[0]?.id||null;await refreshList();render();}
async function persist(next,note='내용 수정'){await accept(await api('/reports/'+current.id,'PUT',{revision:current.revision,report:next,note}));toast('저장했습니다.');}
function render(){
 $('#projectTitle').textContent=report().title;
 $('#stageBadge').textContent={draft:'작성 중',review:'검토 중',approved:'최종 승인'}[current.stage];
 $('#saveState').textContent='저장됨 · 버전 '+current.revision;
 ['editMeta','exportHwpx','exportHwp'].forEach(id=>$('#'+id).disabled=false);
 $('#footerStatus').textContent=report().demo?'가상 예시 데이터 · 연습용 보고서':'내 PC에 저장 · 변경 시 승인이 해제됩니다';
 $('#pageCount').textContent='예상 '+validation.layout.estimated_pages+'쪽 · 목표 '+report().target_pages+'쪽';
 renderLeft();renderPaper();renderRight();
}
function changeTab(side,tab){if(side==='left'){leftTab=tab;renderLeft();}else{rightTab=tab;if(tab==='history')busy(async()=>{history=await api('/reports/'+current.id+'/history');renderRight();});else renderRight();}document.querySelectorAll('#'+side+'Tabs button').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));}
$('#leftTabs').onclick=e=>{if(e.target.dataset.tab)changeTab('left',e.target.dataset.tab);};
$('#rightTabs').onclick=e=>{if(e.target.dataset.tab&&current)changeTab('right',e.target.dataset.tab);};
function choose(id){selected=id;rightTab='edit';document.querySelectorAll('#rightTabs button').forEach(b=>b.classList.toggle('active',b.dataset.tab==='edit'));renderLeft();renderRight();document.querySelectorAll('.doc-block').forEach(el=>el.classList.toggle('selected',el.dataset.id===id));}
function renderLeft(){
 const host=$('#leftContent');
 if(!current){host.innerHTML='<div class="empty"><h3>나의 보고서 작업공간</h3><p>새 보고서를 만들거나<br>예시를 열어 시작해 보세요.</p></div>';return;}
 const r=report();
 if(leftTab==='outline'){
  host.innerHTML='<div class="mini-summary"><strong>'+esc(config.purposes[r.purpose])+'</strong><small>'+esc(r.audience)+' · '+esc(profile().name)+'</small></div><p class="section-label">DOCUMENT BLOCKS · '+r.blocks.length+'</p>'+r.blocks.map((b,i)=>'<button class="outline-item '+(b.id===selected?'active':'')+'" data-id="'+b.id+'"><span class="outline-index">'+String(i+1).padStart(2,'0')+'</span><span>'+esc(b.title||'제목 없음')+'<small>'+config.kinds[b.kind]+'</small></span>'+(b.locked?'<span class="lock">잠금</span>':'')+'</button>').join('')+'<button id="addBlock" class="full">＋ 문서 부품 추가</button><button id="confirmPlan" class="full">구성안 확인 완료</button><p class="form-tip">순서와 필수항목을 확인한 뒤 검토 단계로 이동하세요.</p>';
  host.querySelectorAll('[data-id]').forEach(el=>el.onclick=()=>choose(el.dataset.id));
  $('#addBlock').onclick=addBlockDialog;
  $('#confirmPlan').onclick=()=>busy(async()=>{await accept(await api('/reports/'+current.id+'/confirm-plan','POST',{revision:current.revision}));changeTab('right','review');toast('구성안을 확인했습니다.');});
 }else if(leftTab==='sources'){
  host.innerHTML='<p class="section-label">EVIDENCE LIBRARY</p><p class="form-tip">근거자료와 양식 참고자료를 분리합니다. 등록 후 부품에 연결해 주세요.</p>'+r.sources.map(s=>'<div class="source-card"><h3>'+esc(s.name)+'</h3><span class="pill">'+(s.role==='evidence'?'사실 근거':'양식 참고')+'</span><span class="pill '+(!s.confirmed?'warn':'')+'">'+(s.confirmed?'검토 완료':'확인 필요')+'</span><p>'+esc(s.reference||'출처 위치 미입력')+'</p><button data-source="'+s.id+'">내용 확인·수정</button></div>').join('')+'<button id="addSource" class="full">＋ 근거자료 등록</button>';
  host.querySelectorAll('[data-source]').forEach(el=>el.onclick=()=>sourceDialog(el.dataset.source));
  $('#addSource').onclick=()=>sourceDialog();
 }else{
  host.innerHTML='<p class="section-label">STYLE LIBRARY</p>'+templates.map(t=>'<div class="template-card"><h3>'+esc(t.profile.name)+'</h3><p>'+esc(t.profile.font)+' · '+t.profile.body_pt+'pt<br>'+t.profile.width_mm+' × '+t.profile.height_mm+' mm</p><button data-template="'+t.id+'">'+(!t.approved?'추출값 검토·등록':t.id===r.template_id?'사용 중':'이 양식 적용')+'</button></div>').join('')+'<button id="uploadTemplate" class="full">＋ 기관 HWPX 양식 등록</button><input id="templateFile" type="file" accept=".hwpx" hidden><p class="form-tip">용지·여백·대표 글꼴과 크기를 추출합니다. 기존 본문·로고·복잡한 배치는 복제하지 않습니다.</p>';
  host.querySelectorAll('[data-template]').forEach(el=>el.onclick=()=>{const t=templates.find(x=>x.id===el.dataset.template);if(!t.approved)return templateDialog(t);busy(()=>persist({...r,template_id:t.id},'양식 변경'));});
  $('#uploadTemplate').onclick=()=>$('#templateFile').click();
  $('#templateFile').onchange=e=>busy(async()=>{const f=e.target.files[0];if(!f)return;const fd=new FormData();fd.append('file',f);const t=await api('/templates','POST',fd);templates=await api('/templates');renderLeft();templateDialog(t);},'HWPX 양식의 스타일을 분석합니다…');
 }
}
function blockHTML(b,itemStart=0){
 let html='<h3>□ '+esc(b.title||'제목 없음')+'</h3>';
 if(b.text)html+='<div class="'+(['summary','request'].includes(b.kind)?'doc-callout':'')+'"><p>'+esc(b.text)+'</p></div>';
 if(['process','strategy'].includes(b.kind)&&b.items.length)html+='<table class="doc-table"><thead><tr><th style="width:15%">단계</th><th>추진내용</th></tr></thead><tbody>'+b.items.map((t,i)=>'<tr><td>'+String(itemStart+i+1)+'</td><td>'+esc(t)+'</td></tr>').join('')+'</tbody></table>'; else if(b.items.length)html+='<ul>'+b.items.map(t=>'<li>'+esc(t)+'</li>').join('')+'</ul>';
 if(['table','comparison','timeline'].includes(b.kind)&&b.columns.length)html+='<table class="doc-table"><thead><tr>'+b.columns.map(x=>'<th>'+esc(x)+'</th>').join('')+'</tr></thead><tbody>'+b.rows.map(row=>'<tr>'+row.map(x=>'<td>'+esc(x)+'</td>').join('')+'</tr>').join('')+'</tbody></table>';
 if(b.kind==='chart'&&b.values.length){const max=Math.max(0,...b.values);html+='<small>단위: '+esc(b.unit)+' · 기준: '+esc(b.as_of)+'</small><table class="doc-table"><thead><tr><th>항목</th><th>수치</th><th>비교 막대</th></tr></thead><tbody>'+b.labels.map((label,i)=>'<tr><td>'+esc(label)+'</td><td>'+esc(b.values[i]??'')+' '+esc(b.unit)+'</td><td>'+((b.values[i]>0&&max>0)?'■'.repeat(Math.max(1,Math.round(20*b.values[i]/max))):'—')+'</td></tr>').join('')+'</tbody></table>';}
 if(!b.text&&!b.items.length&&!b.rows.length&&!b.values.length)html+='<div class="placeholder">선택해서 내용을 입력해 주세요.</div>';
 if(b.source_ids.length)html+='<small class="doc-source">근거: '+b.source_ids.map(id=>esc(report().sources.find(s=>s.id===id)?.name||'연결 없음')).join(' · ')+'</small>';
 return html;
}
function renderPaper(){
 const r=report(),p=profile();
 $('#paperArea').innerHTML=validation.layout.pages.map((page,idx)=>'<article class="paper" style="--doc-accent:'+p.accent+'"><div class="doc-kicker"><span>'+esc(r.department||'업무보고')+'</span><span>'+esc(r.report_date)+'</span></div>'+(idx===0?'<h2>'+esc(r.title)+'</h2><div class="doc-meta">'+esc(r.audience)+' 보고 · '+(r.demo?'가상 데이터 예시 · ':'')+(current.stage==='approved'?'승인본':'검토용 초안')+'</div>':'<div class="doc-meta">'+(page[0]?.reference?'근거 및 출처':esc(r.title)+' · 계속')+'</div>')+page.map(f=>'<section class="doc-block '+(f.block.id===selected?'selected':'')+'" data-id="'+esc(f.block.id)+'"'+(f.reference?' data-reference="true"':' tabindex="0" role="button" aria-label="'+esc(f.block.title)+' 편집"')+'>'+blockHTML(f.block,f.item_start||0)+'</section>').join('')+'<div class="page-footer"><span>'+esc(p.name)+' · 예상 배치</span><span>'+String(idx+1).padStart(2,'0')+' / '+String(validation.layout.pages.length).padStart(2,'0')+'</span></div></article>').join('');
 $('#paperArea').querySelectorAll('.paper').forEach(el=>{el.style.setProperty('--doc-font',p.font);el.style.setProperty('--doc-body',(p.body_pt*1.1)+'px');el.style.setProperty('--doc-title',(p.title_pt*1.1)+'px');});
 $('#paperArea').querySelectorAll('.doc-block:not([data-reference])').forEach(el=>{el.onclick=()=>choose(el.dataset.id);el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose(el.dataset.id);}};});
}
function renderRight(){
 const host=$('#rightContent');if(!current)return;
 if(rightTab==='review'){renderReview();return;}
 if(rightTab==='history'){renderHistory();return;}
 const b=report().blocks.find(x=>x.id===selected);
 if(!b){host.innerHTML='<div class="empty"><h3>편집할 부품을 선택하세요.</h3></div>';return;}
 let fields=field('부품 제목','bTitle',b.title)+selectField('부품 종류','bKind',config.kinds,b.kind)+area('본문 / 설명','bText',b.text,4);
 if(['bullets','process','strategy'].includes(b.kind))fields+=area('항목 · 한 줄에 하나','bItems',b.items.join('\n'),5);
 if(['table','comparison','timeline'].includes(b.kind))fields+=area('열 제목 · | 로 구분','bColumns',b.columns.join(' | '),2)+area('데이터 · 한 줄에 한 행 / | 로 열 구분','bRows',b.rows.map(row=>row.join(' | ')).join('\n'),7);
 if(b.kind==='chart')fields+=area('항목명 | 값 · 한 줄에 하나','bChart',b.labels.map((label,i)=>label+' | '+b.values[i]).join('\n'),5)+field('단위','bUnit',b.unit)+field('기준시점','bAsOf',b.as_of);
 host.innerHTML='<p class="section-label">SELECTED BLOCK</p><div class="editor-tools"><button id="moveUp" title="위로">↑</button><button id="moveDown" title="아래로">↓</button><button id="toggleLock">'+(b.locked?'잠금 해제':'내용 잠금')+'</button><button id="deleteBlock" class="danger"'+(b.required||b.locked?' disabled':'')+'>삭제</button></div>'+(b.locked?'<div class="notice">내용과 연결된 근거자료가 잠겨 있습니다.</div>':'')+'<form id="blockForm"><fieldset '+(b.locked?'disabled':'')+' style="border:0;padding:0;margin:0">'+fields+check('필수 부품으로 유지','bRequired',b.required)+'<p class="section-label">CONNECTED EVIDENCE</p><div class="source-checks">'+(report().sources.filter(s=>s.role==='evidence').map(s=>'<label class="check"><input type="checkbox" name="source" value="'+s.id+'"'+(b.source_ids.includes(s.id)?' checked':'')+'>'+esc(s.name)+'</label>').join('')||'<small>왼쪽 근거자료 탭에서 자료를 등록하세요.</small>')+'</div><button class="primary full" type="submit">변경사항 저장</button></fieldset></form><hr class="divider"><p class="section-label">부분 수정 요청</p>'+area('선택한 부품에 적용','instruction','',3)+'<p class="form-tip">예: 단계: 선정 / 촬영 / 검수 / 납품<br>또는 제목: 새 제목 · 맨 앞으로 · 개조식으로</p>'+check('외부 AI로 문장 다듬기 (설정 필요)','useAi')+check('선택 부품·수정 요청·공개 근거의 외부 전송에 동의','aiConsent')+'<button id="applyCommand" class="full"'+(b.locked?' disabled':'')+'>수정 요청 적용</button><p class="form-tip">'+(config.ai_available?'AI 모델: '+esc(config.ai_model):'현재 로컬 명령 사용 중 · AI 연결은 선택사항')+'</p>';
 $('#toggleLock').onclick=()=>busy(()=>updateBlock({...b,locked:!b.locked},b.locked?'내용 잠금 해제':'내용 잠금'));
 $('#moveUp').onclick=()=>moveBlock(-1);$('#moveDown').onclick=()=>moveBlock(1);
 $('#deleteBlock').onclick=()=>busy(()=>persist({...report(),blocks:report().blocks.filter(x=>x.id!==b.id)},'부품 삭제'));
 $('#bKind').onchange=e=>{const kind=e.target.value;if(b.rows.length||b.values.length||b.items.length){toast('부품 종류를 바꾸면 기존 내용은 본문에 보존합니다.');}const preserved=[b.text,...b.items,b.columns.join(' | '),...b.rows.map(x=>x.join(' | ')),...b.labels.map((x,i)=>x+': '+b.values[i]+' '+b.unit)].filter(Boolean).join('\n');busy(()=>updateBlock({...b,kind,text:preserved,items:[],columns:[],rows:[],labels:[],values:[],unit:'',as_of:''},'부품 종류 변경'));};
 $('#blockForm').onsubmit=e=>{e.preventDefault();busy(async()=>{const updated={...b,title:$('#bTitle').value,text:$('#bText').value,required:$('#bRequired').checked,source_ids:[...host.querySelectorAll('input[name="source"]:checked')].map(e=>e.value)};
 if($('#bItems'))updated.items=$('#bItems').value.split('\n').map(x=>x.trim()).filter(Boolean);
 if($('#bColumns')){updated.columns=$('#bColumns').value.split('|').map(x=>x.trim()).filter(Boolean);updated.rows=$('#bRows').value.split('\n').filter(x=>x.trim()).map(row=>row.split('|').map(x=>x.trim()));}
 if($('#bChart')){const rows=$('#bChart').value.split('\n').filter(x=>x.trim()).map(x=>x.split('|').map(x=>x.trim()));if(rows.some(x=>x.length!==2||!x[1]||!Number.isFinite(Number(x[1].replaceAll(',','')))))throw Error('각 줄에 ‘항목 | 숫자’를 입력해 주세요.');updated.labels=rows.map(x=>x[0]);updated.values=rows.map(x=>Number(x[1].replaceAll(',','')));updated.unit=$('#bUnit').value;updated.as_of=$('#bAsOf').value;}
 await updateBlock(updated);});};
 $('#applyCommand').onclick=()=>busy(async()=>{const instruction=$('#instruction').value;if(!instruction.trim())throw Error('수정 요청을 입력해 주세요.');const before=structuredClone(b);await accept(await api('/reports/'+current.id+'/edit','POST',{revision:current.revision,block_id:b.id,instruction,use_ai:$('#useAi').checked,consent:$('#aiConsent').checked}));showDiff(before,report().blocks.find(x=>x.id===b.id));},'선택한 부품을 수정합니다…');
}
async function updateBlock(block,note='부품 내용 수정'){await persist({...report(),blocks:report().blocks.map(b=>b.id===block.id?block:b)},note);}
function moveBlock(delta){busy(async()=>{const r=structuredClone(report());const i=r.blocks.findIndex(b=>b.id===selected),j=i+delta;if(j<0||j>=r.blocks.length)return;[r.blocks[i],r.blocks[j]]=[r.blocks[j],r.blocks[i]];await persist(r,'부품 순서 변경');});}
function addBlockDialog(){openModal('문서 부품 추가',selectField('부품 종류','newKind',config.kinds,'text')+field('제목','newBlockTitle')+'<button id="createBlock" class="primary full">추가</button>');$('#createBlock').onclick=()=>busy(async()=>{const kind=$('#newKind').value,title=$('#newBlockTitle').value||config.kinds[kind];const b={id:crypto.randomUUID().replaceAll('-',''),kind,title,text:'',items:[],columns:['table','comparison','timeline'].includes(kind)?['항목','내용']:[],rows:[],labels:[],values:[],unit:'',as_of:'',source_ids:[],locked:false,required:false};selected=b.id;await persist({...report(),blocks:[...report().blocks,b]},'부품 추가');modal.close();});}
function renderReview(){
 const issues=validation.issues;
 $('#rightContent').innerHTML='<p class="section-label">DOCUMENT CHECK</p><div class="count-row"><div class="count-card"><b>'+validation.errors+'</b>확인할 오류</div><div class="count-card"><b>'+validation.warnings+'</b>검토할 경고</div></div>'+issues.map(i=>'<div class="issue '+i.level+'" data-issue="'+(i.block_id||'')+'">'+esc(i.message)+'</div>').join('')+'<hr class="divider"><p class="section-label">실제 HWPX 검토</p><button id="previewPdf" class="full">한글에서 PDF 렌더링·보기</button><p class="form-tip">'+(config.pdf_available?'이 PC의 한글로 생성한 HWPX를 열어 PDF로 변환합니다.':'Windows용 한글과 pywin32 설치가 필요합니다.')+'</p><button id="downloadJson" class="full">편집 데이터 JSON 내보내기</button><hr class="divider"><p class="section-label">FINAL APPROVAL</p>'+field('검토자','reviewer',current.approval?.reviewer||'')+check('수치·단위·일정·출처를 원자료와 대조했습니다.','factsReviewed')+check('실제 HWPX 또는 한글 렌더링 PDF에서 배치·잘림을 확인했습니다.','nativeReviewed')+'<button id="approveReport" class="primary full"'+(current.stage==='approved'?' disabled':'')+'>'+(current.stage==='approved'?'최종 승인 완료':'검토 완료·최종 승인')+'</button><p class="form-tip">승인 전에 구성안 확인이 필요합니다. 수정하면 승인이 해제됩니다. 자동 검사는 내용의 진실성을 보증하지 않습니다.</p>';
 document.querySelectorAll('[data-issue]').forEach(el=>el.onclick=()=>{if(el.dataset.issue)choose(el.dataset.issue);});
 $('#previewPdf').onclick=()=>busy(()=>download('pdf',true),'실제 한글에서 PDF를 렌더링합니다. 최대 55초가 걸릴 수 있습니다…');
 $('#downloadJson').onclick=()=>busy(()=>download('json'));
 $('#approveReport').onclick=()=>busy(async()=>{await accept(await api('/reports/'+current.id+'/approve','POST',{revision:current.revision,reviewer:$('#reviewer').value,native_reviewed:$('#nativeReviewed').checked,facts_reviewed:$('#factsReviewed').checked}));toast('최종 승인했습니다. 승인본을 내보낼 수 있습니다.');});
}
function renderHistory(){
 $('#rightContent').innerHTML='<p class="section-label">VERSION HISTORY</p><p class="form-tip">모든 저장은 새 버전으로 남습니다. 복원도 새 버전으로 저장되며 승인은 해제됩니다.</p>'+history.map((h,i)=>'<div class="history-item"><strong>버전 '+h.revision+' · '+esc(h.note)+'</strong><small>'+new Date(h.created).toLocaleString('ko-KR')+'</small><div><button data-compare="'+i+'">현재와 비교</button>'+(h.revision!==current.revision?'<button data-restore="'+h.revision+'">이 버전 복원</button>':'<span class="pill">현재</span>')+'</div></div>').join('');
 document.querySelectorAll('[data-compare]').forEach(el=>el.onclick=()=>showDiff(JSON.parse(history[Number(el.dataset.compare)].body),report()));
 document.querySelectorAll('[data-restore]').forEach(el=>el.onclick=()=>busy(async()=>{await accept(await api('/reports/'+current.id+'/restore','POST',{revision:current.revision,target_revision:Number(el.dataset.restore)}));history=await api('/reports/'+current.id+'/history');renderRight();toast('이전 내용을 새 버전으로 복원했습니다.');}));
}
function showDiff(before,after){openModal('변경 전후 비교','<p class="form-tip">변경사항은 버전 이력에 저장되었습니다. 이력에서 이전 버전을 복원할 수 있습니다.</p><div class="form-row"><div><h3>변경 전</h3><pre class="diff">'+esc(JSON.stringify(before,null,2))+'</pre></div><div><h3>변경 후</h3><pre class="diff">'+esc(JSON.stringify(after,null,2))+'</pre></div></div>',true);}
function sourceDialog(id){
 const source=report().sources.find(s=>s.id===id)||{name:'',text:'',role:'evidence',sensitivity:'internal',reference:'',as_of:'',confirmed:false};
 openModal(id?'근거자료 확인·수정':'근거자료 등록','<button id="loadSourceFile">파일에서 텍스트 가져오기</button><input id="sourceFile" type="file" accept=".txt,.md,.csv,.json,.hwpx" hidden><p class="form-tip">TXT · CSV · JSON · HWPX / PDF·이미지 OCR은 지원하지 않습니다.</p>'+field('자료 이름','sName',source.name)+'<div class="form-row">'+selectField('사용 목적','sRole',{evidence:'사실 확인용 근거',style:'디자인 참고만'},source.role)+selectField('외부 전송 구분','sSensitivity',{internal:'내부 처리 전용',public:'외부 전송 가능한 공개자료'},source.sensitivity)+'</div>'+area('근거 내용','sText',source.text,8)+field('출처 위치 · 문서명 / 경로 / URL','sReference',source.reference)+field('자료 기준시점','sAsOf',source.as_of)+check('원자료를 읽고 사실·수치를 확인했습니다.','sConfirmed',source.confirmed)+'<div class="modal-actions">'+(id?'<button id="deleteSource" class="danger">자료 삭제</button>':'')+'<button id="saveSource" class="primary">저장</button></div>');
 $('#loadSourceFile').onclick=()=>$('#sourceFile').click();
 $('#sourceFile').onchange=e=>busy(async()=>{const file=e.target.files[0];if(!file)return;const fd=new FormData();fd.append('file',file);const data=await api('/sources/extract','POST',fd);$('#sName').value=data.name;$('#sText').value=data.text;$('#sConfirmed').checked=false;});
 $('#sText').oninput=()=>$('#sConfirmed').checked=false;
 $('#saveSource').onclick=()=>busy(async()=>{const updated={...source,id:id||crypto.randomUUID().replaceAll('-',''),name:$('#sName').value,text:$('#sText').value,role:$('#sRole').value,sensitivity:$('#sSensitivity').value,reference:$('#sReference').value,as_of:$('#sAsOf').value,confirmed:$('#sConfirmed').checked};if(!updated.name.trim())throw Error('자료 이름을 입력해 주세요.');await persist({...report(),sources:id?report().sources.map(s=>s.id===id?updated:s):[...report().sources,updated]},'근거자료 저장');modal.close();});
 if(id)$('#deleteSource').onclick=()=>busy(async()=>{if(report().blocks.some(b=>b.source_ids.includes(id)))throw Error('부품에서 사용 중인 자료입니다. 근거 연결을 먼저 해제해 주세요.');await persist({...report(),sources:report().sources.filter(s=>s.id!==id)},'근거자료 삭제');modal.close();});
}
function templateDialog(t){
 const p=t.profile;
 openModal('기관 양식 추출값 확인','<div class="notice">'+esc(t.metadata.notice)+'</div>'+field('양식 이름','tName',p.name)+field('본문 글꼴','tFont',p.font)+'<div class="form-row">'+field('본문 크기 (10–18pt)','tBody',p.body_pt,'number')+field('제목 크기 (14–32pt)','tTitle',p.title_pt,'number')+'</div><div class="form-row">'+field('용지 가로 (mm)','tWidth',p.width_mm,'number')+field('용지 세로 (mm)','tHeight',p.height_mm,'number')+'</div><div class="form-row">'+field('공통 여백 (mm)','tMargin',p.margin_mm,'number')+field('강조색','tAccent',p.accent,'color')+'</div><button id="confirmTemplate" class="primary full">추출값 확인·양식 등록</button>');
 $('#confirmTemplate').onclick=()=>busy(async()=>{const updated={name:$('#tName').value,font:$('#tFont').value,body_pt:Number($('#tBody').value),title_pt:Number($('#tTitle').value),width_mm:Number($('#tWidth').value),height_mm:Number($('#tHeight').value),margin_mm:Number($('#tMargin').value),accent:$('#tAccent').value};await api('/templates/'+t.id+'/approve','POST',updated);templates=await api('/templates');renderLeft();modal.close();toast('기관 양식이 등록되었습니다.');});
}

const planFields=[
 ['summary','보고요지','이 계획으로 추진하려는 핵심 내용과 보고 목적을 적어 주세요.',3],
 ['background','추진배경 및 필요성','현황, 문제점, 사업을 추진해야 하는 이유를 입력하세요. 한 줄씩 쓰면 개조식으로 정리됩니다.',4],
 ['goals','추진목표','달성하려는 목표를 입력하세요. 확인된 수치가 있다면 함께 적어 주세요.',3],
 ['scope','사업개요 및 추진범위','사업기간, 대상, 위치, 담당부서, 추진범위 등을 자유롭게 적어 주세요.',4],
 ['strategy','추진방향 및 전략','추진 원칙이나 중점과제를 한 줄에 하나씩 입력하세요.',3],
 ['steps','단계별 추진 절차','한 줄에 한 단계씩 입력하세요.\n대상 선정 및 사전 협의\n자료 수집 및 현장 조사\n성과 검토 및 결과 보고',6],
 ['schedule','추진일정','자유롭게 쓰거나 시기 | 추진내용 | 담당 형식으로 입력하세요.\n10월 | 현장 조사 | 담당부서\n11월 | 성과 검토 | 검토부서',4],
 ['budget','소요예산','자유롭게 쓰거나 항목 | 금액 | 산출근거 형식으로 입력하세요.\n현장 조사 | 500만원 | 견적서 기준',4],
 ['effects','기대효과','기대되는 개선 효과를 입력하세요.',3],
 ['requests','행정사항 및 협조 요청','보고 후 결정할 사항, 부서별 협조사항 등을 입력하세요.',3],
 ['notes','기타 검토사항','유의사항, 제약조건 등 추가로 담을 내용을 입력하세요.',3]
];
let planDraft={};
function planInputDialog(){
 const d=planDraft,templateOptions=Object.fromEntries(templates.filter(t=>t.approved).map(t=>[t.id,t.profile.name]));
 const sections=planFields.map(([key,label,hint,rows],index)=>'<section class="plan-section"><h3><span>'+String(index+1).padStart(2,'0')+'</span> '+label+'</h3>'+area(label,'plan_'+key,d[key]||'',rows)+'<p class="form-tip">'+esc(hint).replaceAll('\n','<br>')+'</p></section>').join('');
 openModal('내용 입력으로 추진계획서 만들기','<p class="plan-intro">작성한 내용을 기관 양식의 문단·절차표·일정표로 배치합니다. 빈 항목은 생략하며, 새로운 수치나 사실을 추가하지 않습니다.</p><form id="planForm">'+field('계획서 제목 *','plan_title',d.title||'')+'<div class="form-row">'+field('작성 부서','plan_department',d.department||'')+field('보고 대상','plan_audience',d.audience||'기관장')+'</div><div class="form-row">'+field('보고일','plan_report_date',d.report_date||new Date().toLocaleDateString('sv-SE'),'date')+selectField('기준 양식','plan_template_id',templateOptions,d.template_id||'public')+'</div><div class="plan-fields">'+sections+'</div>'+field('목표 분량 (출처 포함 · 내용에 따라 늘어납니다)','plan_target_pages',d.target_pages||3,'number')+check('입력한 내용의 사실·수치·출처를 직접 확인했습니다.','plan_confirmed',d.confirmed||false)+'<p class="form-tip">체크하지 않아도 초안을 만들 수 있습니다. 입력 내용은 내부 근거자료로 보관되며, 외부로 전송되지 않습니다.</p><div class="plan-submit"><span id="planDraftState">입력 중인 내용은 이 작성창에 임시 보관됩니다.</span><button type="submit" class="primary">입력한 내용으로 계획서 만들기 →</button></div></form>',true);
 $('#plan_title').required=true;$('#plan_title').maxLength=240;
 for(const [key] of planFields)$('#plan_'+key).maxLength=['summary','requests'].includes(key)?3000:12000;
 $('#plan_target_pages').min=1;$('#plan_target_pages').max=30;
 const collect=()=>Object.fromEntries([...['title','department','audience','report_date','template_id'].map(k=>[k,$('#plan_'+k).value]),...planFields.map(([k])=>[k,$('#plan_'+k).value]),['target_pages',Number($('#plan_target_pages').value)],['confirmed',$('#plan_confirmed').checked]]);
 $('#planForm').oninput=()=>{planDraft=collect();$('#planDraftState').textContent='입력 내용 임시 보관 중 · 생성 후 문서로 저장됩니다.';};
 $('#planForm').onsubmit=e=>{e.preventDefault();busy(async()=>{planDraft=collect();await accept(await api('/plans/from-input','POST',planDraft));planDraft={};modal.close();toast('입력 내용을 추진계획서로 구성하고 저장했습니다.');},'입력 내용을 문단·절차·표로 구성합니다…');};
}

function reportDialog(edit=false){
 const r=edit?report():{title:'',purpose:'plan',audience:'기관장',department:'',report_date:new Date().toLocaleDateString('sv-SE'),message:'',decision:'',target_pages:2,template_id:'public'};
 const templateOptions=Object.fromEntries(templates.filter(t=>t.approved).map(t=>[t.id,t.profile.name]));
 openModal(edit?'보고서 설정':'새 보고서 만들기',field('보고서 제목','rTitle',r.title)+ '<div class="form-row">'+selectField('보고 목적','rPurpose',config.purposes,r.purpose)+field('보고 대상','rAudience',r.audience)+'</div><div class="form-row">'+field('작성 부서','rDepartment',r.department)+field('보고일','rDate',r.report_date,'date')+'</div>'+area('핵심 메시지','rMessage',r.message,3)+area('요청하는 결정','rDecision',r.decision,2)+'<div class="form-row">'+selectField('기준 양식','rTemplate',templateOptions,r.template_id)+field('목표 분량 (출처 포함)','rPages',r.target_pages,'number')+'</div><p class="form-tip">목적에 맞는 구성안을 제안합니다. 빈 예산·일정·성과 수치는 사용자가 근거를 확인하고 입력합니다.</p><button id="saveReportMeta" class="primary full">'+(edit?'설정 저장':'구성안 만들기 →')+'</button>');
 $('#saveReportMeta').onclick=()=>busy(async()=>{const next={...r,title:$('#rTitle').value,purpose:$('#rPurpose').value,audience:$('#rAudience').value,department:$('#rDepartment').value,report_date:$('#rDate').value,message:$('#rMessage').value,decision:$('#rDecision').value,template_id:$('#rTemplate').value,target_pages:Number($('#rPages').value)};if(!next.title.trim())throw Error('보고서 제목을 입력해 주세요.');if(edit)await persist(next,'보고서 설정 변경');else{const plan=await api('/plan','POST',next);await accept(await api('/reports','POST',plan));}modal.close();toast(edit?'설정을 저장했습니다.':'구성안을 만들었습니다. 근거자료와 내용을 채워 주세요.');});
}
async function download(format,preview=false){
 const response=await fetch('/api/reports/'+current.id+'/export',{method:'POST',headers:{'Content-Type':'application/json','X-Report-Client':'studio-v1'},body:JSON.stringify({revision:current.revision,format,approved:current.stage==='approved'})});
 if(!response.ok){let message='내보내기에 실패했습니다.';try{message=(await response.json()).detail||message;}catch{}throw Error(message);}
 const blob=await response.blob(),url=URL.createObjectURL(blob);
 if(preview){openModal('실제 한글 렌더링 · '+(response.headers.get('X-Render-Pages')||'?')+'쪽','<p class="form-tip">생성한 HWPX를 이 PC의 한글로 렌더링한 결과입니다. 내용·잘림·페이지를 검토해 주세요.</p><iframe title="한글 렌더링 PDF" class="pdf-frame" src="'+url+'"></iframe><button id="savePdf" class="full">PDF 내려받기</button>',true);$('#savePdf').onclick=()=>downloadURL(url,report().title+'.pdf');modal.addEventListener('close',()=>URL.revokeObjectURL(url),{once:true});}
 else{downloadURL(url,report().title+(current.stage==='approved'?'-승인본':'-초안')+'.'+format);setTimeout(()=>URL.revokeObjectURL(url),10000);toast(format==='hwp'?'한글에서 재열기·내용 대조를 통과한 HWP를 다운로드했습니다.':'파일을 생성했습니다. 다운로드 폴더를 확인해 주세요.');}
}
function downloadURL(url,name){const a=document.createElement('a');a.href=url;a.download=name.replace(/[<>:"/\\|?*]/g,'_');document.body.append(a);a.click();a.remove();}
$('#newReport').onclick=()=>reportDialog();
$('#welcomeNew').onclick=()=>planInputDialog();
$('#newPlan').onclick=()=>planInputDialog();
$('#editMeta').onclick=()=>reportDialog(true);
$('#openDemo').onclick=$('#welcomeDemo').onclick=()=>busy(async()=>{await accept(await api('/demo','POST',{}));toast('가상 예시 보고서를 열었습니다.');});
$('#exportHwp').onclick=()=>busy(()=>download('hwp'),'한글 2014 호환 HWP 생성 및 실제 재열기를 검증합니다…');
$('#exportHwpx').onclick=()=>busy(()=>download('hwpx'),'편집 가능한 HWPX를 생성·검증합니다…');
$('#reportSelect').onchange=e=>{if(e.target.value)busy(async()=>{await accept(await api('/reports/'+e.target.value));if(rightTab==='history'){history=await api('/reports/'+current.id+'/history');renderRight();}});};
$('#importJson').onclick=()=>$('#jsonFile').click();
$('#jsonFile').onchange=e=>busy(async()=>{const file=e.target.files[0];if(!file)return;if(file.size>4*1024*1024)throw Error('JSON은 4MB 이하여야 합니다.');const r=JSON.parse(await file.text());await accept(await api('/reports','POST',r));toast('새 보고서로 가져왔습니다.');e.target.value='';});
async function init(){config=await api('/config');
 $('#exportHwp').hidden=!config.hangul?.available;
 if(config.hangul?.legacy){$('#compatibilityNotice').hidden=false;$('#compatibilityNotice').textContent='이 PC의 한글 '+config.hangul.version+'에서는 HWP 내보내기를 권장합니다. HWPX는 표 중심의 호환형으로 생성합니다. 이전에 받은 파일은 새로 내보내 주세요.';}
templates=await api('/templates');const list=await api('/reports');if(list.length)await accept(await api('/reports/'+list[0].id));else {await refreshList();renderLeft();}}
busy(init,'로컬 작업공간을 엽니다…');

