'use strict';

const $ = id => document.getElementById(id);
const categories = { assignment: '作业任务', activity: '活动', life: '生活' };
const weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
const origins = { mail: '邮件日记', manual: '手动添加', voice: '语音录入' };
const statuses = { invitation: '邀请', invited: '邀请', optional: '邀请', confirmed: '已确认', registered: '已报名', completed: '已完成', planned: '已安排', pending: '待确认', unknown: '待确认', cancelled: '已取消', canceled: '已取消', notice: '通知' };
const invitationStatuses = new Set(['invitation', 'invited', 'optional']);
const FLOATING_PREVIEW_LIMIT = 2;
const shanghai = new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});

function localNow() { return shanghai.format(new Date()).replace(' ', 'T'); }
function datePart(value) { return String(value ?? '').slice(0, 10); }
function utcDate(value) { return new Date(`${value}T00:00:00Z`); }
function dayOffset(value, offset) {
  const date = utcDate(value);
  date.setUTCDate(date.getUTCDate() + offset);
  return date.toISOString().slice(0, 10);
}
function monday(date) { return dayOffset(date, -((utcDate(date).getUTCDay() + 6) % 7)); }
function shiftMonth(date, amount) {
  const value = utcDate(`${date.slice(0, 7)}-01`);
  value.setUTCMonth(value.getUTCMonth() + amount);
  return value.toISOString().slice(0, 10);
}
function dayList(start, count) { return Array.from({ length: count }, (_, index) => dayOffset(start, index)); }
function chineseDate(value, withYear = false) {
  return `${withYear ? `${value.slice(0, 4)} 年 ` : ''}${Number(value.slice(5, 7))} 月 ${Number(value.slice(8, 10))} 日`;
}
function clock(value) { return String(value ?? '').slice(11, 16); }
function minuteOfDay(value) {
  const [hours, minutes] = clock(value).split(':').map(Number);
  return hours * 60 + minutes;
}
function formatMinutes(minutes) {
  return [Math.floor(minutes / 60), minutes % 60].map(part => String(part).padStart(2, '0')).join(':');
}
function countDays(from, to) { return Math.round((utcDate(to) - utcDate(from)) / 86400000); }

const state = {
  today: datePart(localNow()), selected: datePart(localNow()), miniMonth: `${localNow().slice(0, 7)}-01`,
  view: 'week', events: [], mail: null, filters: new Set(Object.keys(categories)), search: '',
  loading: true, error: '', request: 0, renderedRange: '', source: 'manual',
};

function range() {
  if (state.view === 'day') return { from: state.selected, to: dayOffset(state.selected, 1) };
  const firstWeekday = monday(state.selected);
  if (state.view !== 'month') return { from: firstWeekday, to: dayOffset(firstWeekday, 7) };
  const first = `${state.selected.slice(0, 7)}-01`;
  const from = monday(first);
  const next = shiftMonth(first, 1);
  const endWeek = monday(next);
  return { from, to: endWeek === next ? next : dayOffset(endWeek, 7) };
}

function node(tag, className, label) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (label != null) element.textContent = label;
  return element;
}

function makeButton(className, label, onClick) {
  const button = node('button', className, label);
  button.type = 'button';
  button.addEventListener('click', onClick);
  return button;
}

function move(date, view = state.view) {
  state.selected = date;
  state.miniMonth = `${date.slice(0, 7)}-01`;
  const nextRange = view !== state.view || !sameViewRange();
  state.view = view;
  if (nextRange) {
    state.events = [];
    state.error = '';
    state.loading = true;
  }
  render();
  loadSchedule();
}

function sameViewRange() {
  const { from, to } = range();
  return state.renderedRange === `${state.view}:${from}:${to}`;
}

async function api(path, options) {
  const request = await fetch(path, options);
  const response = await request.json().catch(() => null);
  if (!request.ok) throw new Error(typeof response?.error === 'string' ? response.error : response?.message || '服务器暂时无法响应，请重试。');
  if (!response) throw new Error('服务器返回了无法读取的数据。');
  return response;
}

function jsonRequest(body, method = 'POST') { return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }; }

async function loadSchedule(quiet = false) {
  const requestId = ++state.request;
  const { from, to } = range();
  const key = `${state.view}:${from}:${to}`;
  const singleWeek = state.view === 'week' || state.view === 'list';
  const query = new URLSearchParams(singleWeek ? { week: from } : { from, to });
  $('refresh').disabled = true;
  try {
    const response = await api(`/api/schedule?${query}`);
    if (requestId !== state.request) return;
    const events = Array.isArray(response.events) ? response.events : [];
    const today = response.today || datePart(localNow());
    const changed = key !== state.renderedRange || today !== state.today || JSON.stringify(events) !== JSON.stringify(state.events);
    const rerender = changed || state.loading || state.error;
    state.renderedRange = key;
    state.today = today;
    state.events = events;
    state.mail = response.mail ?? null;
    state.error = '';
    state.loading = false;
    if (rerender) render();
    else {
      renderSource();
      updateTimeMarker();
    }
    if (!quiet) $('status').textContent = `已显示 ${filteredEvents().length} 项日程。`;
  } catch (error) {
    if (requestId !== state.request) return;
    state.loading = false;
    if (state.renderedRange === key && quiet) return;
    state.error = error.message;
    render();
  } finally {
    if (requestId === state.request) $('refresh').disabled = false;
  }
}

function isInvitation(event) {
  return invitationStatuses.has(event.status) || (event.origin === 'mail' && event.category === 'activity' && !event.status);
}

function filteredEvents() {
  const query = state.search.toLocaleLowerCase();
  const showInvitations = $('show-invitations').checked;
  return state.events.filter(event => {
    if (!state.filters.has(event.category) || (!showInvitations && isInvitation(event))) return false;
    return !query || [event.title, event.location, event.notes].some(value => String(value ?? '').toLocaleLowerCase().includes(query));
  });
}

function renderSource() {
  const mail = state.mail;
  const verified = mail?.coverage_end || mail?.last_success_at;
  $('mail-status').textContent = mail?.demo ? '正在使用示例日程' : verified
    ? `邮件覆盖至 ${chineseDate(verified)} ${clock(verified)}`.trim()
    : state.loading ? '正在读取邮件日记…' : '暂无更新记录';
  $('mail-warning').textContent = mail?.warning || '';
  $('mail-warning').hidden = !mail?.warning;
}

function renderMini() {
  const month = state.miniMonth;
  const start = monday(month);
  const activeWeek = monday(state.selected);
  $('mini-month').textContent = `${month.slice(0, 4)} 年 ${Number(month.slice(5, 7))} 月`;
  const elements = weekdays.map(label => node('span', '', label.slice(1)));
  for (const date of dayList(start, 42)) {
    const inWeek = state.view !== 'day' && date >= activeWeek && date < dayOffset(activeWeek, 7);
    const classes = [date.slice(0, 7) !== month.slice(0, 7) ? 'other-month' : '', date === state.today ? 'is-today' : '', inWeek ? 'in-week' : '', date === state.selected ? 'selected-day' : ''];
    const button = makeButton(classes.join(' '), String(Number(date.slice(8, 10))), () => move(date));
    button.setAttribute('aria-label', chineseDate(date, true));
    if (date === state.today) button.setAttribute('aria-current', 'date');
    elements.push(button);
  }
  $('mini-grid').replaceChildren(...elements);
}

function render() {
  const { from, to } = range();
  const last = dayOffset(to, -1);
  const inMonth = state.view === 'month';
  const inDay = state.view === 'day';
  const year = state.selected.slice(0, 4);
  const month = Number(state.selected.slice(5, 7));
  $('period-label').textContent = `${year} 年`;
  const weekday = weekdays[(utcDate(from).getUTCDay() + 6) % 7];
  $('period-heading').textContent = inDay ? `${chineseDate(from)} ${weekday}` : inMonth ? `${month} 月日程` : `${chineseDate(from)} – ${chineseDate(last)}`;
  $('previous').setAttribute('aria-label', inDay ? '前一天' : inMonth ? '上个月' : '上一周');
  $('next').setAttribute('aria-label', inDay ? '后一天' : inMonth ? '下个月' : '下一周');
  $('return-home').hidden = state.view === 'week' && state.selected === state.today;
  document.querySelectorAll('[data-view]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.view === state.view)));
  renderMini();
  renderSource();
  for (const cat of Object.keys(categories)) {
    const count = state.events.filter(event => event.category === cat).length;
    $(`count-${cat}`).textContent = count ? String(count) : '';
  }
  const calendar = $('calendar');
  calendar.setAttribute('aria-busy', String(state.loading));
  if (state.loading) {
    calendar.replaceChildren(node('p', 'calendar-feedback', '正在读取日程…'));
    return;
  }
  if (state.error) {
    const error = node('div', 'calendar-feedback', state.error);
    error.append(node('br'), makeButton('button small', '重试', () => loadSchedule()));
    calendar.replaceChildren(error);
    return;
  }
  const events = filteredEvents();
  const scrollLeft = calendar.scrollLeft;
  const days = dayList(from, countDays(from, to));
  const view = inDay ? dayAgenda(from, events) : state.view === 'week' ? weekSheet(days, events) : inMonth ? monthSheet(days, events) : agenda(days, events);
  calendar.replaceChildren(view);
  calendar.scrollLeft = scrollLeft;
  if ($('day-dialog').open) renderDayDialog(events);
  if (state.search && !events.length && (state.view === 'week' || inMonth)) {
    calendar.prepend(node('div', 'calendar-feedback', '当前日期范围没有匹配的日程。'));
  }
}

function eventStatus(event) {
  return statuses[event.status] || event.status || '';
}

function isDeadline(event) { return event.kind === 'deadline' || (!event.kind && event.category === 'assignment' && event.origin === 'mail' && !event.end); }
function isFloating(event) { return Boolean(event.all_day || !clock(event.start) || isDeadline(event)); }

function dailyEvents(day, events) {
  return events.filter(event => {
    const start = datePart(event.start);
    const end = datePart(event.end) || start;
    if (start === day) return true;
    if (!(start < day && day <= end)) return false;
    return event.all_day || day < end || minuteOfDay(event.end) > 0;
  }).sort((a, b) => String(a.start).localeCompare(String(b.start)));
}

function eventTime(event, day) {
  if (event.all_day || !clock(event.start)) return isDeadline(event) ? '截止' : '全天';
  if (!event.end) return `${clock(event.start)}${isDeadline(event) ? ' 截止' : ''}`;
  const from = !day || datePart(event.start) === day ? clock(event.start) : '00:00';
  const to = !day || datePart(event.end) === day ? clock(event.end) : '24:00';
  return `${from}–${to}`;
}

function gmailSource(event) {
  const link = event.mail_url ?? event.source_url;
  const url = URL.canParse(link) ? new URL(link) : null;
  if (url?.protocol !== 'https:' || url.hostname !== 'mail.google.com' || url.port || url.username || url.password) return null;
  return /^\/mail(?:\/u(?:\/\d+)?)?\/?$/.test(url.pathname) && /^#(?:all|inbox)\/[A-Za-z0-9_-]+$/.test(url.hash) ? url : null;
}

function eventButton(event, type, day) {
  const status = eventStatus(event);
  const timed = type === 'timed';
  const button = makeButton(`event ${event.category} ${timed ? 'timed-content' : type}${isInvitation(event) ? ' invitation' : ''}`, null, () => showDetails(event));
  const time = eventTime(event, day);
  button.title = [event.title, time, event.location, status].filter(Boolean).join(' / ');
  button.setAttribute('aria-label', [categories[event.category], event.title, day && chineseDate(day), time, event.location, status].filter(Boolean).join('，'));
  const strip = type === 'strip-event';
  const visibleTime = strip ? clock(event.start) : time;
  if (visibleTime) button.append(node('span', 'event-time', visibleTime));
  button.append(node('span', 'event-title', event.title));
  if (type === 'agenda-event' && event.location) button.append(node('span', 'event-location', event.location));
  if (type === 'agenda-event' && status) button.append(node('span', 'event-status', status));
  const mail = gmailSource(event);
  if (!mail) {
    if (timed) button.classList.add('timed');
    return button;
  }
  const card = node('div', `event-card ${event.category}${timed ? ' timed' : ''}${type === 'agenda-event' ? ' agenda-card' : ''}`);
  const badge = node('a', 'mail-badge');
  badge.href = mail.href;
  badge.target = '_blank';
  badge.rel = 'noopener noreferrer';
  badge.setAttribute('aria-label', `在新窗口打开 Gmail 原邮件：${event.title}`);
  badge.title = '在新窗口打开 Gmail 原邮件';
  const icon = node('span', 'mail-icon');
  icon.setAttribute('aria-hidden', 'true');
  badge.append(icon, node('span', '', '原邮件'));
  card.append(button, badge);
  return card;
}

function dayHeading(date, index) {
  const cell = node('div', `day-heading${date === state.today ? ' is-today' : ''}`);
  const heading = makeButton('week-day', null, () => move(date, 'day'));
  heading.setAttribute('aria-label', `打开 ${chineseDate(date)} 日视图`);
  if (date === state.today) heading.setAttribute('aria-current', 'date');
  heading.append(node('span', '', weekdays[index]), node('strong', '', Number(date.slice(8, 10))));
  cell.append(heading);
  return cell;
}

let dayDialog;
function showDayEvents(day, label = '当日事项', items = null) {
  dayDialog = { day, ids: items && new Set(items.map(event => event.id)) };
  const weekday = weekdays[(utcDate(day).getUTCDay() + 6) % 7];
  $('day-dialog-date').textContent = `${chineseDate(day, true)} ${weekday}`;
  $('day-dialog-title').textContent = label;
  renderDayDialog(filteredEvents());
  $('day-dialog').showModal();
}

function renderDayDialog(events) {
  const { day, ids } = dayDialog;
  const items = dailyEvents(day, ids ? events.filter(event => ids.has(event.id)) : events);
  const list = $('day-dialog-items');
  if (items.length) list.replaceChildren(...items.map(event => eventButton(event, 'agenda-event', day)));
  else list.replaceChildren(node('p', 'agenda-blank', '当天没有符合筛选条件的日程。'));
}

function moreButton(count, day, label, items) {
  const button = makeButton('more-events', `+${count} 项`, () => showDayEvents(day, label, items));
  button.setAttribute('aria-label', `查看 ${chineseDate(day)} 全部${items.length}项${label}`);
  return button;
}

function previewPriority(event) {
  if (event.category === 'assignment') return 0;
  return isInvitation(event) ? 2 : 1;
}

function weekSheet(days, events) {
  const week = node('div', 'week-sheet');
  const head = node('div', 'week-row week-head');
  head.append(node('div', 'week-gutter'), ...days.map(dayHeading));
  week.append(head);
  const assignments = days.map(day => dailyEvents(day, events));
  for (const [label, matcher] of [['全天', e => isFloating(e) && !isDeadline(e)], ['截止', isDeadline]]) {
    const row = node('div', 'week-row floating');
    row.append(node('div', 'floating-label', label));
    days.forEach((day, index) => {
      const cell = node('div', `floating-cell${day === state.today ? ' is-today' : ''}`);
      const items = assignments[index].filter(matcher);
      const previews = [...items].sort((a, b) => previewPriority(a) - previewPriority(b)).slice(0, FLOATING_PREVIEW_LIMIT);
      cell.append(...previews.map(event => eventButton(event, 'strip-event', day)));
      if (items.length > previews.length) cell.append(moreButton(items.length - previews.length, day, `${label}事项`, items));
      row.append(cell);
    });
    week.append(row);
  }

  const segments = days.map((day, i) => assignments[i].filter(e => !isFloating(e)).map(event => {
    const start = datePart(event.start) === day ? minuteOfDay(event.start) : 0;
    const end = event.end ? (datePart(event.end) === day ? minuteOfDay(event.end) : 1440) : start + 30;
    return { event, start, end: Math.max(start + (gmailSource(event) ? 76 : 54), end) };
  }));
  const allSegments = segments.flat();
  const firstHour = Math.min(8, ...allSegments.map(seg => Math.floor(seg.start / 60)));
  const lastMinute = Math.max(22 * 60, ...allSegments.map(seg => seg.end));
  const finalHour = Math.min(24, Math.ceil(lastMinute / 60));
  const timed = node('div', 'week-row timeline');
  timed.style.setProperty('--hours', Math.max(finalHour, lastMinute / 60) - firstHour);
  const labels = node('div', 'time-labels');
  for (let h = firstHour; h < finalHour; h += 1) {
    const label = node('span', 'time-label', `${String(h).padStart(2, '0')}:00`);
    label.style.setProperty('--y', `calc(var(--hour) * ${h - firstHour})`);
    labels.append(label);
  }
  timed.append(labels);
  days.forEach((day, index) => {
    const today = day === state.today;
    const track = node('div', `day-track${today ? ' is-today' : ''}`);
    for (const entry of groupSegments(segments[index])) {
      const events = entry.items;
      const button = events.length === 1 ? eventButton(events[0], 'timed', day) : timeGroupButton(day, entry);
      button.style.setProperty('--top', `calc(var(--hour) * ${(entry.start - firstHour * 60) / 60})`);
      button.style.setProperty('--height', `calc(var(--hour) * ${(entry.end - entry.start) / 60})`);
      track.append(button);
    }
    if (today) {
      const pointer = node('div', 'current-time');
      pointer.dataset.firstHour = firstHour;
      pointer.dataset.finalHour = finalHour;
      pointer.setAttribute('aria-hidden', 'true');
      updateTimeMarker(pointer);
      track.append(pointer);
    }
    timed.append(track);
  });
  week.append(timed);
  return week;
}

function updateTimeMarker(pointer = document.querySelector('.current-time')) {
  if (!pointer) return;
  const hour = minuteOfDay(localNow()) / 60;
  const first = Number(pointer.dataset.firstHour);
  pointer.hidden = hour < first || hour >= Number(pointer.dataset.finalHour);
  pointer.style.setProperty('--y', `calc(var(--hour) * ${hour - first})`);
}

function timeGroupButton(day, group) {
  const start = formatMinutes(group.start);
  const button = makeButton('time-group timed', null, () => showDayEvents(day, `${start} 起的事项`, group.items));
  button.setAttribute('aria-label', `查看 ${chineseDate(day)} ${start} 起的 ${group.items.length} 项日程`);
  const count = node('span', 'group-count', `${group.items.length} 项日程`);
  const arrow = node('span', 'group-arrow', '›');
  arrow.setAttribute('aria-hidden', 'true');
  button.append(node('span', 'group-time', `${start} 起`), count, arrow);
  const duration = group.end - group.start;
  const previewCount = duration >= 150 ? 2 : duration >= 105 ? 1 : 0;
  const previews = previewCount ? [...group.items].sort((a, b) => previewPriority(a) - previewPriority(b)).slice(0, previewCount) : [];
  for (const event of previews) button.append(node('span', 'group-preview', event.title));
  return button;
}

function groupSegments(segments) {
  const groups = [];
  const ordered = [...segments].sort((a, b) => a.start - b.start || b.end - a.end);
  for (const item of ordered) {
    const previous = groups.at(-1);
    if (!previous || item.start >= previous.end) {
      groups.push({ start: item.start, end: item.end, items: [item.event] });
    } else {
      previous.end = Math.max(previous.end, item.end);
      previous.items.push(item.event);
    }
  }
  return groups;
}

function monthSheet(days, events) {
  const month = node('div', 'month-sheet');
  const labels = node('div', 'month-weekdays');
  labels.append(...weekdays.map(w => node('div', '', w)));
  const grid = node('div', 'month-grid');
  for (const day of days) {
    const cell = node('div', `month-cell${day === state.today ? ' is-today' : ''}${day.slice(0, 7) !== state.selected.slice(0, 7) ? ' other-month' : ''}`);
    const button = makeButton('month-day', String(Number(day.slice(8, 10))), () => move(day, 'day'));
    button.setAttribute('aria-label', `打开 ${chineseDate(day)} 日视图`);
    if (day === state.today) button.setAttribute('aria-current', 'date');
    cell.append(button);
    const items = dailyEvents(day, events);
    cell.append(...items.slice(0, 3).map(event => eventButton(event, 'compact', day)));
    if (items.length > 3) cell.append(moreButton(items.length - 3, day, '当日事项', items));
    grid.append(cell);
  }
  month.append(labels, grid);
  return month;
}

function agenda(days, events) {
  const list = node('div', 'agenda');
  days.forEach((day, index) => {
    const items = dailyEvents(day, events);
    if (!items.length) return;
    const section = node('section', `agenda-day${day === state.today ? ' is-today' : ''}`);
    const buttons = node('div', 'agenda-items');
    buttons.append(...items.map(event => eventButton(event, 'agenda-event', day)));
    section.append(node('h2', '', `${weekdays[index]} ${chineseDate(day)}`), buttons);
    list.append(section);
  });
  if (!list.children.length) list.append(node('p', 'agenda-blank', state.search ? '当前日期范围没有匹配的日程。' : '本周没有符合筛选条件的日程。'));
  return list;
}

function dayAgenda(day, events) {
  const list = node('div', 'day-agenda');
  const items = dailyEvents(day, events);
  const untimed = items.filter(event => event.all_day || !clock(event.start));
  const timed = items.filter(event => !event.all_day && clock(event.start));
  for (const [label, entries] of [['全天与未定时间', untimed], ['时间安排', timed]]) {
    if (!entries.length) continue;
    const section = node('section', 'day-agenda-section');
    const rows = node('div', 'agenda-items');
    rows.append(...entries.map(event => eventButton(event, 'agenda-event', day)));
    section.append(node('h2', '', label), rows);
    list.append(section);
  }
  if (!items.length) list.append(node('p', 'agenda-blank', '当天没有符合筛选条件的日程。'));
  return list;
}

let detailEvent = null;
let editId = null;
function showDetails(event) {
  detailEvent = event;
  const category = $('detail-category');
  category.textContent = categories[event.category] || '日程';
  category.className = `detail-category ${event.category}`;
  $('detail-title').textContent = event.title;
  const start = datePart(event.start);
  const end = datePart(event.end);
  const timing = event.all_day || !clock(event.start)
    ? `${chineseDate(start)}${end && end !== start ? ` – ${chineseDate(end)}` : ''} ${isDeadline(event) ? '截止' : '全天'}`
    : `${chineseDate(start)} ${clock(event.start)}${event.end ? ` – ${end !== start ? `${chineseDate(end)} ` : ''}${clock(event.end)}` : ''}${isDeadline(event) ? ' 截止' : ''}`;
  const sourceDateLabel = event.origin === 'mail' ? '收件日期' : '记录日期';
  const fields = [[isDeadline(event) ? '截止时间' : '时间', timing], ['地点', event.location], ['状态', eventStatus(event)], ['来源', origins[event.origin]], [sourceDateLabel, event.source_date]];
  $('detail-fields').replaceChildren(...fields.filter(([, value]) => value).flatMap(([key, value]) => [node('dt', '', key), node('dd', '', value)]));
  $('detail-notes').textContent = event.notes || '';
  $('detail-notes').hidden = !event.notes;
  const link = $('detail-source');
  const url = URL.canParse(event.source_url) ? new URL(event.source_url) : null;
  const mail = gmailSource(event);
  link.hidden = !url || !/^https?:$/.test(url.protocol) || url.hostname === 'mail.google.com';
  if (link.hidden) link.removeAttribute('href');
  else link.href = url.href;
  const mailLink = $('detail-mail-source');
  mailLink.hidden = !mail;
  if (mail) mailLink.href = mail.href;
  else mailLink.removeAttribute('href');
  const editable = /^(manual|voice)$/.test(event.origin) && /^[\da-f]{32}$/.test(event.id);
  $('edit-event').hidden = !editable;
  const remove = $('delete-event');
  remove.hidden = !editable;
  remove.disabled = false;
  remove.textContent = '删除';
  $('detail-error').hidden = true;
  $('detail-dialog').showModal();
}

function eventPath(id) { return `/api/events/${encodeURIComponent(id)}`; }

async function deleteEvent() {
  const item = detailEvent;
  const button = $('delete-event');
  if (button.textContent !== '确认删除') {
    button.textContent = '确认删除';
    return;
  }
  button.disabled = true;
  try {
    await api(eventPath(item.id), { method: 'DELETE' });
    if (detailEvent === item) $('detail-dialog').close();
    await loadSchedule(true);
    $('status').textContent = '日程已删除。';
  } catch (error) {
    if (detailEvent !== item) return;
    $('detail-error').hidden = false;
    $('detail-error').textContent = error.message;
    button.disabled = false;
    button.textContent = '删除';
  }
}

function useAllDay(checked, preserve = true) {
  const start = $('event-start');
  const end = $('event-end');
  const priorStart = start.value;
  const priorEnd = end.value;
  $('event-all-day').checked = checked;
  start.type = checked ? 'date' : 'datetime-local';
  end.type = start.type;
  if (!preserve) return;
  start.value = checked ? datePart(priorStart) : priorStart && `${datePart(priorStart)}T09:00`;
  end.value = checked ? datePart(priorEnd) : priorEnd && `${datePart(priorEnd)}T10:00`;
}

function setDraft(data) {
  $('event-title').value = data.title ?? '';
  $('event-category').value = data.category in categories ? data.category : 'activity';
  setKind(data.kind || 'event');
  useAllDay(Boolean(data.all_day), false);
  const toInput = value => (value || '').slice(0, data.all_day ? 10 : 16);
  $('event-start').value = toInput(data.start);
  $('event-end').value = toInput(data.end);
  $('event-location').value = data.location ?? '';
  $('event-notes').value = data.notes ?? '';
}

function setKind(kind) {
  $('event-kind').value = kind;
  const deadline = kind === 'deadline';
  $('event-start-label').textContent = deadline ? '截止时间' : '开始';
  $('event-end-field').hidden = deadline;
  $('event-end').disabled = deadline;
}

let recognition = null;
let dialogVersion = 0;
function openCreate(mode, existing = null) {
  dialogVersion += 1;
  editId = existing?.id ?? null;
  state.source = existing?.origin ?? 'manual';
  $('create-title').textContent = existing ? '编辑日程' : mode === 'voice' ? '语音录入日程' : '新建日程';
  $('voice-panel').hidden = mode !== 'voice';
  $('transcript').value = '';
  $('voice-status').textContent = '识别后可修改日程再保存。';
  $('record-label').textContent = '开始录音';
  $('record').disabled = false;
  $('interpret').disabled = false;
  $('save-event').disabled = false;
  $('parse-warnings').hidden = true;
  $('create-error').hidden = true;
  setDraft(existing || { category: 'activity', start: mode === 'voice' ? '' : `${state.selected}T09:00` });
  $('create-dialog').showModal();
  if (mode === 'voice') $('record').focus();
  else $('event-title').focus();
}

function record() {
  if (recognition) {
    recognition.stop();
    return;
  }
  const Recognizer = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognizer) {
    $('voice-status').textContent = '此浏览器不支持语音识别。可在此输入日程，或用 Chrome、Edge 打开。';
    $('transcript').focus();
    return;
  }
  const localRecognition = new Recognizer();
  recognition = localRecognition;
  const version = dialogVersion;
  localRecognition.lang = 'zh-CN';
  localRecognition.interimResults = true;
  localRecognition.maxAlternatives = 1;
  const preparedText = $('transcript').value.trim();
  $('record-label').textContent = '停止录音';
  $('voice-status').textContent = '正在等待麦克风…';
  localRecognition.onstart = () => {
    if (version === dialogVersion) $('voice-status').textContent = '正在听，请说出日期、时间和事项。';
  };
  localRecognition.onresult = event => {
    if (version !== dialogVersion) return;
    const transcript = [...event.results].map(result => result[0].transcript).join('');
    $('transcript').value = [preparedText, transcript].filter(Boolean).join(' ');
    if ([...event.results].some(result => result.isFinal)) state.source = 'voice';
  };
  localRecognition.onerror = event => {
    if (version !== dialogVersion) return;
    const fail = { 'not-allowed': '请允许麦克风权限后重试，或直接输入文字。', 'audio-capture': '找不到可用麦克风，可直接输入文字。', 'no-speech': '没有检测到语音，可以再试一次。', network: '浏览器的语音服务暂不可用，可直接输入文字。' };
    $('voice-status').textContent = fail[event.error] || '语音识别已中断，可直接输入文字。';
  };
  localRecognition.onend = () => {
    if (recognition === localRecognition) recognition = null;
    if (version !== dialogVersion) return;
    $('record-label').textContent = '开始录音';
    if (state.source === 'voice') $('voice-status').textContent = '可编辑识别文字，再点「识别日程」。';
  };
  try { localRecognition.start(); }
  catch {
    recognition = null;
    $('record-label').textContent = '开始录音';
    $('voice-status').textContent = '无法启动麦克风，可直接输入文字。';
  }
}

async function interpret() {
  const text = $('transcript').value.trim();
  if (!text) {
    $('voice-status').textContent = '请先录音或输入一段日程。';
    return;
  }
  const button = $('interpret');
  const version = dialogVersion;
  const warnings = $('parse-warnings');
  button.disabled = true;
  warnings.hidden = true;
  try {
    const result = await api('/api/parse', jsonRequest({ text, base_date: state.today }));
    if (version !== dialogVersion) return;
    const draft = result.draft;
    const explicitDeadline = /截止|最后期限|最晚|\bddl\b|deadline/i.test(draft.title);
    setDraft({ ...draft, kind: draft.kind || (explicitDeadline ? 'deadline' : 'event') });
    const messages = Array.isArray(result.warnings) ? result.warnings : [];
    warnings.replaceChildren(...messages.map(message => node('li', '', message)));
    warnings.hidden = !messages.length;
    $('voice-status').textContent = '请核对下面的日程，再保存。';
  } catch (error) {
    if (version === dialogVersion) $('voice-status').textContent = error.message;
  } finally {
    if (version === dialogVersion) button.disabled = false;
  }
}

async function saveEvent(event) {
  event.preventDefault();
  const button = $('save-event');
  const errorText = $('create-error');
  errorText.hidden = true;
  const kind = $('event-kind').value;
  const data = {
    title: $('event-title').value.trim(), category: $('event-category').value, all_day: $('event-all-day').checked, kind,
    start: $('event-start').value, end: kind !== 'deadline' && $('event-end').value || null, location: $('event-location').value.trim(),
    notes: $('event-notes').value.trim(), origin: state.source,
  };
  if (!data.title || (data.end && (data.all_day ? data.end < data.start : data.end <= data.start))) {
    errorText.textContent = data.title ? '结束时间应晚于开始时间。' : '请输入日程标题。';
    errorText.hidden = false;
    return;
  }
  button.disabled = true;
  const version = dialogVersion;
  const id = editId;
  try {
    await api(id ? eventPath(id) : '/api/events', jsonRequest(data, id ? 'PATCH' : 'POST'));
    if (version === dialogVersion) $('create-dialog').close();
    move(datePart(data.start));
    $('status').textContent = '日程已保存。';
  } catch (error) {
    if (version === dialogVersion) {
      errorText.textContent = error.message;
      errorText.hidden = false;
    }
  } finally {
    if (version === dialogVersion) button.disabled = false;
  }
}

$('search').addEventListener('input', event => { state.search = event.target.value.trim(); render(); });
$('show-invitations').addEventListener('change', render);
document.querySelectorAll('[data-category]').forEach(input => input.addEventListener('change', () => {
  if (input.checked) state.filters.add(input.dataset.category);
  else state.filters.delete(input.dataset.category);
  render();
}));
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => move(state.selected, button.dataset.view)));
$('today').addEventListener('click', () => move(datePart(localNow())));
$('return-home').addEventListener('click', () => {
  move(state.today, 'week');
  $('today').focus();
});
function movePeriod(direction) {
  const date = state.view === 'month' ? shiftMonth(state.selected, direction) : dayOffset(state.selected, direction * (state.view === 'day' ? 1 : 7));
  move(date);
}
$('previous').addEventListener('click', () => movePeriod(-1));
$('next').addEventListener('click', () => movePeriod(1));
$('mini-prev').addEventListener('click', () => { state.miniMonth = shiftMonth(state.miniMonth, -1); renderMini(); });
$('mini-next').addEventListener('click', () => { state.miniMonth = shiftMonth(state.miniMonth, 1); renderMini(); });
$('refresh').addEventListener('click', () => loadSchedule());
$('manual-add').addEventListener('click', () => openCreate('manual'));
$('voice-add').addEventListener('click', () => openCreate('voice'));
$('edit-event').addEventListener('click', () => {
  $('detail-dialog').close();
  openCreate('manual', detailEvent);
});
$('delete-event').addEventListener('click', deleteEvent);
$('record').addEventListener('click', record);
$('interpret').addEventListener('click', interpret);
$('event-all-day').addEventListener('change', event => useAllDay(event.target.checked));
$('event-kind').addEventListener('change', event => setKind(event.target.value));
$('create-form').addEventListener('submit', saveEvent);
document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => $(button.dataset.close).close()));
$('create-dialog').addEventListener('close', () => {
  dialogVersion += 1;
  if (recognition) { recognition.abort(); recognition = null; }
});

let refreshedAt = 0;
function refreshVisible() {
  if (document.visibilityState !== 'visible' || Date.now() - refreshedAt < 10000) return;
  refreshedAt = Date.now();
  loadSchedule(true);
}
window.addEventListener('focus', refreshVisible);
document.addEventListener('visibilitychange', refreshVisible);
window.setInterval(refreshVisible, 60000);
render();
loadSchedule();
