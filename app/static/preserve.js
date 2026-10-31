'use strict';
const $ = id => document.getElementById(id);
let inspected = null, selected = null, queued = [], comparison = null, activeFile = null, working = false;

function status(message, error = false) {
  $('preserveStatus').textContent = message;
  $('preserveStatus').classList.toggle('error', error);
}
async function work(fn) {
  if (working) return;
  working = true;
  $('preserveWorkspace').disabled = true;
  try { await fn(); } catch (error) { status(error.message, true); }
  finally { working = false; $('preserveWorkspace').disabled = false; }
}
function node(tag, content) {
  const el = document.createElement(tag);
  if (content !== undefined) el.textContent = content;
  return el;
}
function resetComparison() {
  comparison = null;
  $('comparisonResult').hidden = true;
  $('downloadSection').hidden = true;
}
function requestData() {
  return {source_sha256: inspected.source_sha256, replacements: queued};
}
async function post(action, body, binary = false) {
  const response = await fetch('/api/hwpx/' + action, {method: 'POST', headers: {'X-Report-Client': 'studio-v1'}, body});
  if (!response.ok) {
    const data = await response.json();
    throw Error(typeof data.detail === 'string' ? data.detail : '입력 형식을 확인해 주세요.');
  }
  return binary ? response.blob() : response.json();
}
function form(withRequest = true) {
  const data = new FormData();
  data.append('file', activeFile);
  if (withRequest) data.append('request_json', JSON.stringify(requestData()));
  return data;
}
function choose(target) {
  selected = target;
  $('targetEditor').hidden = false;
  $('targetLocation').textContent = target.section + ' · ' + target.location;
  $('targetOriginal').value = target.text;
  $('targetRestriction').textContent = target.reason || (target.length_locked ? '줄 배치 캐시가 있어 UTF-16 길이가 같은 치환만 지원합니다.' : '같은 글자 서식 안의 텍스트를 치환합니다.');
  const existing = queued.find(edit => edit.target_id === target.id);
  $('findText').value = existing ? existing.before : target.text;
  $('replaceText').value = existing ? existing.after : target.text;
  $('expectedCount').value = existing ? existing.expected_count : 1;
  ['findText', 'replaceText', 'expectedCount', 'queueEdit'].forEach(id => $(id).disabled = !target.supported);
  renderTargets();
}
function renderTargets() {
  if (!inspected) return;
  const query = $('targetSearch').value.toLocaleLowerCase();
  const matches = inspected.targets.filter(t => ($('showProtected').checked || t.supported) &&
    (t.section + ' ' + t.location + ' ' + t.text).toLocaleLowerCase().includes(query));
  $('targetCount').textContent = matches.length + '개 검색됨 · 한 번에 최대 100개 표시';
  const host = $('targetList');
  host.replaceChildren();
  for (const target of matches.slice(0, 100)) {
    const button = node('button', target.location + (target.supported ? '' : ' · 보존 전용'));
    button.type = 'button';
    button.classList.toggle('active', selected?.id === target.id);
    button.append(node('small', target.text.slice(0, 130) || '(텍스트 없음)'));
    button.onclick = () => choose(target);
    host.append(button);
  }
}
function renderQueue() {
  resetComparison();
  $('changeSection').hidden = queued.length === 0;
  const host = $('queuedChanges');
  host.replaceChildren();
  queued.forEach((edit, index) => {
    const target = inspected.targets.find(t => t.id === edit.target_id);
    const row = node('div');
    row.className = 'queued';
    row.append(node('strong', target.location), node('pre', edit.before + ' → ' + edit.after));
    const remove = node('button', '목록에서 제거');
    remove.type = 'button';
    remove.onclick = () => { queued.splice(index, 1); renderQueue(); };
    row.append(remove);
    host.append(row);
  });
}
function save(blob, suffix) {
  const name = activeFile.name.replace(/\.hwpx$/i, '') + suffix;
  const url = URL.createObjectURL(blob), anchor = node('a');
  anchor.href = url; anchor.download = name;
  document.body.append(anchor); anchor.click(); anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
$('preserveFile').onchange = () => {
  inspected = null; selected = null; queued = []; activeFile = null; resetComparison();
  $('targetSection').hidden = true; $('targetEditor').hidden = true; $('changeSection').hidden = true;
  $('inspectionSummary').textContent = '';
  status('선택한 파일을 검사하세요.');
};
$('inspectFile').onclick = () => work(async () => {
  const file = $('preserveFile').files[0];
  if (!file || !/\.hwpx$/i.test(file.name)) throw Error('.hwpx 파일을 선택하세요.');
  if (file.size > 10 * 1024 * 1024) throw Error('파일은 10MB 이하여야 합니다.');
  activeFile = file;
  status('패키지·XML·참조·표 구조를 검사합니다…');
  const result = await post('inspect', form(false));
  inspected = result; queued = []; selected = null; resetComparison();
  $('targetEditor').hidden = true; $('changeSection').hidden = true;
  $('inspectionSummary').textContent = '구조 검사 통과 · ' + result.validation.sections + '개 구역 · 수정 가능 ' + result.supported_count + '개 / 보존 전용 ' + result.unsupported_count + '개 문단';
  $('targetSection').hidden = false;
  renderTargets(); status('수정할 문단이나 셀을 선택하세요.');
});
$('targetSearch').oninput = renderTargets;
$('showProtected').onchange = renderTargets;
for (const id of ['findText', 'replaceText', 'expectedCount']) $(id).oninput = () => {
  resetComparison(); status('입력한 내용을 수정 목록에 추가한 뒤 다시 비교하세요.');
};
$('queueEdit').onclick = () => {
  if (!selected?.supported) return;
  const before = $('findText').value, after = $('replaceText').value, count = Number($('expectedCount').value);
  if (!before || before === after) return status('서로 다른 원문과 새 텍스트를 입력하세요.', true);
  if (!Number.isInteger(count) || count < 1 || count > 100) return status('출현 횟수는 1~100의 정수여야 합니다.', true);
  if (!queued.some(e => e.target_id === selected.id) && queued.length >= 100) return status('한 번에 최대 100개 문단을 수정할 수 있습니다.', true);
  queued = queued.filter(edit => edit.target_id !== selected.id);
  queued.push({target_id: selected.id, before, after, expected_count: count});
  renderQueue(); status('목록에 추가했습니다. 변경 전후 비교를 실행하세요.');
};
$('previewChanges').onclick = () => work(async () => {
  resetComparison(); status('치환 전후와 수정본 구조를 검증합니다…');
  comparison = await post('preview', form());
  const table = node('table'), head = node('tr');
  ['수정 위치', '변경 전', '변경 후'].forEach(title => head.append(node('th', title)));
  const thead = node('thead'); thead.append(head); table.append(thead);
  const body = node('tbody');
  for (const change of comparison.changes) {
    const row = node('tr');
    for (const value of [change.location, change.before, change.after]) {
      const cell = node('td'); cell.append(node('pre', value)); row.append(cell);
    }
    body.append(row);
  }
  table.append(body); $('comparisonTable').replaceChildren(table);
  $('validationSummary').textContent = '구조·XML·참조·표 격자·텍스트 재대조 통과. 수정 구역 ' + comparison.changed_members.length + '개, 나머지 ' + comparison.preserved_members + '개 항목의 내용은 원본과 동일합니다. 실제 한글 배치는 별도로 확인하세요.';
  $('comparisonResult').hidden = false; $('downloadSection').hidden = false;
  status('변경 전후를 확인한 뒤 복사본을 다운로드하세요.');
});
$('downloadCopy').onclick = () => work(async () => {
  if (!comparison) throw Error('변경 전후 비교를 먼저 실행하세요.');
  const data = form(); data.append('reviewed_output_sha256', comparison.output_sha256);
  const blob = await post('replace', data, true);
  save(blob, '-수정본.hwpx'); status('수정본을 만들었습니다. 다운로드 폴더에서 열어 배치를 확인하세요.');
});
$('downloadComparison').onclick = () => {
  if (comparison) save(new Blob([JSON.stringify(comparison, null, 2) + '\n'], {type: 'application/json'}), '-변경비교.json');
};
