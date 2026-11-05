'use strict';
const $ = id => document.getElementById(id);
const state = {papers: [], brief: null, controller: null, request: 0};
const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
};
function setNotice(text, error = false) {
  $('notice').textContent = text;
  $('notice').classList.toggle('error', error);
}
async function getJSON(path, options = {}) {
  const response = await fetch(path, {cache: 'no-store', ...options});
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || 'The local request could not be completed.');
  return payload;
}
function sourceLink(paper) {
  if (paper.synthetic) return node('span', 'SYNTHETIC FIXTURE', 'pill demo');
  const link = node('a', 'Read source ↗', 'source-link');
  try {
    const url = new URL(paper.url);
    if (url.protocol !== 'https:' || url.username || url.password) throw new Error();
    link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
  } catch {return node('span', 'Source unavailable', 'pill');}
  return link;
}
function paperRow(paper, index, expanded = false) {
  const article = node('article', undefined, 'paper-row');
  article.append(node('span', String(index + 1).padStart(2, '0'), 'paper-number'));
  const content = node('div', undefined, 'paper-content');
  content.append(node('h3', paper.title), node('p', `${paper.authors.join(', ')} · ${paper.published.slice(0, 10)}`));
  if (expanded) content.append(node('p', paper.abstract, 'abstract'));
  const tags = node('div', undefined, 'paper-tags');
  tags.append(sourceLink(paper)); article.append(content, tags);
  return article;
}
function renderLibrary() {
  const filter = $('library-filter').value.toLowerCase().trim();
  const papers = state.papers.filter(p => `${p.title} ${p.abstract} ${p.authors.join(' ')}`.toLowerCase().includes(filter));
  $('all-papers').replaceChildren(...papers.map((p, i) => paperRow(p, i, true)));
  if (!papers.length) $('all-papers').append(node('div', 'No papers match this filter.', 'empty-state'));
  $('filter-count').textContent = `${papers.length} shown`;
}
function renderBrief(brief) {
  state.brief = brief;
  $('brief-date').textContent = `${brief.day} / UTC`;
  $('brief-preview').replaceChildren(...brief.highlights.slice(0, 2).map(p => node('div', p.title)));
  if (!brief.highlights.length) $('brief-preview').append(node('div', 'No new or changed records today.'));
  const box = $('daily-brief'); box.replaceChildren();
  box.append(node('h2', `${brief.new_or_changed} new or changed records`), node('p', brief.limitations));
  brief.highlights.forEach((paper, index) => {
    const item = node('article', undefined, 'brief-item');
    item.append(node('h3', `${String(index + 1).padStart(2, '0')} / ${paper.title}`), node('p', paper.quote), sourceLink(paper));
    box.append(item);
  });
  if (!brief.highlights.length) box.append(node('p', 'Nothing new was ingested today. Existing papers remain searchable in your library.'));
}
function navigate() {
  const names = {overview: 'Overview', ask: 'Ask your library', library: 'Paper library', brief: 'Daily brief'};
  const hash = location.hash.slice(1);
  const page = Object.hasOwn(names, hash) ? hash : 'overview';
  if (page !== 'ask' && state.controller) cancelAnswer();
  document.querySelectorAll('.panel').forEach(panel => {panel.hidden = panel.id !== page; panel.classList.toggle('active', panel.id === page);});
  document.querySelectorAll('.nav-link').forEach(link => link.classList.toggle('active', link.hash === `#${page}`));
  $('page-name').textContent = names[page];
}
function busy(value) {
  $('ask-button').disabled = value; $('ask-button').textContent = value ? 'Finding evidence…' : 'Find evidence ↗';
  $('cancel-answer').hidden = !value;
  $('answer-results').setAttribute('aria-busy', String(value));
}
function cancelAnswer() {
  state.request += 1;
  if (state.controller) state.controller.abort();
  state.controller = null; busy(false);
  $('answer-results').replaceChildren(node('p', 'Search canceled. You can edit your question and try again.', 'answer-summary'));
}
function renderAnswer(answer) {
  const target = $('answer-results'); target.replaceChildren();
  const heading = node('div', undefined, 'answer-heading');
  heading.append(node('h2', answer.citations.length ? `${answer.citations.length} evidence excerpts` : 'Not enough evidence'), node('span', 'EXTRACTIVE · VERIFIED', 'pill'));
  target.append(heading, node('p', answer.summary, 'answer-summary'));
  if (answer.synthetic) target.append(node('p', 'Demo evidence below comes from fictional records. It is not scientific research.', 'notice'));
  answer.citations.forEach(citation => {
    const card = node('article', undefined, 'evidence-card');
    const top = node('div', undefined, 'evidence-top');
    const title = node('h3'); title.append(node('span', citation.id, 'evidence-id'), document.createTextNode(citation.title));
    top.append(title, sourceLink(citation));
    const meta = node('div', undefined, 'evidence-meta');
    meta.append(node('span', `✓ Exact source match · characters ${citation.start}–${citation.end}`), node('code', `SHA-256 ${citation.content_hash.slice(0, 16)}…`));
    card.append(top, node('blockquote', citation.quote), meta); target.append(card);
  });
  target.append(node('p', answer.limitations.join(' '), 'disclaimer'));
}
async function askQuestion(event) {
  event.preventDefault();
  const query = $('question').value.trim();
  if (!query) {$('question').focus(); return;}
  if (state.controller) state.controller.abort();
  const request = ++state.request;
  state.controller = new AbortController(); busy(true);
  try {
    const answer = await getJSON('/api/answer', {method: 'POST', signal: state.controller.signal,
      headers: {'Content-Type': 'application/json', 'X-Research-Request': '1'}, body: JSON.stringify({query})});
    if (request === state.request) renderAnswer(answer);
  } catch (error) {
    if (request === state.request && error.name !== 'AbortError') $('answer-results').replaceChildren(node('p', error.message, 'notice error'));
  } finally {if (request === state.request) {state.controller = null; busy(false);}}
}
$('ask-form').addEventListener('submit', askQuestion);
$('cancel-answer').addEventListener('click', cancelAnswer);
$('library-filter').addEventListener('input', renderLibrary);
document.querySelectorAll('[data-question]').forEach(button => button.addEventListener('click', () => {$('question').value = button.dataset.question; $('question').focus();}));
$('download-brief').addEventListener('click', () => {
  if (!state.brief) return;
  const blob = new Blob([state.brief.markdown], {type: 'text/markdown;charset=utf-8'});
  const href = URL.createObjectURL(blob); const anchor = node('a');
  anchor.href = href; anchor.download = `research-brief-${state.brief.day}.md`; anchor.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
});
window.addEventListener('hashchange', navigate); navigate();
(async () => {
  try {
    const [status, library, brief] = await Promise.all([getJSON('/api/status'), getJSON('/api/papers'), getJSON('/api/brief')]);
    state.papers = library.papers;
    $('paper-count').textContent = status.papers; $('source-count').textContent = status.sources;
    $('recent-label').textContent = `${Math.min(3, state.papers.length)} selected`;
    $('recent-papers').replaceChildren(...state.papers.slice(0, 3).map((p, i) => paperRow(p, i)));
    if (!status.papers) $('recent-papers').append(node('div', 'Your library is empty. Load the bundled demo or a reviewed source with the CLI.', 'empty-state'));
    renderLibrary(); renderBrief(brief);
    setNotice(status.synthetic ? `DEMO WORKSPACE · ${status.synthetic} fictional records are indexed. Synthetic fixtures are clearly labeled and must not be cited as real publications.` : 'LOCAL WORKSPACE · Source claims are unverified. The dashboard makes no source requests and stores no question history.');
  } catch (error) {setNotice(`Could not load your local index. ${error.message}`, true); $('download-brief').disabled = true;}
})();
