const boardEl = document.getElementById('board');
const turnEl = document.getElementById('turn');
const statusEl = document.getElementById('status');
const errEl = document.getElementById('err');
const newGameBtn = document.getElementById('newGame');
const playWhiteBtn = document.getElementById('playWhite');
const playBlackBtn = document.getElementById('playBlack');
const iconCache = new Map(); // code -> true/false
const promoBackdrop = document.getElementById('promoBackdrop');
const promoChoicesEl = document.getElementById('promoChoices');
const promoCancelBtn = document.getElementById('promoCancel');
let promoTarget = null;
let lastState = null;
let busy = false;
let refreshInFlight = null;

function sqName(file, rank){ return String.fromCharCode(97+file) + String(rank+1); }

async function api(path, body){
  const res = await fetch(path, body ? {
    method:'POST',
    headers:{'content-type':'application/json'},
    body: JSON.stringify(body),
  } : {});
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = null; }
  if(!res.ok){
    const msg = data && data.error ? data.error : `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

function render(state){
  lastState = state;
  turnEl.textContent = state.turn_text;
  statusEl.textContent = state.status_text;
  errEl.textContent = '';

  if(state.human_color === 'white'){
    playWhiteBtn.classList.add('side-btn-active');
    playBlackBtn.classList.remove('side-btn-active');
  }else if(state.human_color === 'black'){
    playBlackBtn.classList.add('side-btn-active');
    playWhiteBtn.classList.remove('side-btn-active');
  }else{
    playWhiteBtn.classList.remove('side-btn-active');
    playBlackBtn.classList.remove('side-btn-active');
  }

  boardEl.innerHTML = '';
  const humanIsWhite = state.human_color === 'white';

  for(let rIndex=0;rIndex<8;rIndex++){
    const rank = humanIsWhite ? (7 - rIndex) : rIndex;
    for(let fIndex=0;fIndex<8;fIndex++){
      const file = humanIsWhite ? fIndex : (7 - fIndex);
      const light = ((rIndex + fIndex) % 2) === 0;
      const sq = document.createElement('div');
      sq.className = 'sq ' + (light ? 'light' : 'dark');
      const name = sqName(file, rank);
      sq.dataset.square = name;
      const cell = state.pieces[name];
      if(cell){
        sq.textContent = cell.glyph || '';
        if(cell.code){
          sq.dataset.piece = cell.code;
        }
      }else{
        sq.textContent = '';
      }
      if(state.selected === name) sq.classList.add('selected');
      if(state.legal_targets && state.legal_targets.includes(name)){
        sq.classList.add('legal');
      }
      if(cell){
        sq.classList.add('occupied');
      }
      if(state.last_move){
        if(state.last_move.from === name){
          sq.classList.add('last-move-from');
        }
        if(state.last_move.to === name){
          sq.classList.add('last-move-to');
        }
      }
      if(cell && cell.code){
        const code = cell.code;
        const cached = iconCache.get(code);
        const url = `/static/pieces/${code}.png`;

        if(cached === true){
          sq.style.backgroundImage = `url('${url}')`;
          sq.classList.add('icon');
        }else if(cached === false){
          sq.style.backgroundImage = '';
        }else{
          sq.style.backgroundImage = `url('${url}')`;
          const img = new Image();
          img.onload = () => {
            iconCache.set(code, true);
            sq.classList.add('icon');
          };
          img.onerror = () => {
            iconCache.set(code, false);
            sq.style.backgroundImage = '';
          };
          img.src = url;
        }
      }else{
        sq.style.backgroundImage = '';
      }
      sq.addEventListener('click', async () => {
        if(busy) return;
        try{
          busy = true;
          boardEl.classList.add('busy');
          const res = await api('/api/click', {square: name});
          if(res && res.promotion_required){
            promoTarget = name;
            promoChoicesEl.innerHTML = '';
            const fromSq = res.promotion_from;
            let colorCode = 'w';
            if(lastState && lastState.pieces && lastState.pieces[fromSq] && lastState.pieces[fromSq].code){
              colorCode = lastState.pieces[fromSq].code[0] === 'b' ? 'b' : 'w';
            }
            (res.promotion_choices || ['q','r','b','n']).forEach(code => {
              const btn = document.createElement('button');
              const letter = code.toUpperCase();
              const imgCode = colorCode + letter;
              btn.className = 'promo-piece-btn';
              btn.dataset.piece = imgCode;
              btn.textContent = letter;
              btn.setAttribute('aria-label', letter);
              btn.style.backgroundImage = `url('/static/pieces/${imgCode}.png')`;
              btn.addEventListener('click', async () => {
                promoBackdrop.style.display = 'none';
                try{
                  const afterPromo = await api('/api/click', {square: promoTarget, promotion: code});
                  render(afterPromo);
                }finally{
                  promoTarget = null;
                }
              });
              promoChoicesEl.appendChild(btn);
            });
            promoBackdrop.style.display = 'flex';
          }else{
            render(res);
          }
        }catch(e){
          errEl.textContent = e.message;
          errEl.textContent = e.message;
        }finally{
          busy = false;
          boardEl.classList.remove('busy');
        }
      });
      boardEl.appendChild(sq);
    }
  }
}

async function refresh(){
  if(busy) return;
  if(refreshInFlight) return;
  refreshInFlight = (async () => {
    const state = await api('/api/state');
    render(state);
  })();
  try{
    await refreshInFlight;
  }finally{
    refreshInFlight = null;
  }
}

newGameBtn.addEventListener('click', async () => {
  try{
    if(busy) return;
    busy = true;
    boardEl.classList.add('busy');
    const st = await api('/api/new-game', {});
    render(st);
  }catch(e){
    errEl.textContent = e.message;
  }finally{
    busy = false;
    boardEl.classList.remove('busy');
  }
});

promoCancelBtn.addEventListener('click', () => {
  promoBackdrop.style.display = 'none';
  promoTarget = null;
});

playWhiteBtn.addEventListener('click', async () => {
  try{
    if(busy) return;
    busy = true;
    boardEl.classList.add('busy');
    const st = await api('/api/set-side', {color: 'white'});
    render(st);
  }catch(e){
    errEl.textContent = e.message;
  }finally{
    busy = false;
    boardEl.classList.remove('busy');
  }
});

playBlackBtn.addEventListener('click', async () => {
  try{
    if(busy) return;
    busy = true;
    boardEl.classList.add('busy');
    const st = await api('/api/set-side', {color: 'black'});
    render(st);
  }catch(e){
    errEl.textContent = e.message;
  }finally{
    busy = false;
    boardEl.classList.remove('busy');
  }
});

refresh();
setInterval(() => { fetch('/api/ping').catch(() => {}); }, 1500);
