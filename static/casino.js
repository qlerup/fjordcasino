'use strict';
const $ = selector => document.querySelector(selector);
const money = value => Number(value).toLocaleString('da-DK');
const state = {data:null, game:null, busy:false, bets:[], chip:20, rotation:0, pending:null};
const machines = {
 duck:{name:'Andedammen', symbols:['duck-yellow','duck-mallard','duck-pink','duck-sailor','duck-crown','wild']},
 cosmic:{name:'Stjernestøv', symbols:['star','moon','planet','rocket','diamond','wild']},
 fruit:{name:'Frugtfesten', symbols:['cherry','lemon','grape','watermelon','seven','wild']}
};
const red = new Set([1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]);
const wheel = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26];
function element(tag, cls='', text) { const el=document.createElement(tag); el.className=cls; if(text!==undefined)el.textContent=text; return el; }
function symbol(name) {
 const holder=element('span');
 if(name.startsWith('duck-')) {
  const colors={'duck-yellow':'#edc653','duck-mallard':'#728764','duck-pink':'#dc9ca6','duck-sailor':'#b6cfd2','duck-crown':'#d8b565'};
  // Only fixed application artwork is inserted as markup; API content uses textContent.
  holder.innerHTML=`<svg viewBox="0 0 180 155" aria-hidden="true"><ellipse cx="86" cy="138" rx="62" ry="8" fill="#142f3422"/><path d="M31 91 Q7 66 24 61 Q37 86 66 83 C65 48 70 23 99 21 C132 18 150 51 132 75 C151 120 121 137 78 134 C39 132 23 115 31 91Z" fill="${colors[name]||colors['duck-yellow']}"/><path d="M54 93 Q77 113 111 94 Q107 125 79 121 Q55 116 54 93" fill="#ffffff33"/><path d="M128 51 L166 62 Q163 78 130 72Z" fill="#d78838"/><circle cx="119" cy="45" r="5" fill="#23312b"/><circle cx="120" cy="43" r="1.5" fill="white"/>${name==='duck-crown'?'<path d="M78 28 L74 5 L91 15 L102 0 L112 15 L131 6 L126 30Z" fill="#f4d582" stroke="#a78439" stroke-width="2"/>':name==='duck-sailor'?'<path d="M78 29 L78 17 Q101 8 125 17 L130 29Z" fill="#fff9e8"/><path d="M77 29 L132 29" stroke="#456783" stroke-width="7"/>':''}</svg>`;
 } else {holder.className='emoji';holder.textContent=({star:'⭐',moon:'🌙',planet:'🪐',rocket:'🚀',diamond:'💎',cherry:'🍒',lemon:'🍋',grape:'🍇',watermelon:'🍉',seven:'7️⃣',wild:'✦'})[name]||'✦';}
 return holder;
}
document.querySelectorAll('[data-symbol]').forEach(el=>el.replaceChildren(symbol(el.dataset.symbol)));
function toast(message,error=false,retry=null) {
 const box=$('#toast');box.className='toast'+(error?' error':'');box.replaceChildren(document.createTextNode(message));
 clearTimeout(toast.timer);
 if(retry){const b=element('button','','Prøv samme runde igen');b.onclick=retry;box.append(b);}
 else toast.timer=setTimeout(()=>box.classList.add('hidden'),6500);
}
async function api(path,body) {
 const options={headers:{},signal:AbortSignal.timeout(12000)};
 if(body!==undefined){options.method='POST';options.headers={'Content-Type':'application/json','X-CSRF-Token':$('meta[name="csrf-token"]').content};options.body=JSON.stringify(body);}
 const response=await fetch(path,options);
 if(response.status===401){location.assign('/login');throw new Error('Log ind igen.');}
 const data=await response.json();
 if(!response.ok){const err=new Error(data.error||'Forespørgslen blev afvist.');err.definitive=response.status<500;throw err;}
 return data;
}
function pendingKey(){return 'fjordcasino-round-'+state.data.user.id;}
function loadPending(){try{const p=JSON.parse(sessionStorage.getItem(pendingKey()));if(p&&['slots','roulette','blackjack'].includes(p.game)&&p.body&&typeof p.body.request_id==='string')state.pending=p;}catch{/* Storage may be disabled. */}}
function rememberPending(){try{if(state.pending)sessionStorage.setItem(pendingKey(),JSON.stringify(state.pending));else sessionStorage.removeItem(pendingKey());}catch{/* Server idempotency still protects retries during this page visit. */}}
function renderState(data){state.data=data;$('#balance').textContent=money(data.user.balance);$('#daily-label').textContent='Dagens mønter er på din saldo';renderHistory();}
async function refresh(){renderState(await api('/api/state'));}
function renderHistory(){
 const data=state.data;if(!data)return;
 $('#stats').replaceChildren(...[['Spillede runder',data.stats.rounds],['Gevinster i alt',data.stats.won],['Største gevinst',data.stats.biggest]].map(([label,value])=>{const box=element('div','stat');box.append(element('small','',label),element('strong','',money(value)));return box;}));
 $('#history-rows').replaceChildren(...data.history.map(row=>{const tr=element('tr');tr.append(element('td','',row.description),element('td','',new Date(row.created_at).toLocaleString('da-DK')),element('td',row.amount>=0?'positive':'negative',(row.amount>0?'+':'')+money(row.amount)),element('td','',money(row.balance)));return tr;}));
}
function busy(on){state.busy=on;document.querySelectorAll('#game-content button,#game-content select,[data-nav],[data-open],[data-filter],#logout').forEach(el=>el.disabled=on);}
function id(){const bytes=crypto.getRandomValues(new Uint8Array(16));return Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');}
async function play(game,body,onResult){
 if(state.busy)return;
 if(state.pending&&(state.pending.game!==game||!body.request_id)){toast('En tidligere runde afventer svar. Hent resultatet først.',true,recover);return;}
 const requestBody={...body,request_id:body.request_id||id()};
 state.pending={game,body:requestBody};rememberPending();busy(true);
 try{
  const result=await api('/api/play/'+game,requestBody);
  state.pending=null;rememberPending();
  state.data.user.balance=result.balance;$('#balance').textContent=money(result.balance);
  await onResult(result);
  try{await refresh();}catch{toast('Runden er gemt. Historikken kunne ikke opdateres.',true);}
 }catch(error){
  if(error.definitive){state.pending=null;rememberPending();}
  toast(error.message||'Forbindelsen blev afbrudt. Runden kan allerede være gemt.',true,state.pending?recover:null);
 }finally{busy(false);if(state.game==='blackjack')renderBlackjack();}
}
async function recover(){
 if(!state.pending||state.busy)return;
 const pending=state.pending;
 await play(pending.game,pending.body,async result=>{toast('Runden er hentet. Din saldo er opdateret.');if(result.game==='blackjack')state.data.blackjack=result;});
 if(!state.pending){navigate('history');}
}
function navigate(view){
 if(state.busy)return;
 if(view==='blackjack'){openGame('blackjack');return;}
 state.game=null;$('#lobby-view').classList.toggle('hidden',view==='history');$('#history-view').classList.toggle('hidden',view!=='history');$('#game-view').classList.add('hidden');
 document.querySelectorAll('[data-nav]').forEach(el=>el.classList.toggle('active',el.dataset.nav===view));
 if(view!=='history')filter(['slots','roulette'].includes(view)?view:'all');
}
function filter(category){document.querySelectorAll('[data-category]').forEach(el=>el.hidden=category!=='all'&&el.dataset.category!==category);document.querySelectorAll('[data-filter]').forEach(el=>el.classList.toggle('active',el.dataset.filter===category));}
function resultText(result){return result.payout?'Gevinst: '+money(result.payout)+' mønter · indsats '+money(result.bet):'Ingen gevinst denne gang · indsats '+money(result.bet)+' mønter';}
function showResult(result){const box=$('#game-result');if(box){box.textContent=resultText(result);box.classList.toggle('winner',result.payout>result.bet);}}
const wait=ms=>new Promise(resolve=>setTimeout(resolve,matchMedia('(prefers-reduced-motion: reduce)').matches?0:ms));
function betSelect(values){const label=element('label','','INDSATS');const select=element('select');select.id='bet';select.setAttribute('aria-label','Indsats i mønter');values.forEach(v=>{const opt=element('option','',money(v)+' mønter');opt.value=v;select.append(opt);});label.append(select);return label;}
function button(text,cls,fn){const el=element('button',cls,text);el.type='button';el.onclick=fn;return el;}
function openGame(key){
 if(state.busy||!state.data)return;state.game=key;state.bets=[];
 $('#lobby-view').classList.add('hidden');$('#history-view').classList.add('hidden');$('#game-view').classList.remove('hidden');
 const [kind,name]=key.split(':');
 $('#game-title').textContent=kind==='slot'?machines[name].name:kind==='roulette'?(name==='duck'?'Anderoulette':'Roulette Royale'):'Blackjack Club';
 $('#game-kicker').textContent=kind==='slot'?'TRE HJUL · TRE VANDRETTE LINJER':kind==='roulette'?'EUROPÆISK ROULETTE · ÉT NUL':'SEKS KORTSPIL · DEALER STÅR PÅ 17';
 document.querySelectorAll('[data-nav]').forEach(el=>el.classList.toggle('active',el.dataset.nav===(kind==='slot'?'slots':kind)));
 if(kind==='slot')renderSlots(name);else if(kind==='roulette')renderRoulette(name);else renderBlackjack();
 $('#main').focus({preventScroll:true});
}
function renderSlots(name){
 const stage=element('div','game-stage '+name+'-stage');const machine=element('div','slot-machine');machine.append(element('div','slot-marquee',machines[name].name));
 const reels=element('div','reels');reels.id='reels';for(let i=0;i<9;i++){const cell=element('div','reel-cell');cell.append(symbol(machines[name].symbols[i%5]));reels.append(cell);}machine.append(reels,element('div','slot-under','3 LINJER · WILD ERSTATTER ALLE SYMBOLER'));stage.append(machine);
 const result=element('div','game-result','Vælg din indsats, og drej hjulene.');result.id='game-result';result.setAttribute('aria-live','polite');stage.append(result);
 const controls=element('div','bet-controls');controls.append(betSelect([30,60,150,300,600]),button('Drej hjulene ↻','button gold spin-button',()=>{
  play('slots',{machine:name,bet:Number($('#bet').value)},async data=>{reels.classList.add('spinning');await wait(700);reels.classList.remove('spinning');[...reels.children].forEach((cell,i)=>{cell.replaceChildren(symbol(data.grid[Math.floor(i/3)][i%3]));cell.classList.toggle('win',data.lines.some(line=>line.row===Math.floor(i/3)));});showResult(data);});
 }));stage.append(controls,element('p','rules-inline','Indsatsen fordeles ligeligt på tre vandrette linjer. Tre ens symboler giver gevinst. Wild erstatter alle symboler. Gevinster inkluderer indsatsen.'));
 const table=element('div','paytable');machines[name].symbols.forEach((s,i)=>{const p=element('div','pay-symbol');p.append(symbol(s),element('span','',[8,12,20,36,80,200][i]+'× linjeindsats'));table.append(p);});stage.append(table);$('#game-content').replaceChildren(stage);
}
function renderRoulette(table){
 const stage=element('div','game-stage');const layout=element('div','roulette-layout');const wrap=element('div','wheel-wrap');
 const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 320 320');svg.classList.add('roulette-wheel');svg.setAttribute('aria-label','Roulettehjul');
 wheel.forEach((n,i)=>{const a=(i-.5)*2*Math.PI/37-Math.PI/2,b=(i+.5)*2*Math.PI/37-Math.PI/2;const path=document.createElementNS(ns,'path');path.setAttribute('d',`M160 160 L${160+153*Math.cos(a)} ${160+153*Math.sin(a)} A153 153 0 0 1 ${160+153*Math.cos(b)} ${160+153*Math.sin(b)}Z`);path.setAttribute('fill',n===0?'#448569':red.has(n)?'#a54d44':'#1a2b29');path.setAttribute('stroke','#c5ad74');path.setAttribute('stroke-width','1');const text=document.createElementNS(ns,'text');const angle=i*2*Math.PI/37-Math.PI/2;text.setAttribute('x',160+132*Math.cos(angle));text.setAttribute('y',164+132*Math.sin(angle));text.setAttribute('text-anchor','middle');text.setAttribute('fill','#fff5dc');text.setAttribute('font-size','10');text.textContent=n;svg.append(path,text);});
 const center=element('div','wheel-center',table==='duck'?'':'F');if(table==='duck')center.append(symbol('duck-yellow'));wrap.append(svg,center);layout.append(wrap);
 const betting=element('div');const board=element('div','roulette-board');
 function betButton(label,kind,value,cls=''){const el=button(label,cls,()=>addBet(kind,value));el.dataset.bet=kind+':'+value;return el;}
 board.append(betButton('0','number',0,'zero'));
 for(let row=3;row>=1;row--)for(let col=0;col<12;col++){const n=col*3+row;board.append(betButton(String(n),'number',n,red.has(n)?'red':''));}
 betting.append(board);const outside=element('div','outside-bets');[['1–18','range','low'],['PAIR','parity','even'],['ROUGE','color','red'],['NOIR','color','black'],['IMPAIR','parity','odd'],['19–36','range','high'],['1–12','dozen',1],['13–24','dozen',2],['25–36','dozen',3],['Kolonne 1','column',1],['Kolonne 2','column',2],['Kolonne 3','column',3]].forEach(([text,kind,value])=>outside.append(betButton(text,kind,value,value==='red'?'red-bet':'')));betting.append(outside);
 const chips=element('div','chip-picker');[20,50,100,200,500].forEach(amount=>{const b=button(String(amount),'chip'+(state.chip===amount?' active':''),()=>{state.chip=amount;chips.querySelectorAll('button').forEach(el=>el.classList.toggle('active',el===b));});b.setAttribute('aria-label',amount+' mønter pr. klik');chips.append(b);});betting.append(chips);
 const slip=element('div','roulette-slip','Klik på bordet for at placere mønter.');slip.id='roulette-slip';betting.append(slip);const controls=element('div','roulette-footer');controls.append(button('Ryd bordet','button secondary',()=>{state.bets=[];updateSlip();}),button('Drej hjulet ↻','button gold',()=>play('roulette',{table,bets:state.bets.map(b=>({...b}))},async data=>{const target=(360-wheel.indexOf(data.number)*360/37)%360;state.rotation+=1440+(target-state.rotation%360+360)%360;svg.style.transform=`rotate(${state.rotation}deg)`;await wait(2350);showResult(data);$('#game-result').textContent='Kuglen landede på '+data.number+' · '+resultText(data);})));betting.append(controls);layout.append(betting);stage.append(layout);const result=element('div','game-result','Vælg en jeton og placér dine indsatser.');result.id='game-result';result.setAttribute('aria-live','polite');stage.append(result,element('p','rules-inline','Op til 20 placeringer og 5.000 mønter pr. runde. Tal giver 36×, dusin/kolonne 3×, og simple chancer 2× inkl. indsats. Nul taber på alle simple chancer.'));$('#game-content').replaceChildren(stage);state.rotation=0;
}
function addBet(kind,value){if(state.busy)return;const found=state.bets.find(b=>b.kind===kind&&b.value===value);if((found?found.amount:0)+state.chip>1000||(!found&&state.bets.length>=20)||state.bets.reduce((s,b)=>s+b.amount,0)+state.chip>5000){toast('Maks. 1.000 pr. placering, 20 placeringer og 5.000 pr. runde.',true);return;}if(found)found.amount+=state.chip;else state.bets.push({kind,value,amount:state.chip});updateSlip();}
function updateSlip(){document.querySelectorAll('[data-bet]').forEach(el=>{el.querySelector('.board-badge')?.remove();const bet=state.bets.find(b=>b.kind+':'+b.value===el.dataset.bet);el.classList.toggle('selected',Boolean(bet));if(bet)el.append(element('span','board-badge',money(bet.amount)));});$('#roulette-slip').textContent=state.bets.length?state.bets.length+' placeringer · samlet indsats '+money(state.bets.reduce((s,b)=>s+b.amount,0))+' mønter':'Klik på bordet for at placere mønter.';}
function card(value){if(value===null)return element('div','playing-card card-back','F');const suits=['♠','♥','♣','♦'];const suit=Math.floor(value/13);const el=element('div','playing-card'+(suit%2?' red-suit':''),['A','2','3','4','5','6','7','8','9','10','J','Q','K'][value%13]);el.append(element('span','',suits[suit]));return el;}
function renderBlackjack(){
 if(state.game!=='blackjack')return;const game=state.data.blackjack,active=game?.status==='playing';
 const stage=element('div','game-stage'),felt=element('div','blackjack-felt');
 [['DEALER',game?.dealer,game?.dealer_total],['DIG',game?.player,game?.player_total]].forEach(([name,cards,total],i)=>{if(i)felt.append(element('div','table-brand','BLACKJACK CLUB'));felt.append(element('p','hand-title',name+(cards?' · '+total+(i===0&&active?' + skjult kort':''):'')));const hand=element('div','card-hand');if(cards)cards.forEach(c=>hand.append(card(c)));else hand.append(element('div','empty-card','♠'),element('div','empty-card','♧'));felt.append(hand);});stage.append(felt);
 const labels={blackjack:'Blackjack!',dealer_blackjack:'Dealer har blackjack.',bust:'Du kom over 21.',win:'Du vandt!',push:'Lige spil. Indsatsen er tilbage.',lose:'Dealer vandt.'};
 const result=element('div','game-result',active?'Træk et kort, stå, eller fordobl på de første to kort.':game?(labels[game.result]+' '+resultText(game)):'Vælg din indsats, og få dine kort.');result.id='game-result';result.setAttribute('aria-live','polite');stage.append(result);
 const controls=element('div','bet-controls');const receive=async data=>{state.data.blackjack=data;renderBlackjack();};
 if(active){const actions=element('div','blackjack-actions');[['hit','Kort +'],['stand','Stå'],['double','Fordobl']].forEach(([action,title])=>{const b=button(title,'button '+(action==='hit'?'gold':'secondary'),()=>play('blackjack',{action,round_id:game.round_id},receive));b.disabled=state.busy||(action==='double'&&(!game.can_double||state.data.user.balance<game.bet));actions.append(b);});controls.append(actions);}else controls.append(betSelect([20,50,100,200,500,1000]),button('Giv kort ♠','button gold',()=>play('blackjack',{action:'start',bet:Number($('#bet').value)},receive)));
 stage.append(controls,element('p','rules-inline','Dealer står på alle 17. Blackjack giver 3:2 plus indsatsen tilbage. Fordobling giver ét kort. Ingen split eller forsikring. Din hånd gemmes automatisk.'));$('#game-content').replaceChildren(stage);
}
function rules(){const content=$('#rules-content');content.replaceChildren();[['Virtuelle mønter','Du får 5.000 startmønter og 1.000 ved dagens første besøg (Europe/Copenhagen). Mønterne kan ikke købes eller udbetales.'],['Spilleautomater','Indsatsen deles mellem tre vandrette linjer. Tre ens symboler vinder; wild erstatter alle symboler. Gevinsttabellen viser multiplikator pr. linje, inklusive indsats.'],['Roulette','Europæisk hjul med 0–36. Et tal giver 36×, dusin og kolonne 3×, rød/sort, lige/ulige og høj/lav 2×, inklusive indsats. Nul vinder kun på nul. Begge borde har samme regler.'],['Blackjack','Kom nærmest 21 uden at gå over. Es tæller 1 eller 11. Dealer står på 17, også blød 17. Blackjack betaler 3:2; almindelig gevinst 1:1. Lige spil giver indsatsen tilbage. Fordobling er kun mulig på de første to kort og giver ét kort. Ingen split eller forsikring.']].forEach(([title,text])=>content.append(element('h3','',title),element('p','',text)));$('#rules-dialog').showModal();}
document.querySelectorAll('[data-nav]').forEach(el=>el.onclick=()=>navigate(el.dataset.nav));
document.querySelectorAll('[data-filter]').forEach(el=>el.onclick=()=>filter(el.dataset.filter));
document.querySelectorAll('[data-open]').forEach(el=>el.onclick=()=>openGame(el.dataset.open));
document.querySelectorAll('[data-close]').forEach(el=>el.onclick=()=>document.getElementById(el.dataset.close).close());
$('#rules-open').onclick=rules;$('#game-rules').onclick=rules;$('#account-button').onclick=()=>$('#account-dialog').showModal();
$('#logout').onclick=async()=>{if(state.busy)return;try{await api('/api/logout',{});location.assign('/login');}catch(error){toast(error.message,true);}};
refresh().then(()=>{loadPending();if(state.pending)toast('En runde afventer bekræftelse. Hent resultatet, før du spiller videre.',true,recover);}).catch(error=>toast('Saldoen kunne ikke hentes: '+error.message,true,()=>location.reload()));
