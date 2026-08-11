const app=document.querySelector('#app');
const esc=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
async function api(url,opts={}){const r=await fetch(url,{headers:{'Content-Type':'application/json',...(opts.headers||{})},...opts});const j=await r.json();if(!r.ok)throw new Error(j.detail||j.error||'Erreur');return j}
const fmtDate=x=>x?new Date(x).toLocaleDateString('fr-FR'):'—';
function nav(path){location.href=path}
async function startSession(mode,target,extra={}){const s=await api('/api/sessions',{method:'POST',body:JSON.stringify({mode,target,...extra})});nav(`/practice?session=${s.sessionId}`)}

async function home(){
  const [d,p,c]=await Promise.all([api('/api/dashboard'),api('/api/plan'),api('/api/curriculum')]);
  app.innerHTML=`<section class="hero"><span class="eyebrow">${esc(c.program.name)} · ${esc(c.program.source_code)}</span><h1>Réviser ce qui augmente vraiment ton score.</h1><p>Le moteur combine spaced repetition, erreurs récentes, concepts faibles, nouvelles notions, confiance et vitesse. Plus tu l'utilises, plus la sélection devient personnelle.</p><div class="actions"><button class="button" id="daily">Session du jour · ${p.recommendedDailyQuestions}</button><button class="button secondary" id="diag">Diagnostic</button><a class="button secondary" href="/exam">Mode Exam</a><a class="button secondary" href="/curriculum">Voir le curriculum</a></div></section>
  <section class="grid"><div class="card"><div class="muted">Readiness score</div><div class="metric">${d.readiness}%</div><div class="muted">Maîtrise + accuracy + couverture + vitesse</div></div><div class="card"><div class="muted">À revoir maintenant</div><div class="metric">${d.due}</div><div class="muted">Questions dues en répétition espacée</div></div><div class="card"><div class="muted">Error Book ouvert</div><div class="metric">${d.openErrors}</div><div class="muted">Erreurs / réponses fragiles non résolues</div></div></section>
  <h2 class="section-title">Moteurs déjà prêts avant ton import</h2><section class="grid"><div class="card"><h3>Mastery par concept</h3><p class="muted">Posterior de maîtrise mis à jour avec difficulté, vitesse et auto-évaluation.</p></div><div class="card"><h3>Blueprint adaptatif</h3><p class="muted">35% dues · 25% erreurs · 25% concepts faibles · 15% nouvelles notions.</p></div><div class="card"><h3>Pipeline Level I</h3><p class="muted">Topic → Learning Module → LOS → Concept → Formule → Question → Source.</p></div></section>`;
  document.querySelector('#daily').onclick=()=>startSession('daily');document.querySelector('#diag').onclick=()=>startSession('diagnostic',30);
}

async function curriculum(){
  const c=await api('/api/curriculum');
  app.innerHTML=`<section class="hero" style="padding-top:18px"><span class="pill">Curriculum canonique</span><h1>${esc(c.program.name)}</h1><p>Code source : <strong>${esc(c.program.source_code)}</strong>. Les 10 matières alimentent le mastery. Les Mock Exams sont conservés comme évaluations transversales séparées.</p><div class="stats"><div class="stat"><strong>${c.summary.totalExpectedModules}</strong><span>modules officiels</span></div><div class="stat"><strong>${c.summary.totalImportedModules}</strong><span>modules importés</span></div><div class="stat"><strong>${c.summary.totalCompletedModules}</strong><span>modules terminés</span></div></div></section><div class="card"><h3>10 matières · ${c.summary.totalExpectedModules} modules</h3>${c.topics.map((t,i)=>`<div class="plan-phase"><div><span class="tag">${String(i+1).padStart(2,'0')}</span> <strong>${esc(t.source_label||t.name)}</strong>${t.canonical_name&&t.canonical_name!==t.source_label?`<div class="muted">CFA topic: ${esc(t.canonical_name)}</div>`:''}<div class="muted">Course ${t.source_course_id} · ${t.imported_modules}/${t.expected_modules} modules importés · ${t.completed_modules}/${t.expected_modules} terminés</div></div><div style="min-width:180px"><div class="bar"><span style="width:${t.expected_modules?Math.min(100,100*t.imported_modules/t.expected_modules):0}%"></span></div><div class="muted">Poids examen ${t.min_weight}–${t.max_weight}%</div></div></div>`).join('')}</div><h2 class="section-title">Évaluations</h2><div class="card">${c.assessments.map(a=>`<div class="plan-phase"><div><span class="tag">${esc(a.collection_type)}</span> <strong>${esc(a.name)}</strong></div><span class="muted">${a.set_count} mock(s) importé(s)</span></div>`).join('')}</div>`;
}

let timerHandle=null;
async function runSession(sid){
  if(timerHandle)clearInterval(timerHandle);
  async function next(){
    const data=await api(`/api/sessions/${sid}/next`);
    if(data.complete)return sessionSummary(sid);
    renderQuestion(data.session,data.question);
  }
  function renderQuestion(session,q){
    let selected=null,assessment='knew',started=Date.now(),result=null;
    const render=()=>{
      const progress=Math.round((q.answered/q.total)*100);
      app.innerHTML=`<section class="practice"><div class="progress"><span style="width:${progress}%"></span></div><div class="question-meta"><div class="row"><span class="pill">${esc(q.topic)}</span>${q.concepts.map(c=>`<span class="tag">${esc(c.name)}</span>`).join('')}</div><div class="row"><span class="muted">${q.position}/${q.total}</span>${['exam','mock'].includes(q.mode)?'<span class="timer" id="timer"></span>':''}</div></div><div class="muted">${esc(q.module||'')} ${q.los?`· LOS ${esc(q.los)}`:''} · difficulté ${q.difficulty}/3 · ${esc(q.type)}</div><h1>${esc(q.prompt)}</h1><div class="options">${q.options.map(o=>`<button class="option ${selected===o.key?'selected':''}" data-key="${o.key}" ${result?'disabled':''}><strong>${o.key}.</strong> ${esc(o.text)}</button>`).join('')}</div>
      ${result?resultHtml(result,q):`<div class="muted">Avant de valider : tu avais quel niveau de certitude ?</div><div class="confidence"><button data-assess="knew" class="${assessment==='knew'?'active':''}">Je savais</button><button data-assess="guessed" class="${assessment==='guessed'?'active':''}">J'ai deviné</button><button data-assess="didnt_know" class="${assessment==='didnt_know'?'active':''}">Je ne savais pas</button></div><div class="actions"><button class="button" id="submit" ${selected?'':'disabled'}>Valider</button><button class="button ghost" id="bookmark">☆ Marquer</button></div>`}</section>`;
      document.querySelectorAll('.option').forEach(b=>b.onclick=()=>{selected=b.dataset.key;render()});
      document.querySelectorAll('[data-assess]').forEach(b=>b.onclick=()=>{assessment=b.dataset.assess;render()});
      const sub=document.querySelector('#submit');if(sub)sub.onclick=async()=>{result=await api('/api/attempt',{method:'POST',body:JSON.stringify({sessionId:Number(sid),questionId:q.id,answer:selected,selfAssessment:assessment,durationMs:Date.now()-started})});render()};
      const bm=document.querySelector('#bookmark');if(bm)bm.onclick=async()=>{const x=await api('/api/bookmarks/toggle',{method:'POST',body:JSON.stringify({questionId:q.id})});bm.textContent=x.bookmarked?'★ Marqué':'☆ Marquer'};
      const nxt=document.querySelector('#next');if(nxt)nxt.onclick=next;
      document.querySelectorAll('[data-reason]').forEach(b=>b.onclick=async()=>{await api('/api/errors/reason',{method:'POST',body:JSON.stringify({questionId:q.id,mistakeReason:b.dataset.reason})});document.querySelector('#reasonBox').innerHTML='<span class="muted">Cause enregistrée.</span>'});
      if(['exam','mock'].includes(q.mode))startTimer(session,q);
    };
    render();
  }
  function startTimer(session,q){
    const el=document.querySelector('#timer');if(!el||!session.time_limit_seconds)return;
    const started=new Date(session.created_at).getTime();const end=started+session.time_limit_seconds*1000;
    const tick=()=>{const left=Math.max(0,Math.floor((end-Date.now())/1000));const m=Math.floor(left/60),s=left%60;const node=document.querySelector('#timer');if(node)node.textContent=`${m}:${String(s).padStart(2,'0')}`;if(left<=0){clearInterval(timerHandle);sessionSummary(sid)}};tick();timerHandle=setInterval(tick,1000);
  }
  function resultHtml(r,q){
    if(r.deferredCorrection)return `<div class="result"><h3>Réponse enregistrée</h3><p class="muted">En mode Exam, aucune correction n'est affichée avant le débrief.</p><button class="button" id="next">Question suivante</button></div>`;
    const reason=!r.correct?`<div id="reasonBox"><p class="muted">Pourquoi l'as-tu ratée ?</p><div class="reason-grid"><button data-reason="knowledge">Connaissance</button><button data-reason="formula">Formule</button><button data-reason="calculation">Calcul</button><button data-reason="reading">Lecture</button><button data-reason="concept_confusion">Confusion</button><button data-reason="time">Temps</button></div></div>`:'';
    return `<div class="result ${r.correct?'good':'bad'}"><h3>${r.correct?'✓ Bonne réponse':'✕ À revoir'}</h3><p>${esc(r.explanation)}</p>${reason}<div class="actions" style="margin-top:14px"><button class="button" id="next">Question suivante</button></div></div>`;
  }
  next();
}

async function sessionSummary(sid){
  if(timerHandle)clearInterval(timerHandle);const s=await api(`/api/sessions/${sid}/summary`);
  app.innerHTML=`<section class="hero"><span class="pill">Débrief ${esc(s.session.mode)}</span><h1>${s.score}%</h1><p>${s.attempts.length} questions répondues. Le moteur a déjà réinjecté les erreurs et réponses fragiles dans tes prochaines révisions.</p><div class="actions"><button class="button" id="again">Session adaptative</button><a class="button secondary" href="/dashboard">Dashboard</a></div></section><div class="card"><h3>Correction complète</h3>${s.attempts.map(a=>`<div class="error-item"><div class="row"><span class="tag">${esc(a.topic_name)}</span><strong style="color:${a.correct?'var(--good)':'var(--bad)'}">${a.correct?'Correct':'Incorrect'}</strong><span class="muted">${Math.round(a.duration_ms/1000)}s · ${esc(a.self_assessment)}</span></div><p><strong>${esc(a.prompt)}</strong></p><p class="muted">Bonne réponse : ${esc(a.correct_answer)} · ${esc(a.explanation)}</p></div>`).join('')}</div>`;
  document.querySelector('#again').onclick=()=>startSession('daily');
}

async function dashboard(){
  const d=await api('/api/dashboard');
  app.innerHTML=`<section class="hero" style="padding-top:18px"><span class="pill">Performance</span><h1>Ton tableau de maîtrise.</h1><p>Le score de maîtrise n'est pas une simple moyenne de bonnes réponses : il tient compte de la difficulté, de la certitude, de la vitesse et de la répétition.</p></section><section class="grid"><div class="card"><div class="muted">Readiness</div><div class="metric">${d.readiness}%</div></div><div class="card"><div class="muted">Accuracy 7 jours</div><div class="metric">${d.window7.accuracy}%</div><div class="muted">${d.window7.avgSeconds}s / question</div></div><div class="card"><div class="muted">Accuracy 30 jours</div><div class="metric">${d.window30.accuracy}%</div><div class="muted">Couverture ${d.coverage}%</div></div><div class="card"><div class="muted">Streak</div><div class="metric">${d.streak}</div><div class="muted">jours consécutifs</div></div><div class="card"><div class="muted">Due now</div><div class="metric">${d.due}</div></div><div class="card"><div class="muted">Open errors</div><div class="metric">${d.openErrors}</div></div></section>
  <h2 class="section-title">Par matière</h2><div class="card">${d.topics.map(t=>`<div class="topic-row"><div><strong>${esc(t.name)}</strong><div class="muted">Poids examen ${t.minWeight}–${t.maxWeight}% · ${t.attempts} réponses</div></div><div><div class="bar"><span style="width:${t.mastery}%"></span></div><div class="muted">Accuracy ${t.accuracy}% · ${t.avgSeconds}s/q</div></div><strong>${t.mastery}%</strong></div>`).join('')}</div>
  <h2 class="section-title">Concepts les plus faibles</h2><div class="card">${d.concepts.length?d.concepts.map(c=>`<div class="concept-row"><div><strong>${esc(c.name)}</strong><div class="muted">${esc(c.topic)} · ${c.exposures} expositions · Δ30j ${c.delta30>0?'+':''}${c.delta30} pts</div></div><div class="bar ${c.masteryPercent>=70?'good':''}"><span style="width:${c.masteryPercent}%"></span></div><div><strong>${c.masteryPercent}%</strong><br><span class="mastery-badge ${c.band}">${esc(c.band)}</span></div></div>`).join(''):'<div class="empty">Fais un diagnostic pour initialiser les scores par concept.</div>'}</div>`;
}

async function exam(){
  const a=await api('/api/assessments');
  app.innerHTML=`<section class="hero"><span class="pill">Mode Exam</span><h1>Simuler sans feedback.</h1><p>Questions pondérées par matière, chronomètre continu, aucune correction pendant le bloc et débrief complet à la fin. Les mocks importés conservent leur ordre officiel au lieu d'être randomisés.</p><div class="actions"><button class="button" data-n="90">Bloc adaptatif 90 questions</button><button class="button secondary" data-n="60">60 questions</button><button class="button secondary" data-n="30">30 questions</button></div></section><h2 class="section-title">Mock Exams 2027</h2><div class="card">${a.assessmentSets.length?a.assessmentSets.map(x=>`<div class="plan-phase"><div><strong>${esc(x.name)}</strong><div class="muted">${esc(x.collection_name||'Mock Exams')} · ${x.item_count} questions</div></div>${x.item_count?`<button class="button secondary" data-mock="${x.id}">Lancer</button>`:'<span class="muted">En attente du contenu</span>'}</div>`).join(''):'<div class="empty">La collection Mock Exams est prête. Les examens apparaîtront ici dès leur import.</div>'}</div>`;
  document.querySelectorAll('[data-n]').forEach(b=>b.onclick=()=>startSession('exam',Number(b.dataset.n)));
  document.querySelectorAll('[data-mock]').forEach(b=>b.onclick=()=>startSession('mock',null,{assessmentSetId:Number(b.dataset.mock)}));
}

async function formulas(){
  const f=await api('/api/formulas');
  app.innerHTML=`<section class="hero" style="padding-top:18px"><span class="pill">Formula Bank</span><h1>Connaître, reconnaître, appliquer.</h1><p>Chaque formule peut être reliée à son concept, ses variables et des questions de calcul. Les drills mélangent reconnaissance et application.</p><button class="button" id="drill">Lancer un Formula Drill</button></section><div class="grid two">${f.formulas.map(x=>`<div class="card"><span class="tag">${esc(x.topic_name||'')}</span><span class="tag">${esc(x.concept_name||'')}</span><h3>${esc(x.name)}</h3><div class="formula">${esc(x.expression)}</div><p class="muted">${esc(x.explanation||'')}</p>${Object.keys(x.variables||{}).length?`<div>${Object.entries(x.variables).map(([k,v])=>`<span class="tag">${esc(k)} = ${esc(v)}</span>`).join('')}</div>`:''}</div>`).join('')}</div>`;
  document.querySelector('#drill').onclick=()=>startSession('formula',20);
}

async function errors(){
  const e=await api('/api/errors');const open=e.errors.filter(x=>!x.resolved),closed=e.errors.filter(x=>x.resolved);
  app.innerHTML=`<section class="hero" style="padding-top:18px"><span class="pill">Error Book</span><h1>Transformer les erreurs en syllabus personnel.</h1><p>Les erreurs sont regroupées par concept et par cause : connaissance, formule, calcul, lecture, confusion ou temps.</p></section><div class="card"><h3>À revoir · ${open.length}</h3>${open.length?open.map(errorHtml).join(''):'<div class="empty">Aucune erreur ouverte.</div>'}</div>${closed.length?`<h2 class="section-title">Résolues</h2><div class="card">${closed.slice(0,30).map(errorHtml).join('')}</div>`:''}`;
  document.querySelectorAll('[data-resolve]').forEach(b=>b.onclick=async()=>{await api('/api/errors/resolve',{method:'POST',body:JSON.stringify({errorId:Number(b.dataset.resolve),resolved:true})});errors()});
}
function errorHtml(x){return `<div class="error-item"><div class="row"><span class="tag">${esc(x.topic_name)}</span><span class="tag">${esc(x.concept_name||'Concept')}</span><span class="tag">${esc(x.reasonLabel)}</span><span class="muted">×${x.times_wrong}</span></div><p><strong>${esc(x.prompt)}</strong></p><p class="muted">${esc(x.explanation)}</p>${!x.resolved?`<button class="button secondary" data-resolve="${x.id}">Marquer résolue</button>`:''}</div>`}

async function plan(){
  const p=await api('/api/plan');
  app.innerHTML=`<section class="hero" style="padding-top:18px"><span class="pill">Study Plan</span><h1>${p.daysUntilExam==null?'Planifier jusqu’au jour J.':`${p.daysUntilExam} jours avant l’examen.`}</h1><p>La charge quotidienne augmente automatiquement en approchant de la date d'examen, tandis que le mix passe progressivement de couverture à consolidation puis mocks.</p></section><section class="grid"><div class="card"><div class="muted">Questions / jour</div><div class="metric">${p.recommendedDailyQuestions}</div></div><div class="card"><div class="muted">Semaines restantes</div><div class="metric">${p.weeksRemaining}</div></div><div class="card"><div class="muted">Questions jamais vues</div><div class="metric">${p.unseenQuestions}</div></div></section><h2 class="section-title">Phases</h2><div class="card">${p.phases.map(x=>`<div class="plan-phase"><strong>${esc(x.name)}</strong><span class="muted">${x.days!=null?`${x.days} jours`:`${x.share}% du temps`}</span></div>`).join('')}</div><div class="actions" style="margin-top:16px"><a class="button secondary" href="/settings">Régler la date d'examen</a></div>`;
}

async function settings(){
  const s=await api('/api/settings');
  app.innerHTML=`<section class="hero" style="padding-top:18px"><span class="pill">Réglages</span><h1>Calibrer ton moteur.</h1></section><div class="card" style="max-width:650px"><label>Date de l'examen<input type="date" id="examDate" value="${esc(s.exam_date||'')}"></label><label>Objectif quotidien de base<input type="number" id="daily" min="5" max="120" value="${s.daily_target}"></label><label>Temps cible par question en Exam (secondes)<input type="number" id="qtime" min="30" max="240" value="${s.exam_question_time_seconds}"></label><button class="button" id="save">Enregistrer</button><span id="saved" class="muted"></span></div>`;
  document.querySelector('#save').onclick=async()=>{await api('/api/settings',{method:'POST',body:JSON.stringify({examDate:document.querySelector('#examDate').value||null,dailyTarget:Number(document.querySelector('#daily').value),examQuestionTimeSeconds:Number(document.querySelector('#qtime').value)})});document.querySelector('#saved').textContent='Enregistré.'};
}

async function conceptMap(){
  const [m,c]=await Promise.all([api('/api/concept-map'),api('/api/confusions')]);
  const byId=Object.fromEntries(m.nodes.map(n=>[n.id,n]));
  app.innerHTML=`<section class="hero" style="padding-top:18px"><span class="pill">Concept Graph</span><h1>Voir les dépendances et les confusions.</h1><p>Les prérequis permettent de repérer les blocages en amont. Les distracteurs tagués font remonter les confusions récurrentes entre deux concepts.</p></section><div class="grid two"><div class="card"><h3>Graphe de prérequis</h3>${m.edges.length?m.edges.map(e=>`<div class="plan-phase"><span>${esc(byId[e.from]?.name||e.from)}</span><strong>→ ${esc(byId[e.to]?.name||e.to)}</strong></div>`).join(''):'<div class="empty">Les relations apparaîtront avec ton import Level I.</div>'}</div><div class="card"><h3>Confusions détectées</h3>${c.confusions.length?c.confusions.map(x=>`<div class="error-item"><span class="tag">${esc(x.topic_name)}</span><p><strong>${esc(x.correct_concept)}</strong> ↔ ${esc(x.confused_with)}</p><div class="muted">${x.count} occurrence(s)</div></div>`).join(''):'<div class="empty">Aucune confusion structurée détectée pour le moment.</div>'}</div></div><h2 class="section-title">Tous les concepts</h2><div class="card">${m.nodes.map(n=>`<div class="concept-row"><div><strong>${esc(n.name)}</strong><div class="muted">${esc(n.topic_name)} · importance ${n.importance}</div></div><div class="bar"><span style="width:${n.masteryPercent}%"></span></div><div><strong>${n.masteryPercent}%</strong><br><span class="mastery-badge ${n.band}">${esc(n.band)}</span></div></div>`).join('')}</div>`;
}

async function importPage(){
  const schema=await api('/api/import/schema');
  app.innerHTML=`<section class="hero" style="padding-top:18px"><span class="pill">Content Pipeline</span><h1>Prêt pour ton Level I.</h1><p>Le moteur accepte un bundle versionné avec Learning Modules, concepts, prérequis, LOS, formules, questions et références de source. Un validateur bloque les questions incomplètes avant import.</p></section><div class="grid two"><div class="card"><h3>Importer un JSON</h3><input type="file" id="file" accept="application/json,.json"><label>Bundle<textarea id="bundle" placeholder="Colle ici le JSON normalisé…"></textarea></label><button class="button" id="send">Valider & importer</button><pre id="result" class="muted"></pre></div><div class="card"><h3>Schéma attendu</h3><pre class="formula" style="white-space:pre-wrap;font-size:11px">${esc(JSON.stringify(schema.bundle,null,2))}</pre></div></div>`;
  document.querySelector('#file').onchange=async e=>{const f=e.target.files[0];if(f)document.querySelector('#bundle').value=await f.text()};
  document.querySelector('#send').onclick=async()=>{const out=document.querySelector('#result');try{const bundle=JSON.parse(document.querySelector('#bundle').value);const r=await api('/api/import',{method:'POST',body:JSON.stringify({filename:'browser-import.json',bundle})});out.textContent=JSON.stringify(r,null,2)}catch(e){out.textContent=e.message}};
}

async function route(){try{const path=location.pathname;const params=new URLSearchParams(location.search);if(path==='/curriculum')return curriculum();if(path==='/practice'){const sid=params.get('session');return sid?runSession(sid):startSession('daily')}if(path==='/dashboard')return dashboard();if(path==='/exam')return exam();if(path==='/formulas')return formulas();if(path==='/errors')return errors();if(path==='/plan')return plan();if(path==='/settings')return settings();if(path==='/map')return conceptMap();if(path==='/import')return importPage();return home()}catch(e){app.innerHTML=`<div class="card"><h3>Erreur</h3><p class="muted">${esc(e.message)}</p></div>`}}
route();
