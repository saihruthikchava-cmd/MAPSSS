const map=L.map('map').setView([16.5062,80.6480],13);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap contributors'}).addTo(map);
const $=id=>document.getElementById(id);let chosenPoint=null,chosenMarker=null,startMarker=null,endMarker=null,routeLayers=[],hazardMarkers=[],allHazards=[],currentRoutes=[];
const colors={'Poor lighting':'#e6a84c','Waterlogging':'#4e91c7','Accident spot':'#df735d','Road damage / obstruction':'#9a7bca','Isolated area':'#5f8f79','Unsafe crossing':'#d66d9b','Other':'#89958e'};
function msg(el,text,error=false){el.textContent=text;el.classList.toggle('error',error)}
function parseCoords(t){const m=t.trim().match(/^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$/);if(!m)return null;const lat=+m[1],lon=+m[2];return lat>=-90&&lat<=90&&lon>=-180&&lon<=180?{lat,lon}:null}
async function geocode(t){const c=parseCoords(t);if(c)return c;const r=await fetch('https://nominatim.openstreetmap.org/search?format=json&limit=1&q='+encodeURIComponent(t));if(!r.ok)throw Error('Location search is temporarily unavailable.');const a=await r.json();if(!a.length)throw Error('Location not found. Try a landmark or coordinates.');return{lat:+a[0].lat,lon:+a[0].lon}}
function setupAutocomplete(inputId,listId){const input=$(inputId),list=$(listId);let timer,items=[],active=-1,controller;
function close(){list.classList.remove('open');list.replaceChildren();items=[];active=-1}
function choose(item){input.value=item.display_name;input.dataset.lat=item.lat;input.dataset.lon=item.lon;close()}
function render(results){items=results;list.replaceChildren();if(!results.length){close();return}results.forEach((it,i)=>{const b=document.createElement('button');b.type='button';b.className='suggestion'+(i===active?' active':'');b.setAttribute('role','option');const pin=document.createElement('span');pin.className='suggestion-pin';pin.textContent='⌖';const text=document.createElement('span');text.className='suggestion-text';const strong=document.createElement('strong');const parts=(it.display_name||'').split(',');strong.textContent=parts.shift()||it.display_name;const small=document.createElement('small');small.textContent=parts.join(',').trim();text.append(strong,small);b.append(pin,text);b.addEventListener('click',()=>choose(it));list.append(b)});list.classList.add('open')}
input.addEventListener('input',()=>{delete input.dataset.lat;delete input.dataset.lon;clearTimeout(timer);const q=input.value.trim();if(q.length<3){close();return}timer=setTimeout(async()=>{try{if(controller)controller.abort();controller=new AbortController();const r=await fetch('https://nominatim.openstreetmap.org/search?format=json&addressdetails=1&limit=5&q='+encodeURIComponent(q),{signal:controller.signal});if(r.ok)render(await r.json())}catch(e){if(e.name!=='AbortError')close()}},350)});
input.addEventListener('keydown',e=>{if(!list.classList.contains('open'))return;if(e.key==='ArrowDown'){e.preventDefault();active=Math.min(active+1,items.length-1);render(items)}else if(e.key==='ArrowUp'){e.preventDefault();active=Math.max(0,active-1);render(items)}else if(e.key==='Enter'&&active>=0){e.preventDefault();choose(items[active])}else if(e.key==='Escape')close()});document.addEventListener('click',e=>{if(!e.target.closest('.field-content'))close()})}
setupAutocomplete('start','startSuggestions');setupAutocomplete('destination','endSuggestions');
document.querySelectorAll('[data-clear]').forEach(b=>b.onclick=()=>{const i=$(b.dataset.clear);i.value='';delete i.dataset.lat;delete i.dataset.lon;i.focus()});
$('swapBtn').onclick=()=>{const a=$('start'),b=$('destination'),v=a.value;a.value=b.value;b.value=v;for(const k of ['lat','lon']){const t=a.dataset[k];a.dataset[k]=b.dataset[k]||'';b.dataset[k]=t||''}};
function clearRoutes(){routeLayers.forEach(l=>map.removeLayer(l));routeLayers=[];if(startMarker)map.removeLayer(startMarker);if(endMarker)map.removeLayer(endMarker);startMarker=endMarker=null;currentRoutes=[]}
function distance(m){return m>=1000?(m/1000).toFixed(1)+' km':Math.round(m)+' m'}function duration(s){const n=Math.round(s/60);return n<60?n+' min':Math.floor(n/60)+' hr '+n%60+' min'}
$('routeBtn').onclick=async()=>{const a=$('start').value.trim(),b=$('destination').value.trim();if(!a||!b){msg($('routeMessage'),'Enter both a starting point and a destination.',true);return}const btn=$('routeBtn');btn.disabled=true;btn.querySelector('span').textContent='Finding routes…';$('routesList').replaceChildren();clearRoutes();
try{const [s,e]=await Promise.all([geocode(a),geocode(b)]);const url=`https://router.project-osrm.org/route/v1/driving/${s.lon},${s.lat};${e.lon},${e.lat}?overview=full&geometries=geojson&alternatives=3&steps=false`;const r=await fetch(url);if(!r.ok)throw Error('Routing service is unavailable. Try again later.');const d=await r.json();if(d.code!=='Ok'||!d.routes?.length)throw Error('No driving route found.');startMarker=L.marker([s.lat,s.lon]).addTo(map).bindPopup('Starting point');endMarker=L.marker([e.lat,e.lon]).addTo(map).bindPopup('Destination');let routes=d.routes.slice();const pref=$('routePreference').value;if(pref==='shortest')routes.sort((x,y)=>x.distance-y.distance);if(pref==='fastest')routes.sort((x,y)=>x.duration-y.duration);currentRoutes=routes;
routes.forEach((rt,i)=>{const layer=L.polyline(rt.geometry.coordinates.map(p=>[p[1],p[0]]),{color:['#176b58','#e6a84c','#668bd2'][i%3],weight:i===0?6:4,opacity:i===0?.95:.65}).addTo(map);routeLayers.push(layer);if(!$('showRoutes').checked&&i>0)map.removeLayer(layer);const row=document.createElement('div');row.className='route-option'+(i===0?' active':'');const info=document.createElement('div'),title=document.createElement('strong'),sub=document.createElement('span');title.textContent=i===0?'★ Suggested route':`Alternative ${i}`;sub.textContent=distance(rt.distance)+' · '+duration(rt.duration);info.append(title,sub);const view=document.createElement('button');view.textContent='View';view.onclick=()=>{map.fitBounds(layer.getBounds(),{padding:[30,30]});document.querySelectorAll('.route-option').forEach(x=>x.classList.remove('active'));row.classList.add('active')};row.append(info,view);$('routesList').append(row)});map.fitBounds(routeLayers[0].getBounds(),{padding:[30,30]});msg($('routeMessage'),`Found ${routes.length} route option(s). Estimates do not use live traffic.`);saveRecent(a,b)
}catch(e){msg($('routeMessage'),e.message||'Could not calculate route.',true)}finally{btn.disabled=false;btn.querySelector('span').textContent='Find my route'}};
$('routePreference').onchange=()=>{if($('start').value.trim()&&$('destination').value.trim())$('routeBtn').click()};
$('showRoutes').onchange=()=>routeLayers.forEach((l,i)=>{if($('showRoutes').checked||i===0)l.addTo(map);else map.removeLayer(l)});
function locate(){if(!navigator.geolocation){msg($('routeMessage'),'Location access is not supported.',true);return}msg($('routeMessage'),'Finding your location…');navigator.geolocation.getCurrentPosition(p=>{const lat=p.coords.latitude,lon=p.coords.longitude;$('start').value=lat.toFixed(6)+', '+lon.toFixed(6);map.setView([lat,lon],15);L.circleMarker([lat,lon],{radius:8,color:'#176b58',fillOpacity:.8}).addTo(map).bindPopup('Your current location').openPopup();msg($('routeMessage'),'Current location added as the starting point.')},()=>msg($('routeMessage'),'Location permission denied or unavailable. Enter a location manually.',true),{enableHighAccuracy:true,timeout:10000})}
$('locateBtn').onclick=locate;$('headerLocate').onclick=locate;
map.on('click',e=>{chosenPoint={lat:e.latlng.lat,lon:e.latlng.lng};$('selectedLocation').replaceChildren();const i=document.createElement('span'),t=document.createElement('span');i.textContent='⌖';t.textContent=`Selected ${chosenPoint.lat.toFixed(5)}, ${chosenPoint.lon.toFixed(5)}`;$('selectedLocation').append(i,t);if(chosenMarker)map.removeLayer(chosenMarker);chosenMarker=L.marker(e.latlng).addTo(map).bindPopup('Selected report location').openPopup();msg($('reportMessage'),'')});
$('description').oninput=()=>$('charCount').textContent=$('description').value.length+'/500';
$('reportBtn').onclick=async()=>{if(!chosenPoint){msg($('reportMessage'),'Click the map to choose the hazard location.',true);return}const payload={type:$('hazardType').value,description:$('description').value.trim(),lat:chosenPoint.lat,lon:chosenPoint.lon};$('reportBtn').disabled=true;try{const r=await fetch('/api/hazards',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),d=await r.json();if(!r.ok)throw Error(d.error||'Could not save report.');$('description').value='';$('charCount').textContent='0/500';chosenPoint=null;if(chosenMarker)map.removeLayer(chosenMarker);chosenMarker=null;$('selectedLocation').textContent='Click the map to choose a location';msg($('reportMessage'),'Report submitted. Thanks for helping your community!');await loadHazards()}catch(e){msg($('reportMessage'),e.message||'Could not submit report.',true)}finally{$('reportBtn').disabled=false}};
$('hazardFilter').onchange=renderHazards;
function renderHazards(){hazardMarkers.forEach(m=>map.removeLayer(m));hazardMarkers=[];$('hazardList').replaceChildren();const filter=$('hazardFilter').value,items=allHazards.filter(h=>filter==='all'||h.type===filter);$('hazardCount').textContent=items.length;if(!items.length){const p=document.createElement('p');p.className='muted';p.textContent=allHazards.length?'No reports match this category.':'No reports yet. Be the first to share a local hazard.';$('hazardList').append(p);return}
items.forEach(h=>{const color=colors[h.type]||'#89958e',marker=L.circleMarker([h.lat,h.lon],{radius:8,color,fillColor:color,fillOpacity:.85,weight:2});if($('showHazards').checked){marker.addTo(map);const pop=document.createElement('div'),strong=document.createElement('strong'),p=document.createElement('p');strong.textContent=h.type;p.textContent=h.description||'No additional details.';pop.append(strong,p);marker.bindPopup(pop);hazardMarkers.push(marker)}const item=document.createElement('div');item.className='hazard-item';item.tabIndex=0;const ico=document.createElement('span');ico.className='hazard-icon';ico.textContent=({'Poor lighting':'☼','Waterlogging':'≈','Accident spot':'!','Road damage / obstruction':'⚒','Isolated area':'⌖','Unsafe crossing':'↔','Other':'•'})[h.type]||'•';const copy=document.createElement('div');copy.className='hazard-copy';const title=document.createElement('strong'),desc=document.createElement('p');title.textContent=h.type;desc.textContent=h.description||`${Number(h.lat).toFixed(4)}, ${Number(h.lon).toFixed(4)}`;copy.append(title,desc);item.append(ico,copy);const focus=()=>{map.setView([h.lat,h.lon],16);if($('showHazards').checked)marker.openPopup()};item.onclick=focus;item.onkeydown=e=>{if(e.key==='Enter')focus()};$('hazardList').append(item)})}
async function loadHazards(){try{allHazards=await(await fetch('/api/hazards')).json();renderHazards()}catch{$('hazardList').textContent='Could not load reports. Refresh to retry.'}}
$('zoomToReports').onclick=()=>{const pts=allHazards.map(h=>[h.lat,h.lon]);if(pts.length)map.fitBounds(L.latLngBounds(pts),{padding:[30,30],maxZoom:15});else msg($('routeMessage'),'No hazard reports are available yet.')};
$('resetMap').onclick=()=>{clearRoutes();map.setView([16.5062,80.6480],13)};
$('fullscreenBtn').onclick=async()=>{try{const el=document.querySelector('.map-card');if(!document.fullscreenElement)await el.requestFullscreen();else await document.exitFullscreen();setTimeout(()=>map.invalidateSize(),250)}catch{msg($('routeMessage'),'Fullscreen is not available in this browser.')}};
function saveRecent(a,b){let list=[];try{list=JSON.parse(localStorage.getItem('waywiseRecent')||'[]')}catch{}list=[{a,b},...list.filter(x=>x.a!==a||x.b!==b)].slice(0,4);localStorage.setItem('waywiseRecent',JSON.stringify(list));renderRecent()}
function renderRecent(){let list=[];try{list=JSON.parse(localStorage.getItem('waywiseRecent')||'[]')}catch{}const wrap=$('recentWrap'),box=$('recentSearches');box.replaceChildren();if(!list.length){wrap.classList.add('hidden');return}wrap.classList.remove('hidden');list.forEach(x=>{const b=document.createElement('button');b.className='recent-chip';b.textContent=x.a+' → '+x.b;b.title=b.textContent;b.onclick=()=>{$('start').value=x.a;$('destination').value=x.b;$('routeBtn').click()};box.append(b)})}
$('clearRecent').onclick=()=>{localStorage.removeItem('waywiseRecent');renderRecent()};renderRecent();loadHazards();


// Feedback is stored in the local SQLite database through the Flask API.
const feedbackMessage = $('feedbackMessage');
if (feedbackMessage) {
  feedbackMessage.addEventListener('input', () => {
    $('feedbackCharCount').textContent = `${feedbackMessage.value.length}/1000`;
  });
}
const feedbackForm = $('feedbackForm');
if (feedbackForm) {
  feedbackForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submit = $('feedbackSubmit');
    submit.disabled = true;
    const payload = {
      category: $('feedbackCategory').value,
      rating: Number($('feedbackRating').value),
      message: feedbackMessage.value.trim()
    };
    try {
      const response = await fetch('/api/feedback', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not save feedback.');
      feedbackForm.reset();
      $('feedbackCharCount').textContent = '0/1000';
      msg($('feedbackStatus'), 'Thank you! Your feedback has been saved.');
    } catch (error) {
      msg($('feedbackStatus'), error.message || 'Could not save feedback. Please try again.', true);
    } finally {
      submit.disabled = false;
    }
  });
}

// Floating WayWise chatbot + browser voice assistant (Web Speech API)
(()=>{
  const $id=id=>document.getElementById(id);
  const toggle=$id('chatToggle'),panel=$id('chatPanel'),close=$id('chatClose'),form=$id('chatForm'),input=$id('chatInput'),messages=$id('chatMessages'),mic=$id('voiceMic'),voiceStatus=$id('voiceStatus'),speakToggle=$id('voiceSpeakToggle');
  if(!toggle||!panel||!form||!input||!mic)return;

  const SpeechRecognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  let recognition=null,wantsListening=false,speakReplies=true,submitAfterStop=false,restartTimer=null;
  let finalParts=[],interimText='',conversationHistory=[];

  function openChat(){panel.classList.remove('hidden');toggle.setAttribute('aria-expanded','true');input.focus()}
  function setVoiceStatus(text){if(voiceStatus)voiceStatus.textContent=text}
  function bubble(text,who,extra=''){const el=document.createElement('div');el.className='chat-bubble '+who+(extra?' '+extra:'');el.textContent=text;messages.append(el);messages.scrollTop=messages.scrollHeight;return el}
  function speak(text){if(!speakReplies||!('speechSynthesis'in window)||!text)return;window.speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(text);u.lang='en-IN';u.rate=1;window.speechSynthesis.speak(u)}
  function currentTranscript(){return (finalParts.join(' ')+' '+interimText).replace(/\s+/g,' ').trim()}
  function updateTranscript(){const text=currentTranscript();input.value=text;if(text)setVoiceStatus('Recognized: '+text);else setVoiceStatus('Listening… speak clearly. Your words will appear here.')}
  function resetMic(){mic.classList.remove('recording');mic.setAttribute('aria-pressed','false')}
  function stopListening(submit=false){
    wantsListening=false;submitAfterStop=submit;
    if(restartTimer){clearTimeout(restartTimer);restartTimer=null}
    if(recognition){try{recognition.stop();return}catch(e){recognition=null}}
    resetMic();finishTranscript();
  }
  function finishTranscript(){
    const text=currentTranscript()||input.value.trim();
    recognition=null;resetMic();
    if(submitAfterStop){submitAfterStop=false;if(text){input.value=text;setVoiceStatus('Sending: '+text);send(text)}else{setVoiceStatus('No words were recognized. Check microphone permission and try again.')}}
    else if(text){input.value=text;setVoiceStatus('Speech captured. You can edit the text or press Send.')}
  }
  function startListening(){
    if(!SpeechRecognition){setVoiceStatus('Voice input is not supported by this browser. Use Chrome or Edge, or type your message.');return}
    if(wantsListening){stopListening(true);return}
    if(!window.isSecureContext&&location.hostname!=='localhost'&&location.hostname!=='127.0.0.1'){setVoiceStatus('Microphone access requires HTTPS or localhost. Open the secure website and allow microphone access.');return}
    finalParts=[];interimText='';input.value='';submitAfterStop=false;wantsListening=true;
    if('speechSynthesis'in window)window.speechSynthesis.cancel();setVoiceStatus('Requesting microphone…');launchRecognition();
  }
  function launchRecognition(){
    if(!wantsListening||!SpeechRecognition)return;
    const instance=new SpeechRecognition();recognition=instance;
    instance.lang='en-IN';instance.interimResults=true;instance.continuous=true;instance.maxAlternatives=3;
    instance.onstart=()=>{if(!wantsListening)return;mic.classList.add('recording');mic.setAttribute('aria-pressed','true');setVoiceStatus('Listening… speak now. Tap the microphone again to finish and send.')};
    instance.onresult=e=>{
      // Rebuild transcript from the complete result list. This avoids losing words
      // when a browser changes resultIndex or returns revised interim results.
      const finals=[];let interim=[];
      for(let i=0;i<e.results.length;i++){
        const result=e.results[i];const transcript=(result[0]?.transcript||'').trim();
        if(!transcript)continue;
        if(result.isFinal)finals.push(transcript);else interim.push(transcript);
      }
      finalParts=finals;interimText=interim.join(' ');updateTranscript();
    };
    instance.onerror=e=>{
      const errors={
        'not-allowed':'Microphone permission is blocked. Click the lock icon near the address bar, allow Microphone, then reload.',
        'service-not-allowed':'Speech recognition is blocked by the browser. Try Chrome or Edge.',
        'audio-capture':'No microphone was detected. Check your microphone and Windows input settings.',
        'network':'Speech recognition needs an internet connection. Check your connection and try again.',
        'language-not-supported':'This browser does not support the selected recognition language. Try Chrome or Edge.'
      };
      if(e.error==='not-allowed'||e.error==='service-not-allowed'||e.error==='audio-capture'||e.error==='language-not-supported')wantsListening=false;
      setVoiceStatus(errors[e.error]|| (e.error==='no-speech'?'No speech detected yet. Speak a little louder or closer to the microphone.':'Voice recognition error: '+e.error));
    };
    instance.onend=()=>{
      if(recognition!==instance)return;
      recognition=null;
      if(wantsListening){
        setVoiceStatus(currentTranscript()?'Speech captured so far. Keep speaking…':'Listening paused by browser; restarting microphone…');
        restartTimer=setTimeout(()=>{restartTimer=null;if(wantsListening)launchRecognition()},250);
      }else{finishTranscript()}
    };
    try{instance.start()}catch(e){recognition=null;wantsListening=false;resetMic();setVoiceStatus('Could not start voice input. Reload the page, check microphone permission, and try again.')}
  }
  async function send(text){
    text=String(text||'').trim();if(!text)return;
    if(wantsListening||recognition)stopListening(false);finalParts=[];interimText='';openChat();bubble(text,'user');input.value='';
    const pending=bubble('Thinking…','bot','pending'),sendButton=$id('chatSend'),history=conversationHistory.slice(-8);if(sendButton)sendButton.disabled=true;
    try{const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text,history})});const data=await r.json();if(!r.ok)throw Error(data.error||'The assistant is unavailable right now.');const reply=data.reply||'I could not create a reply. Try again.';pending.textContent=reply;pending.classList.remove('pending');conversationHistory.push({role:'user',content:text},{role:'assistant',content:reply});conversationHistory=conversationHistory.slice(-12);speak(reply);setVoiceStatus(speakReplies?'Reply can be spoken aloud.':'Voice replies are off.')}
    catch(e){pending.textContent=e.message||'Connection issue. Please try again.';pending.classList.remove('pending')}
    finally{if(sendButton)sendButton.disabled=false;messages.scrollTop=messages.scrollHeight}
  }
  function closeChat(){stopListening(false);panel.classList.add('hidden');toggle.setAttribute('aria-expanded','false');toggle.focus()}
  toggle.addEventListener('click',()=>panel.classList.contains('hidden')?openChat():closeChat());close.addEventListener('click',closeChat);
  mic.addEventListener('click',startListening);
  if(!SpeechRecognition){mic.title='Voice input requires a supported browser such as Chrome or Edge';setVoiceStatus('Voice input is not supported in this browser. You can type instead.')}
  if(speakToggle)speakToggle.addEventListener('click',()=>{speakReplies=!speakReplies;speakToggle.textContent=speakReplies?'🔊 Voice on':'🔇 Voice off';speakToggle.setAttribute('aria-pressed',String(speakReplies));if(!speakReplies&&'speechSynthesis'in window)window.speechSynthesis.cancel();setVoiceStatus(speakReplies?'Spoken replies are on.':'Spoken replies are off.')});
  form.addEventListener('submit',e=>{e.preventDefault();const typed=input.value.trim();if(wantsListening||recognition){wantsListening=false;submitAfterStop=false;if(recognition){try{recognition.stop()}catch(err){recognition=null}}resetMic()}send(typed)});
  document.querySelectorAll('[data-chat-prompt]').forEach(b=>b.addEventListener('click',()=>send(b.dataset.chatPrompt)));
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!panel.classList.contains('hidden'))closeChat()});
})();
