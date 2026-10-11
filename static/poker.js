'use strict';
let pokerData=null,pokerBusy=false,pokerVisible=false,pokerHostAddress=location.origin,pokerRenderedState=null;
let pokerSeenAction=null,pokerNoticeTimer=null;
const pokerLabel={waiting:'Venter på spillere',preflop:'Før floppet',flop:'Flop',turn:'Turn',river:'River',finished:'Hånden er afsluttet'};
function openPoker(){
 if(state.busy)return;state.game=null;pokerVisible=true;
 ['lobby','history','game'].forEach(name=>$('#'+name+'-view').classList.add('hidden'));$('#poker-view').classList.remove('hidden');
 document.querySelectorAll('[data-nav]').forEach(el=>el.classList.toggle('active',el.dataset.nav==='poker'));pokerRefresh();
}
document.querySelectorAll('[data-nav],[data-open]').forEach(el=>el.addEventListener('click',()=>{if(el.dataset.nav!=='poker'){pokerVisible=false;$('#poker-view').classList.add('hidden');}}));
function pokerCard(value,highlight=false){
 const el=value===null?card(null):card(Math.floor(value/13)*13+(value%13+1)%13);
 if(highlight){el.classList.add('poker-best-card');el.setAttribute('aria-label',el.textContent+' · indgår i din bedste hånd');}
 return el;
}
async function pokerRefresh(){
 if(pokerBusy||!state.data||document.activeElement?.closest('#poker-view input,#poker-view textarea'))return;
 pokerBusy=true;
 try{pokerData=await api('/api/poker/state');renderPoker();if(pokerData.returned!==undefined)await refresh();}
 catch(error){if(!$('#poker-content').children.length)renderPoker();pokerError(error.message);}
 finally{pokerBusy=false;}
}
function pokerError(message){let box=$('#poker-error');if(!box){box=element('p','poker-error');box.id='poker-error';$('#poker-content').prepend(box);}box.textContent=message;}
async function pokerRequest(path,body){
 if(pokerBusy)return;pokerBusy=true;
 try{pokerData=await api(path,body);renderPoker();await refresh();}
 catch(error){pokerError(error.message);}
 finally{pokerBusy=false;}
}
function invitation(code){return 'FC1.'+btoa(JSON.stringify({url:pokerHostAddress,code}));}
function pokerFeedback(view){
 if(view.stage==='finished'){
  document.querySelectorAll('.poker-seat.winner').forEach(seat=>{
   const confetti=element('div','poker-confetti');confetti.setAttribute('aria-hidden','true');
   for(let i=0;i<22;i++){const piece=element('i');piece.style.setProperty('--x',(Math.random()*100)+'%');piece.style.setProperty('--drift',(Math.random()*100-50)+'px');piece.style.setProperty('--delay',(-Math.random()*2.8)+'s');piece.style.setProperty('--color',['#efd594','#bce4c6','#e9a292','#fff3d7'][i%4]);confetti.append(piece);}
   seat.append(confetti);
  });
 }
 const events=view.events||[],latest=events.at(-1)?.id||0;
 if(pokerSeenAction===null){pokerSeenAction=latest;return;}
 const fresh=events.filter(event=>event.id>pokerSeenAction&&event.seat!==view.seat);
 pokerSeenAction=Math.max(pokerSeenAction,latest);
 if(fresh.length){
  const words={fold:'foldede',check:'checkede',call:'kaldte',raise:'hævede til',allin:'gik all-in med'};
  const text=fresh.map(event=>{
   const amount=event.action==='raise'?event.bet:event.paid;
   return (view.players[event.seat]?.name||'En spiller')+' '+(words[event.action]||event.action)+(['call','raise','allin'].includes(event.action)?' '+money(amount)+' mønter':'');
  }).join(' · ');
  let notice=$('#poker-action-notice');if(!notice){notice=element('div','poker-action-notice');notice.id='poker-action-notice';notice.setAttribute('role','status');notice.setAttribute('aria-live','polite');$('.poker-felt').append(notice);}
  clearTimeout(pokerNoticeTimer);notice.dataset.hand=String(view.hand_id);notice.textContent=text;notice.classList.remove('fading');
  pokerNoticeTimer=setTimeout(()=>{notice.classList.add('fading');},3000);
 }
}
function renderPoker(){
 const root=$('#poker-content');
 $('#poker-view > .quiet').classList.toggle('hidden',!!pokerData?.connected);
 const nextState=JSON.stringify({connected:!!pokerData?.connected,view:pokerData?.view,leaving:pokerData?.leaving,invite_code:pokerData?.invite_code});
 if(nextState===pokerRenderedState&&root.children.length){$('#poker-error')?.remove();return;}
 const previousNotice=$('#poker-action-notice');
 pokerRenderedState=nextState;root.replaceChildren();
 if(!pokerData?.connected){
  pokerSeenAction=null;clearTimeout(pokerNoticeTimer);
  const panel=element('div','poker-setup');panel.append(element('h2','','Opret et bord eller forbind til en ven'));
  panel.append(button('Opret bord · 1.000 mønter','button gold',async()=>{
   if(pokerBusy)return;pokerBusy=true;
   try{const created=await api('/api/poker/create',{});pokerData=await api('/api/poker/connect',{url:'local',code:created.code});renderPoker();await refresh();}catch(error){pokerError(error.message);}finally{pokerBusy=false;}
  }));
  const form=element('form','poker-connect'),label=element('label','','Vennekode');const input=element('input');input.required=true;input.id='poker-invite';input.placeholder='FC1.…';input.autocomplete='off';label.append(input);form.append(label);
  const submit=element('button','button secondary','Forbind · 1.000 mønter');submit.type='submit';form.append(submit);
  form.onsubmit=event=>{event.preventDefault();try{const text=input.value.trim();if(!text.startsWith('FC1.')||text.length>2000)throw new Error();const invite=JSON.parse(atob(text.slice(4)));pokerRequest('/api/poker/connect',{url:invite.url===location.origin?'local':invite.url,code:invite.code});}catch{pokerError('Indsæt hele vennekoden fra værten.');}};
  panel.append(form,element('p','quiet','Din offentlige installation kan være vært for en ven på en lokal installation. På samme netværk kan værtens lokale IP-adresse bruges.'));
  panel.append(button('Hent eksisterende forbindelse','button secondary',pokerRefresh));root.append(panel);return;
 }
 const view=pokerData.view;if(!view){pokerError('Bordet kunne ikke læses. Prøv igen.');return;}
 if(pokerData.invite_code){
  const invite=element('div','poker-invitation'),label=element('label','','Adresse, vennerne kan nå');const input=element('input');input.value=pokerHostAddress;input.type='url';input.id='poker-host-url';label.append(input);
  const code=element('textarea');code.readOnly=true;code.id='poker-share-code';code.setAttribute('aria-label','Vennekode til bordet');code.value=invitation(pokerData.invite_code);
  input.onchange=()=>{pokerHostAddress=input.value.trim().replace(/\/$/,'');code.value=invitation(pokerData.invite_code);};
  invite.append(label,code,button('Kopiér vennekode','button secondary',async()=>{try{await navigator.clipboard.writeText(code.value);toast('Vennekoden er kopieret.');}catch{code.focus();code.select();toast('Markér og kopiér vennekoden.');}}),element('p','quiet','Del kun koden med venner. Bordets vært styrer kort og afregning.'));
  const sharing=element('details','poker-sharing');sharing.open=view.stage==='waiting'&&view.players.filter(p=>!p.left).length<2;
  sharing.append(element('summary','','Invitér flere'),invite);root.append(sharing);
 }
 const felt=element('div','poker-felt');felt.append(element('h2','',pokerLabel[view.stage]||view.stage),element('p','poker-pot','Pulje: '+money(view.pot)+' mønter'));
 const hint=view.hand_hint,highlighted=new Set(hint?.cards||[]);
 const board=element('div','card-hand');view.board.forEach(c=>board.append(pokerCard(c,highlighted.has(c))));if(!view.board.length)board.append(element('p','quiet','Fælleskort kommer efter første indsatsrunde.'));felt.append(board);
 if(hint){
  const status=element('p','poker-hand-hint','Din hånd: '+hint.label);status.setAttribute('role','status');
  const explanation=hint.plays_board?'Bordet spiller · dine egne kort forbedrer ikke hånden.':hint.complete?'De fem markerede kort er din bedste hånd lige nu.':'Dine startkort · fælleskortene kan forbedre hånden.';
  status.append(element('small','',explanation));felt.append(status);
 }
 const players=element('div','poker-players');players.style.setProperty('--seats',Math.min(3,view.players.filter(p=>!p.left).length));view.players.forEach((player,i)=>{
  if(player.left)return;const seat=element('div','poker-seat'+(view.turn===i?' active':'')+(player.folded?' folded':'')+(view.winners.includes(i)?' winner':''));
  seat.append(element('strong','',player.name+(i===view.seat?' (dig)':'')+(i===view.dealer?' · D':'')),element('p','',money(player.stack)+' jetoner · satset '+money(player.bet)));
  const cards=element('div','card-hand');player.cards.forEach(c=>cards.append(pokerCard(c,i===view.seat&&highlighted.has(c))));seat.append(cards);
  if(player.folded)seat.append(element('span','','Foldet'));if(view.winners.includes(i))seat.append(element('strong','poker-winner-label',view.winners.length>1?'Vinder af en pulje':'Vinder af hånden'));players.append(seat);
 });felt.append(players);
 const controls=element('div','poker-controls');const send=(action,amount)=>pokerRequest('/api/poker/action',{op:'action',action,amount,revision:view.revision});
 if(view.turn===view.seat&&!pokerData.leaving){
  const mine=view.players[view.seat],owed=view.current_bet-mine.bet;
  controls.append(button('Fold','button secondary',()=>send('fold')),button(owed?'Kald '+money(Math.min(owed,mine.stack)):'Check','button gold',()=>send(owed?'call':'check')));
  const label=element('label','','Hæv til');const raise=element('input');raise.type='number';raise.min=view.current_bet+view.min_raise;raise.max=mine.stack+mine.bet;raise.step=1;raise.value=raise.min;raise.id='poker-raise';label.append(raise);controls.append(label,button('Hæv','button secondary',()=>send('raise',Number(raise.value))),button('All-in','button secondary',()=>send('allin')));
 }else if(view.stage!=='waiting'&&view.stage!=='finished')controls.append(element('p','quiet','Venter på '+(view.players[view.turn]?.name||'bordet')+' · automatisk fold efter 60 sekunder.'));
 if(view.host&&['waiting','finished'].includes(view.stage))controls.append(button('Start næste hånd','button gold',()=>pokerRequest('/api/poker/action',{op:'start',revision:view.revision})));
 controls.append(button(pokerData.leaving?'Afventer hånden · hent status':'Forlad bordet og få jetoner tilbage','button secondary',()=>pokerRequest('/api/poker/action',{op:'leave',revision:view.revision})));
 felt.append(controls,element('p','quiet','Texas Hold’em · op til 6 spillere · blinds 10/20 · sidepuljer ved all-in. Ingen ekstra indskud midt i hånden.'));if(previousNotice?.dataset.hand===String(view.hand_id))felt.append(previousNotice);else clearTimeout(pokerNoticeTimer);root.append(felt);pokerFeedback(view);
}
setInterval(()=>{if(pokerVisible&&!document.hidden)pokerRefresh();},2500);
