'use strict';
let pokerData=null,pokerBusy=false,pokerVisible=false,pokerHostAddress=location.origin,pokerRenderedState=null;
const pokerLabel={waiting:'Venter på spillere',preflop:'Før floppet',flop:'Flop',turn:'Turn',river:'River',finished:'Hånden er afsluttet'};
function openPoker(){
 if(state.busy)return;state.game=null;pokerVisible=true;
 ['lobby','history','game'].forEach(name=>$('#'+name+'-view').classList.add('hidden'));$('#poker-view').classList.remove('hidden');
 document.querySelectorAll('[data-nav]').forEach(el=>el.classList.toggle('active',el.dataset.nav==='poker'));pokerRefresh();
}
document.querySelectorAll('[data-nav],[data-open]').forEach(el=>el.addEventListener('click',()=>{if(el.dataset.nav!=='poker'){pokerVisible=false;$('#poker-view').classList.add('hidden');}}));
function pokerCard(value){return value===null?card(null):card(Math.floor(value/13)*13+(value%13+1)%13);}
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
function renderPoker(){
 const root=$('#poker-content');
 const nextState=JSON.stringify({connected:!!pokerData?.connected,view:pokerData?.view,leaving:pokerData?.leaving,invite_code:pokerData?.invite_code});
 if(nextState===pokerRenderedState&&root.children.length){$('#poker-error')?.remove();return;}
 pokerRenderedState=nextState;root.replaceChildren();
 if(!pokerData?.connected){
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
  invite.append(label,code,button('Kopiér vennekode','button secondary',async()=>{try{await navigator.clipboard.writeText(code.value);toast('Vennekoden er kopieret.');}catch{code.focus();code.select();toast('Markér og kopiér vennekoden.');}}),element('p','quiet','Brug dit offentlige domæne, eller din LAN-adresse på samme net. Del kun koden med venner; bordets vært styrer kort og afregning.'));root.append(invite);
 }
 const felt=element('div','poker-felt');felt.append(element('h2','',pokerLabel[view.stage]||view.stage),element('p','poker-pot','Pulje: '+money(view.pot)+' mønter'));
 const board=element('div','card-hand');view.board.forEach(c=>board.append(pokerCard(c)));if(!view.board.length)board.append(element('p','quiet','Fælleskort kommer efter første indsatsrunde.'));felt.append(board);
 const players=element('div','poker-players');view.players.forEach((player,i)=>{
  if(player.left)return;const seat=element('div','poker-seat'+(view.turn===i?' active':'')+(player.folded?' folded':''));
  seat.append(element('strong','',player.name+(i===view.seat?' (dig)':'')+(i===view.dealer?' · D':'')),element('p','',money(player.stack)+' jetoner · satset '+money(player.bet)));
  const cards=element('div','card-hand');player.cards.forEach(c=>cards.append(pokerCard(c)));seat.append(cards);
  if(player.folded)seat.append(element('span','','Foldet'));if(view.winners.includes(i))seat.append(element('span','positive','Vinder'));players.append(seat);
 });felt.append(players);
 const controls=element('div','poker-controls');const send=(action,amount)=>pokerRequest('/api/poker/action',{op:'action',action,amount,revision:view.revision});
 if(view.turn===view.seat&&!pokerData.leaving){
  const mine=view.players[view.seat],owed=view.current_bet-mine.bet;
  controls.append(button('Fold','button secondary',()=>send('fold')),button(owed?'Kald '+money(Math.min(owed,mine.stack)):'Check','button gold',()=>send(owed?'call':'check')));
  const label=element('label','','Hæv til');const raise=element('input');raise.type='number';raise.min=view.current_bet+view.min_raise;raise.max=mine.stack+mine.bet;raise.step=1;raise.value=raise.min;raise.id='poker-raise';label.append(raise);controls.append(label,button('Hæv','button secondary',()=>send('raise',Number(raise.value))),button('All-in','button secondary',()=>send('allin')));
 }else if(view.stage!=='waiting'&&view.stage!=='finished')controls.append(element('p','quiet','Venter på '+(view.players[view.turn]?.name||'bordet')+' · automatisk fold efter 60 sekunder.'));
 if(view.host&&['waiting','finished'].includes(view.stage))controls.append(button('Start næste hånd','button gold',()=>pokerRequest('/api/poker/action',{op:'start',revision:view.revision})));
 controls.append(button(pokerData.leaving?'Afventer hånden · hent status':'Forlad bordet og få jetoner tilbage','button secondary',()=>pokerRequest('/api/poker/action',{op:'leave',revision:view.revision})));
 felt.append(controls,element('p','quiet','Texas Hold’em · op til 6 spillere · blinds 10/20 · sidepuljer ved all-in. Ingen ekstra indskud midt i hånden.'));root.append(felt);
}
setInterval(()=>{if(pokerVisible&&!document.hidden)pokerRefresh();},2500);
