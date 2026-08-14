const state = {
  library: null, selectedBook: null, level: null,
  queue: [], queueIndex: -1,
  saved: { schema_version: 1, playlists: [] },
  serverPlaylists: false,
  voice: localStorage.getItem('voice') || null,
  bookSort: localStorage.getItem('book-sort') || 'rating',
  keepScrollOnNextRoute: false,
};
const el = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const label = value => value.replace('-', ' ').replace(/\b\w/g, c => c.toUpperCase());
const list = values => `<ul class="compact-list">${values.map(v => `<li>${esc(v.text ?? v)}</li>`).join('')}</ul>`;
const findBook = id => state.library.books.find(book => book.id === id);
// Authors are embedded per book; index them once with their library books attached.
const authorsById = () => {
  if (!state.authorIndex) {
    state.authorIndex = new Map();
    state.library.books.forEach(book => book.authors.forEach(author => {
      if (!state.authorIndex.has(author.id)) state.authorIndex.set(author.id, {...author, books: []});
      state.authorIndex.get(author.id).books.push(book);
    }));
  }
  return state.authorIndex;
};
const findAuthor = id => authorsById().get(id) || null;
const norm = value => String(value ?? '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
const bookByTitle = title => state.library.books.find(book => norm(book.title) === norm(title))
  || state.library.books.find(book => norm(book.title).startsWith(norm(title) + ' '));
const recommendedLevel = book => book.content.editorial.recommended_level;
const bookRating = book => book.content.workflow.status === 'stub'
  ? null
  : book.content.assessment.rating || null;
const compareTitles = (a, b) => a.title.localeCompare(b.title, 'en-GB', {
  sensitivity: 'base', numeric: true,
});
const compareBooks = (a, b) => {
  if (state.bookSort === 'title') return compareTitles(a, b);
  const scoreA = bookRating(a)?.score;
  const scoreB = bookRating(b)?.score;
  if (scoreA == null && scoreB != null) return 1;
  if (scoreA != null && scoreB == null) return -1;
  if (scoreA !== scoreB) return scoreB - scoreA;
  return compareTitles(a, b);
};
const sortedBooks = books => [...books].sort(compareBooks);

// Audio comes in per-voice variants: scripts[level].audio = {voice: {url, seconds}}.
// Playback prefers the chosen voice, then the library default, then anything.
const audioVariants = (book, level) => book?.scripts[level]?.audio || {};
const pickVoice = variants => {
  if (state.voice && variants[state.voice]) return state.voice;
  const fallback = state.library.config.tts.default_voice;
  return variants[fallback] ? fallback : Object.keys(variants)[0] || null;
};
const pickedAudio = (book, level) => {
  const variants = audioVariants(book, level);
  const voice = pickVoice(variants);
  return voice ? { voice, ...variants[voice] } : null;
};
const audioUrl = item => pickedAudio(findBook(item.bookId), item.level)?.url || null;
const hasAudio = (book, level) => Object.keys(audioVariants(book, level)).length > 0;
const levelSeconds = (book, level) => {
  const picked = pickedAudio(book, level);
  if (picked?.seconds) return picked.seconds;
  const script = book.scripts[level];
  const words = script?.words || state.library.config.levels[level]?.target_words || 0;
  return words / state.library.config.base_words_per_minute * 60;
};
const timeLabel = seconds => seconds < 90 ? `${Math.round(seconds)} sec` : `${Math.round(seconds / 60)} min`;
const featuredItem = book => {
  const playable = Object.keys(book.scripts).filter(level => hasAudio(book, level));
  if (!playable.length) return null;
  const level = playable.includes(recommendedLevel(book))
    ? recommendedLevel(book)
    : playable.sort((a, b) => levelSeconds(book, b) - levelSeconds(book, a))[0];
  return {bookId: book.id, level};
};

async function start() {
  try {
    state.library = await fetch('data/library.json').then(response => {
      if (!response.ok) throw new Error('Run ./bookflow serve to build the library data.');
      return response.json();
    });
    await loadPlaylists();
    if (!['rating', 'title'].includes(state.bookSort)) state.bookSort = 'rating';
    el('book-sort').value = state.bookSort;
    state.selectedBook = sortedBooks(state.library.books)[0] || null;
    const speeds = state.library.config.playback_speeds;
    const defaultSpeed = state.library.config.default_playback_speed || 1;
    el('speed').innerHTML = speeds.map(speed =>
      `<option value="${speed}" ${speed === defaultSpeed ? 'selected' : ''}>${speed}×</option>`).join('');
    const voiceNames = state.library.config.tts.voices
      || {[state.library.config.tts.default_voice]: state.library.config.tts.default_voice};
    if (!state.voice || !voiceNames[state.voice]) state.voice = state.library.config.tts.default_voice;
    el('voice').innerHTML = Object.entries(voiceNames).map(([id, name]) =>
      `<option value="${id}" ${id === state.voice ? 'selected' : ''}>${esc(name.split(' — ')[0])}</option>`).join('');
    bind();
    window.addEventListener('hashchange', route);
    route();
    renderPlaylist();
  } catch (error) {
    el('book-detail').innerHTML = `<section class="empty"><h1>Library data is not ready</h1><p>${esc(error.message)}</p></section>`;
  }
}

// Hash routes: #book/<id> and #author/<id>. The detail pane renders whichever
// entity the hash names; anything unrecognised falls back to the selected book.
function route() {
  const [type, id] = decodeURIComponent(location.hash.slice(1)).split('/');
  if (type === 'author' && findAuthor(id)) {
    state.view = {type: 'author', id};
  } else if (type === 'book' && findBook(id)) {
    if (state.selectedBook?.id !== id) state.level = null;
    state.selectedBook = findBook(id);
    state.view = {type: 'book', id};
  } else {
    state.view = state.selectedBook ? {type: 'book', id: state.selectedBook.id} : null;
  }
  renderList();
  renderDetail();
}

function renderDetail() {
  if (state.view?.type === 'author') renderAuthor(state.view.id);
  else renderBook();
  if (state.keepScrollOnNextRoute) state.keepScrollOnNextRoute = false;
  else if (location.hash) el('book-detail').scrollIntoView({block: 'start'});
}

function bind() {
  el('search').addEventListener('input', renderList);
  el('book-sort').addEventListener('change', event => {
    state.bookSort = event.target.value;
    localStorage.setItem('book-sort', state.bookSort);
    renderList();
  });
  el('playlist-toggle').addEventListener('click', () => { el('playlist').hidden = false; });
  el('playlist-close').addEventListener('click', () => { el('playlist').hidden = true; });
  el('playlist-clear').addEventListener('click', () => { state.queue = []; state.queueIndex = -1; renderPlaylist(); });
  el('playlist-save').addEventListener('click', saveQueueAsPlaylist);
  el('speed').addEventListener('change', event => { el('audio').playbackRate = Number(event.target.value); });
  el('voice').addEventListener('change', event => {
    state.voice = event.target.value;
    localStorage.setItem('voice', state.voice);
    renderBook();
    const playing = state.queue[state.queueIndex] && !el('audio').paused;
    if (playing) playCurrent();  // position is restored from the saved position
  });
  const audio = el('audio');
  audio.addEventListener('ended', () => {
    localStorage.removeItem(positionKey());
    playNext();
  });
  audio.addEventListener('timeupdate', () => {
    if (audio.currentTime > 5) localStorage.setItem(positionKey(), String(audio.currentTime));
  });
}

function matches(book, query) {
  const haystack = [book.title, ...book.authors.map(a => a.name), ...book.discovery.tag_ids,
    ...book.content.assessment.audience.topics].join(' ').toLowerCase();
  return haystack.includes(query.toLowerCase());
}

function renderList() {
  const query = el('search').value.trim();
  const books = sortedBooks(state.library.books.filter(book => matches(book, query)));
  el('filter-summary').textContent = `${books.length} non-fiction ${books.length === 1 ? 'book' : 'books'}`;
  el('book-list').innerHTML = books.map(book => {
    const featured = featuredItem(book);
    const rating = bookRating(book);
    const chip = featured
      ? `<span class="quickplay" data-quickplay title="Play the ${featured.level === recommendedLevel(book) ? 'recommended' : 'longest available'} brief">▶ ${timeLabel(levelSeconds(book, featured.level))}${featured.level === recommendedLevel(book) ? ' ★' : ''}</span>`
      : '';
    return `
    <button class="book-card" type="button" data-book="${book.id}" aria-current="${state.view?.type !== 'author' && book.id === state.selectedBook?.id}">
      <strong>${esc(book.title)}</strong>
      <span>${esc(book.authors.map(a => a.name).join(', '))}</span>
      ${rating ? `<span class="rating-chip">${rating.score.toFixed(1)}/10</span>` : ''}
      ${chip}
    </button>`;
  }).join('');
  el('book-list').querySelectorAll('[data-book]').forEach(button => button.addEventListener('click', event => {
    const book = state.library.books.find(candidate => candidate.id === button.dataset.book);
    if (event.target.closest('.quickplay')) {
      playItem(featuredItem(book));
      return;
    }
    state.keepScrollOnNextRoute = true;
    if (location.hash === `#book/${book.id}`) { route(); }
    else location.hash = `book/${book.id}`;
    el('book-detail').focus({preventScroll: true});
  }));
  if (!books.length) {
    el('book-detail').replaceChildren(el('empty-state').content.cloneNode(true));
  } else if (!el('book-detail').querySelector('article')) {
    renderDetail();
  }
}

function renderBook() {
  const book = state.selectedBook;
  if (!book) return;
  const c = book.content;
  const authorLinks = book.authors.map(author =>
    `<a class="author-link" href="#author/${esc(author.id)}">${esc(author.name)}</a>`).join(', ');
  const levels = Object.entries(state.library.config.levels);
  const selected = state.level && book.scripts[state.level] ? state.level : null;
  const decision = c.assessment.decision;
  const rating = bookRating(book);
  const rubric = Object.fromEntries(
    (state.library.rating_config?.dimensions || []).map(item => [item.id, item]));
  const sources = book.research.sources;
  // Authorship edges are shown in the byline and Author section; the related
  // list keeps cross-book and cross-author connections only.
  const related = book.relationships
    .filter(relationship => relationship.type !== 'written-by')
    .map(relationship => {
      const otherId = relationship.source_id === book.id ? relationship.target_id : relationship.source_id;
      const entity = state.library.catalog.entities.find(item => item.id === otherId);
      return {...relationship, otherId, entity};
    });
  const relatedItem = item => {
    const name = item.entity?.name || item.otherId;
    const linkedBook = item.entity?.kind !== 'author' && findBook(item.otherId);
    const linkedAuthor = item.entity?.kind === 'author' && findAuthor(item.otherId);
    const title = linkedBook ? `<a href="#book/${esc(item.otherId)}"><strong>${esc(name)}</strong></a>`
      : linkedAuthor ? `<a href="#author/${esc(item.otherId)}"><strong>${esc(name)}</strong></a>`
      : `<strong>${esc(name)}</strong>`;
    return `<li>${title}<span>${esc(label(item.type))} · ${esc(item.description)}</span>${!linkedBook && !linkedAuthor ? '<small>Not yet available in the library</small>' : ''}</li>`;
  };

  el('book-detail').innerHTML = `
    <article>
      <header class="hero">
        <div class="eyebrow">${esc(c.editorial.recommended_level)} recommended · ${esc(c.editorial.compression_fit)} compression fit</div>
        <h1>${esc(book.title)}</h1>
        <div class="byline">${authorLinks} · ${esc(book.bibliography.first_published || 'Date unknown')}</div>
        ${rating ? `<div class="rating-summary"><strong>${rating.score.toFixed(1)}/10</strong><span>${esc(rating.confidence)} confidence · content and ideas</span></div>` : ''}
        <p class="verdict">${esc(c.card.verdict)}</p>
        ${book.workflow.coverage !== 'full-book' ? `<span class="coverage">${esc(book.workflow.coverage)} · not verified against the full book</span>` : ''}
      </header>

      <nav class="level-nav" aria-label="Summary length">
        ${levels.map(([key, level]) => {
          const script = book.scripts[key];
          const recommended = key === recommendedLevel(book);
          const timing = hasAudio(book, key) ? timeLabel(levelSeconds(book, key)) : `${level.target_words} words`;
          return `<button type="button" data-level="${key}" aria-pressed="${selected === key}"
            class="${recommended ? 'recommended' : ''}" ${!script ? 'disabled' : ''}
            title="${esc(level.purpose || '')}${recommended ? ' (recommended for this book)' : ''}">
            ${recommended ? '★ ' : ''}${esc(label(key))}<small> · ${esc(timing)}</small></button>`;
        }).join('')}
      </nav>
      <div id="script-slot">${selected ? scriptPanel(book, selected) : ''}</div>

      <section class="section">
        <h2>What it says</h2>
        <p class="lede">${esc(c.overview.core_argument.text)}</p>
        <p>${esc(c.overview.synopsis.text)}</p>
      </section>

      <section class="section">
        <h2>Main ideas</h2>
        <div class="idea-grid">${c.ideas.map(idea => `
          <article class="idea">
            <h3>${esc(idea.title)}</h3>
            <p>${esc(idea.explanation)}</p>
            ${idea.representative_example ? `<p><strong>Example:</strong> ${esc(idea.representative_example)}</p>` : ''}
            ${idea.caveat ? `<p class="caveat"><strong>Limit:</strong> ${esc(idea.caveat)}</p>` : ''}
          </article>`).join('')}</div>
      </section>

      <section class="section">
        <h2>Your decision</h2>
        <div class="decision-grid">
          <div><h3>Read it if</h3><p>${esc(decision.read_if)}</p></div>
          <div><h3>The brief is enough if</h3><p>${esc(decision.summary_is_enough_if)}</p></div>
          <div><h3>Skip it if</h3><p>${esc(decision.skip_if)}</p></div>
        </div>
        <p><strong>Format:</strong> ${esc(decision.format_advice)}</p>
      </section>

      <details class="section">
        <summary>What it is like to read</summary>
        <dl class="reading-grid">${Object.entries(c.reading_experience)
          .filter(([key]) => !['source_ids', 'basis'].includes(key))
          .map(([key, value]) => `<dt>${esc(label(key.replaceAll('_', '-')))}</dt><dd>${esc(value)}</dd>`).join('')}</dl>
      </details>

      <details class="section">
        <summary>Assessment</summary>
        ${rating ? `
          <div class="rating-panel">
            <div><strong>${rating.score.toFixed(1)}/10</strong><span>${esc(rating.confidence)} confidence</span></div>
            <p>${esc(rating.summary)}</p>
            <dl class="rating-grid">${rating.dimensions.map(item => {
              const configured = rubric[item.id] || {};
              return `<dt>${esc(configured.label || label(item.id))}<small>${configured.weight ? ` · ${Math.round(configured.weight * 100)}%` : ''}</small></dt>
                <dd><strong>${Number(item.score).toFixed(1)}</strong><span>${esc(item.rationale)}</span></dd>`;
            }).join('')}</dl>
          </div>` : ''}
        <h3>Meaning and importance</h3><p>${esc(c.assessment.meaning.text)} ${esc(c.assessment.importance.text)}</p>
        <h3>Lessons</h3>${list(c.assessment.lessons)}
        <h3>Evidence: ${esc(c.assessment.evidence_quality.rating)}</h3>
        ${list(c.assessment.evidence_quality.strengths)}${list(c.assessment.evidence_quality.weaknesses)}
        <h3>Reception</h3><p>${esc(c.assessment.reception.summary)}</p>
        <h3>What readers and reviewers praise</h3>${list(c.assessment.reception.praise)}
        <h3>What they criticise</h3>${list(c.assessment.reception.criticism)}
        <h3>What it is not or misses</h3>${list([...c.assessment.scope.is_not, ...c.assessment.scope.omissions, ...c.assessment.scope.missing_or_weak, ...c.assessment.scope.dated_or_contested])}
      </details>

      <details class="section">
        <summary>Audience and topics</summary>
        <h3>Best for</h3>${list(c.assessment.audience.best_for)}
        <h3>Not for</h3>${list(c.assessment.audience.not_for)}
        <h3>Topics</h3><div class="tags">${book.tag_details.map(tag => `<span>${esc(tag.label)}</span>`).join('')}</div>
      </details>

      <details class="section">
        <summary>Book map</summary>
        <ol>${c.book_map.map(part => `<li><h3>${esc(part.title)}</h3><p>${esc(part.summary)}</p></li>`).join('')}</ol>
      </details>

      <details class="section">
        <summary>Related books and authors</summary>
        ${related.length ? `<ul class="related">${related.map(relatedItem).join('')}</ul>` : '<p>No relationships recorded yet.</p>'}
      </details>

      <details class="section">
        <summary>Author</summary>
        <p>${esc(c.assessment.author_and_purpose.text)}</p>
        ${book.authors.map(author => `<h3><a href="#author/${esc(author.id)}">${esc(author.name)}</a></h3><p>${esc(author.profile.biography.text)}</p><p>${esc(author.profile.perspective_and_limits.text)}</p><p><a href="#author/${esc(author.id)}">All of ${esc(author.name.split(' ').pop())}'s books in this library →</a></p>`).join('')}
      </details>

      <details class="section">
        <summary>Remember and apply</summary>
        <h3>Recall</h3>${list(c.retention.recall_prompts)}
        <h3>Application</h3>${list(c.retention.application_prompts)}
      </details>

      <section class="section">
        <details><summary>${sources.length} research sources</summary>
          <ol class="source-list">${sources.map(source => `<li><a href="${esc(source.url)}" target="_blank" rel="noreferrer">${esc(source.title)}</a><span class="source-meta">${esc(source.author_or_publisher)} · ${esc(source.independence)} · ${esc(source.quality)} quality</span><span class="source-meta">Limit: ${esc(source.limitations)}</span></li>`).join('')}</ol>
        </details>
      </section>
    </article>`;

  el('book-detail').querySelectorAll('[data-level]').forEach(button => button.addEventListener('click', () => {
    state.level = button.dataset.level;
    renderBook();
    document.querySelector('.script-panel')?.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  }));
  bindScriptActions();
}

function renderAuthor(id) {
  const author = findAuthor(id);
  if (!author) return;
  const profile = author.profile;
  const works = author.selected_works || [];
  const sources = author.research?.sources || [];
  const librarySection = author.books.map(book => {
    const rating = bookRating(book);
    const featured = featuredItem(book);
    return `<li>
      <a href="#book/${esc(book.id)}">
        <strong>${esc(book.title)}</strong>
        <span class="muted">${esc(book.bibliography.first_published || '')}${rating ? ` · ${rating.score.toFixed(1)}/10` : ''} · ${esc(recommendedLevel(book))} recommended</span>
      </a>
      ${featured ? `<button type="button" class="quickplay" data-play-book="${esc(book.id)}" title="Play the recommended brief">▶ ${timeLabel(levelSeconds(book, featured.level))}</button>` : ''}
    </li>`;
  }).join('');
  const workItem = work => {
    const match = bookByTitle(work.title);
    const title = match ? `<a href="#book/${esc(match.id)}">${esc(work.title)}</a>` : esc(work.title);
    return `<li>${title}${work.year ? ` (${esc(work.year)})` : ''}${work.relationship ? ` — ${esc(work.relationship)}` : ''}</li>`;
  };

  el('book-detail').innerHTML = `
    <article>
      <header class="hero">
        <div class="eyebrow">Author</div>
        <h1>${esc(author.name)}</h1>
        <p class="verdict">${esc(profile.one_line.text)}</p>
      </header>

      <section class="section">
        <h2>In this library</h2>
        <ul class="author-books">${librarySection}</ul>
      </section>

      <section class="section">
        <h2>Biography</h2>
        <p>${esc(profile.biography.text)}</p>
        <p>${esc(profile.background.text)}</p>
      </section>

      <section class="section">
        <h2>Expertise and perspective</h2>
        <p>${esc(profile.expertise.text)}</p>
        <p class="caveat"><strong>Limits:</strong> ${esc(profile.perspective_and_limits.text)}</p>
      </section>

      ${works.length ? `<section class="section">
        <h2>Selected works</h2>
        <ul class="compact-list">${works.map(workItem).join('')}</ul>
      </section>` : ''}

      ${sources.length ? `<section class="section">
        <details><summary>${sources.length} research sources</summary>
          <ol class="source-list">${sources.map(source => `<li><a href="${esc(source.url)}" target="_blank" rel="noreferrer">${esc(source.title)}</a><span class="source-meta">${esc(source.author_or_publisher)} · ${esc(source.independence)} · ${esc(source.quality)} quality</span></li>`).join('')}</ol>
        </details>
      </section>` : ''}
    </article>`;

  el('book-detail').querySelectorAll('[data-play-book]').forEach(button => button.addEventListener('click', event => {
    event.preventDefault();
    playItem(featuredItem(findBook(button.dataset.playBook)));
  }));
}

function scriptPanel(book, level) {
  const script = book.scripts[level];
  const command = `./bookflow audio ${book.id} ${level}`;
  const playable = hasAudio(book, level);
  const voices = Object.keys(audioVariants(book, level));
  const voiceNames = state.library.config.tts.voices || {};
  return `<section class="script-panel" aria-live="polite">
    <div class="action-row">
      <strong>${esc(label(level))} brief · ${script.words} words · ${esc(script.meta.status || 'unknown')}</strong>
      <button class="primary" id="play" type="button" ${playable ? '' : 'disabled'}>${playable ? 'Play audio' : 'Audio not generated'}</button>
      <button class="quiet-button" id="add" type="button" ${playable ? '' : 'disabled'}>Add to playlist</button>
    </div>
    ${playable
      ? `<p class="muted">Narrated by ${voices.map(v => esc((voiceNames[v] || v).split(' — ')[0])).join(', ')}.
         Other voices: <code>${esc(command)} --voice ${esc(Object.keys(voiceNames).find(v => !voices.includes(v)) || 'bf_isabella')}</code></p>`
      : `<p class="muted">Generate locally with <code>${esc(command)}</code>.</p>`}
    <details><summary>Read transcript</summary><div class="script-text">${esc(script.body)}</div></details>
  </section>`;
}

function bindScriptActions() {
  if (!state.level) return;
  el('play')?.addEventListener('click', () => playItem({bookId: state.selectedBook.id, level: state.level}));
  el('add')?.addEventListener('click', () => {
    enqueue({bookId: state.selectedBook.id, level: state.level});
  });
}

// --- queue and playback ---

function positionKey() {
  return `position:${el('audio').dataset.book}:${el('audio').dataset.level}`;
}

// One queue entry per book: choosing another duration replaces the existing
// entry in place rather than adding a duplicate.
function enqueue(item) {
  const at = state.queue.findIndex(existing => existing.bookId === item.bookId);
  if (at >= 0) state.queue[at] = item;
  else state.queue.push(item);
  renderPlaylist();
}

function dedupeByBook(items) {
  const seen = new Set();
  return items.filter(item => !seen.has(item.bookId) && seen.add(item.bookId));
}

function playItem(item) {
  if (!item) return;
  const at = state.queue.findIndex(existing => existing.bookId === item.bookId);
  if (at >= 0) {
    state.queue[at] = item;
    state.queueIndex = at;
  } else {
    state.queue.splice(state.queueIndex + 1, 0, item);
    state.queueIndex += 1;
  }
  playCurrent();
}

function playCurrent() {
  const item = state.queue[state.queueIndex];
  const url = item && audioUrl(item);
  if (!url) { renderPlaylist(); return; }
  const book = findBook(item.bookId);
  const audio = el('audio');
  el('player').hidden = false;
  el('player-title').textContent = book.title;
  el('player-level').textContent = label(item.level);
  audio.src = url;
  audio.dataset.book = item.bookId;
  audio.dataset.level = item.level;
  audio.playbackRate = Number(el('speed').value);
  const savedPosition = Number(localStorage.getItem(positionKey()) || 0);
  if (savedPosition > 5) audio.currentTime = savedPosition;
  audio.play();
  renderPlaylist();
}

function playNext() {
  if (state.queueIndex < state.queue.length - 1) {
    state.queueIndex += 1;
    playCurrent();
  }
}

// --- saved playlists (data/playlists.json via ./bookflow serve, else this browser) ---

const toFile = item => ({book_id: item.bookId, duration: item.level});
const fromFile = item => ({bookId: item.book_id, level: item.duration});

async function loadPlaylists() {
  const legacy = JSON.parse(localStorage.getItem('book-brief-playlist') || 'null');
  if (Array.isArray(legacy) && legacy.length) {
    state.queue = legacy;
    localStorage.removeItem('book-brief-playlist');
  }
  try {
    const response = await fetch('/api/playlists', {cache: 'no-store'});
    if (response.ok) {
      const data = await response.json();
      state.saved = {schema_version: 1, playlists: data.playlists.map(p => ({...p, items: p.items.map(fromFile)}))};
      state.serverPlaylists = true;
      return;
    }
  } catch (error) { /* static server without the playlists API */ }
  state.serverPlaylists = false;
  const local = JSON.parse(localStorage.getItem('book-brief-saved') || 'null');
  if (local) state.saved = local;
}

async function persistPlaylists() {
  if (state.serverPlaylists) {
    const payload = {schema_version: 1,
      playlists: state.saved.playlists.map(p => ({...p, items: p.items.map(toFile)}))};
    await fetch('/api/playlists', {method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)}).catch(() => {});
  } else {
    localStorage.setItem('book-brief-saved', JSON.stringify(state.saved));
  }
  renderPlaylist();
}

function saveQueueAsPlaylist() {
  if (!state.queue.length) return;
  const name = prompt('Playlist name:');
  if (!name) return;
  const id = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'playlist';
  const entry = {id, name, items: [...state.queue], updated_at: new Date().toISOString()};
  const existing = state.saved.playlists.find(p => p.id === id);
  if (existing) Object.assign(existing, entry); else state.saved.playlists.push(entry);
  persistPlaylists();
}

function renderPlaylist() {
  el('playlist-count').textContent = state.queue.length;
  el('playlist-hint').textContent = state.serverPlaylists
    ? 'Saved playlists are stored in data/playlists.json.'
    : 'Saved playlists live in this browser. Start with ./bookflow serve to store them in the library.';
  el('playlist-items').innerHTML = state.queue.map((item, index) => {
    const book = findBook(item.bookId);
    const current = index === state.queueIndex;
    const recommended = book && item.level === recommendedLevel(book);
    const timing = book ? ` · ${timeLabel(levelSeconds(book, item.level))}` : '';
    return `<li ${recommended ? 'class="recommended"' : ''}>
      <button type="button" data-play="${index}" ${current ? 'aria-current="true"' : ''}
        ${recommended ? 'title="The recommended length for this book"' : ''}>
        <strong>${current ? '▶ ' : ''}${esc(book?.title || item.bookId)}</strong>
        <span class="muted">${recommended ? '★ ' : ''}${esc(label(item.level))}${esc(timing)}</span>
      </button>
      <span>
        <button type="button" data-up="${index}" aria-label="Move up" ${index === 0 ? 'disabled' : ''}>↑</button>
        <button type="button" data-remove="${index}" aria-label="Remove">×</button>
      </span>
    </li>`;
  }).join('') || '<li class="muted">Nothing queued.</li>';
  el('playlist-items').querySelectorAll('[data-play]').forEach(button => button.addEventListener('click', () => {
    state.queueIndex = Number(button.dataset.play);
    playCurrent();
  }));
  el('playlist-items').querySelectorAll('[data-up]').forEach(button => button.addEventListener('click', () => {
    const index = Number(button.dataset.up);
    [state.queue[index - 1], state.queue[index]] = [state.queue[index], state.queue[index - 1]];
    if (state.queueIndex === index) state.queueIndex = index - 1;
    else if (state.queueIndex === index - 1) state.queueIndex = index;
    renderPlaylist();
  }));
  el('playlist-items').querySelectorAll('[data-remove]').forEach(button => button.addEventListener('click', () => {
    const index = Number(button.dataset.remove);
    state.queue.splice(index, 1);
    if (state.queueIndex >= index) state.queueIndex -= 1;
    renderPlaylist();
  }));

  el('saved-lists').innerHTML = state.saved.playlists.map((playlist, index) => {
    const totalSeconds = playlist.items.reduce((sum, item) => {
      const book = findBook(item.bookId);
      return sum + (book ? levelSeconds(book, item.level) : 0);
    }, 0);
    return `<li>
      <button type="button" data-open="${index}">
        <strong>${esc(playlist.name)}</strong>
        <span class="muted">${playlist.items.length} item${playlist.items.length === 1 ? '' : 's'} · ${timeLabel(totalSeconds)}</span>
      </button>
      <span>
        <button type="button" data-append="${index}" aria-label="Append to queue">+</button>
        <button type="button" data-delete="${index}" aria-label="Delete">×</button>
      </span>
    </li>`;
  }).join('') || '<li class="muted">None saved yet.</li>';
  el('saved-lists').querySelectorAll('[data-open]').forEach(button => button.addEventListener('click', () => {
    state.queue = dedupeByBook([...state.saved.playlists[Number(button.dataset.open)].items]);
    state.queueIndex = 0;
    playCurrent();
  }));
  el('saved-lists').querySelectorAll('[data-append]').forEach(button => button.addEventListener('click', () => {
    state.saved.playlists[Number(button.dataset.append)].items.forEach(enqueue);
  }));
  el('saved-lists').querySelectorAll('[data-delete]').forEach(button => button.addEventListener('click', () => {
    const playlist = state.saved.playlists[Number(button.dataset.delete)];
    if (!confirm(`Delete playlist "${playlist.name}"?`)) return;
    state.saved.playlists.splice(Number(button.dataset.delete), 1);
    persistPlaylists();
  }));
}

start();
