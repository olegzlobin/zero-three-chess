const boardEl = document.getElementById('board');
const turnEl = document.getElementById('turn');
const statusEl = document.getElementById('status');
const errEl = document.getElementById('err');
const newGameBtn = document.getElementById('newGame');
const copyPgnBtn = document.getElementById('copyPgn');
const exportPgnBtn = document.getElementById('exportPgn');
const whiteHumanBtn = document.getElementById('whiteHuman');
const whiteRandomBtn = document.getElementById('whiteRandom');
const whiteMaterialBtn = document.getElementById('whiteMaterial');
const whitePositionalBtn = document.getElementById('whitePositional');
const blackHumanBtn = document.getElementById('blackHuman');
const blackRandomBtn = document.getElementById('blackRandom');
const blackMaterialBtn = document.getElementById('blackMaterial');
const blackPositionalBtn = document.getElementById('blackPositional');
const depthButtons = {
  1: document.getElementById('depth1'),
  2: document.getElementById('depth2'),
  3: document.getElementById('depth3'),
  4: document.getElementById('depth4'),
  5: document.getElementById('depth5'),
  6: document.getElementById('depth6'),
  7: document.getElementById('depth7'),
  8: document.getElementById('depth8'),
};
const evalMetaEl = document.getElementById('evalMeta');
const evalFillEl = document.getElementById('evalFill');
const thinkingEl = document.getElementById('thinking');
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

  if(typeof state.eval_cp === 'number'){
    const cpForWhite = state.eval_cp;
    const pawns = (cpForWhite / 100).toFixed(1);
    const sign = cpForWhite > 0 ? '+' : '';
    const depth = typeof state.eval_depth === 'number' ? state.eval_depth : null;
    const nodes = typeof state.eval_nodes === 'number' ? state.eval_nodes : null;
    const nodesK = nodes !== null ? (nodes / 1000).toFixed(1) + 'k' : '—';
    const depthText = depth !== null ? depth.toString() : '—';
    evalMetaEl.textContent = `${sign}${pawns}  ·  depth ${depthText}  ·  ${nodesK} nodes`;

    const capped = Math.max(-300, Math.min(300, cpForWhite));
    const t = (capped + 300) / 600; // 0..1
    evalFillEl.style.width = `${t * 100}%`;
  }else{
    evalMetaEl.textContent = '—';
    evalFillEl.style.width = '50%';
  }

  const tc = state.turn_color;
  const sideKind = tc === 'white' ? state.white_kind : state.black_kind;
  const engineToMove = !state.finished && sideKind !== 'human';
  if(thinkingEl){
    if(engineToMove){
      thinkingEl.textContent = 'Компьютер думает...';
      thinkingEl.classList.add('thinking-on');
    }else{
      thinkingEl.textContent = '';
      thinkingEl.classList.remove('thinking-on');
    }
  }

  // подсветка конфигурации игроков
  const whiteKind = state.white_kind;
  const blackKind = state.black_kind;

  [whiteHumanBtn, whiteRandomBtn, whiteMaterialBtn, whitePositionalBtn,
   blackHumanBtn, blackRandomBtn, blackMaterialBtn, blackPositionalBtn].forEach(btn => {
    if(btn) btn.classList.remove('side-btn-active', 'engine-btn-active');
  });

  if(whiteKind === 'human'){
    whiteHumanBtn.classList.add('side-btn-active');
  }else if(whiteKind === 'random'){
    whiteRandomBtn.classList.add('engine-btn-active');
  }else if(whiteKind === 'material'){
    whiteMaterialBtn.classList.add('engine-btn-active');
  }else if(whiteKind === 'positional'){
    whitePositionalBtn.classList.add('engine-btn-active');
  }

  if(blackKind === 'human'){
    blackHumanBtn.classList.add('side-btn-active');
  }else if(blackKind === 'random'){
    blackRandomBtn.classList.add('engine-btn-active');
  }else if(blackKind === 'material'){
    blackMaterialBtn.classList.add('engine-btn-active');
  }else if(blackKind === 'positional'){
    blackPositionalBtn.classList.add('engine-btn-active');
  }

  Object.values(depthButtons).forEach(btn => btn.classList.remove('depth-btn-active'));
  if(typeof state.search_depth === 'number' && depthButtons[state.search_depth]){
    depthButtons[state.search_depth].classList.add('depth-btn-active');
  }

  if(copyPgnBtn){
    copyPgnBtn.disabled = !state.finished;
  }
  if(exportPgnBtn){
    exportPgnBtn.disabled = !state.finished;
  }

  boardEl.innerHTML = '';
  const humanIsWhite = true; // белые всегда внизу

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
        if(lastState){
          const tc = lastState.turn_color;
          const sideKind = tc === 'white' ? lastState.white_kind : lastState.black_kind;
          if(!lastState.finished && sideKind !== 'human') return;
        }
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

async function fetchPgnText(){
  const res = await fetch('/api/pgn');
  const ct = res.headers.get('content-type') || '';
  if(!res.ok){
    let msg = `HTTP ${res.status}`;
    if(ct.includes('json')){
      const data = await res.json().catch(() => ({}));
      if(data && data.error) msg = data.error;
    }
    throw new Error(msg);
  }
  return res.text();
}

if(copyPgnBtn){
  copyPgnBtn.addEventListener('click', async () => {
    if(!lastState || !lastState.finished) return;
    const label = copyPgnBtn.textContent;
    try{
      const text = await fetchPgnText();
      await navigator.clipboard.writeText(text);
      errEl.textContent = '';
      copyPgnBtn.textContent = 'Скопировано';
      setTimeout(() => { copyPgnBtn.textContent = label; }, 1500);
    }catch(e){
      errEl.textContent = e.message;
    }
  });
}

if(exportPgnBtn){
  exportPgnBtn.addEventListener('click', async () => {
    if(!lastState || !lastState.finished) return;
    try{
      const text = await fetchPgnText();
      const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'game.pgn';
      a.click();
      URL.revokeObjectURL(url);
    }catch(e){
      errEl.textContent = e.message;
    }
  });
}

promoCancelBtn.addEventListener('click', () => {
  promoBackdrop.style.display = 'none';
  promoTarget = null;
});

function bindPlayerButton(btn, color, kind){
  if(!btn) return;
  btn.addEventListener('click', async () => {
    try{
      if(busy) return;
      busy = true;
      boardEl.classList.add('busy');
      const st = await api('/api/set-player', {color, kind});
      render(st);
    }catch(e){
      errEl.textContent = e.message;
    }finally{
      busy = false;
      boardEl.classList.remove('busy');
    }
  });
}

bindPlayerButton(whiteHumanBtn, 'white', 'human');
bindPlayerButton(whiteRandomBtn, 'white', 'random');
bindPlayerButton(whiteMaterialBtn, 'white', 'material');
bindPlayerButton(whitePositionalBtn, 'white', 'positional');
bindPlayerButton(blackHumanBtn, 'black', 'human');
bindPlayerButton(blackRandomBtn, 'black', 'random');
bindPlayerButton(blackMaterialBtn, 'black', 'material');
bindPlayerButton(blackPositionalBtn, 'black', 'positional');

Object.entries(depthButtons).forEach(([depthStr, btn]) => {
  const depthVal = parseInt(depthStr, 10);
  btn.addEventListener('click', async () => {
    try{
      if(busy) return;
      busy = true;
      boardEl.classList.add('busy');
      const st = await api('/api/set-depth', {depth: depthVal});
      render(st);
    }catch(e){
      errEl.textContent = e.message;
    }finally{
      busy = false;
      boardEl.classList.remove('busy');
    }
  });
});

refresh();
setInterval(() => { fetch('/api/ping').catch(() => {}); }, 1500);
setInterval(() => { refresh().catch(() => {}); }, 1000);
