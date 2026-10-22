'use strict';
const labels = {online: 'Доступна', offline: 'Недоступна', unknown: 'Немає даних'};
const socketColors = ['var(--socket-1)', 'var(--socket-2)'];
const dateFormat = new Intl.DateTimeFormat('uk-UA', {timeZone: 'Europe/Kyiv', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});
const historyHours = 24;
let loading = false;
const date = value => dateFormat.format(new Date(value * 1000));
function duration(seconds) {
  if (seconds < 60) return `${Math.round(seconds)} с`;
  const minutes = Math.floor(seconds / 60);
  return minutes < 60 ? `${minutes} хв` : `${Math.floor(minutes / 60)} год ${minutes % 60} хв`;
}
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function svgElement(tag, attrs, text) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
  if (text !== undefined) node.textContent = text;
  return node;
}
const localPartsFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Europe/Kyiv', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', hourCycle: 'h23',
});
let selectedWeek = null;
function localParts(timestamp) {
  const parts = Object.fromEntries(localPartsFormat.formatToParts(new Date(timestamp * 1000))
    .filter(part => part.type !== 'literal').map(part => [part.type, part.value]));
  return {day: `${parts.year}-${parts.month}-${parts.day}`, hour: Number(parts.hour)};
}
function shiftDay(day, count) {
  const value = new Date(`${day}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() + count);
  return value.toISOString().slice(0, 10);
}
function monday(day) {
  return shiftDay(day, -((new Date(`${day}T00:00:00Z`).getUTCDay() + 6) % 7));
}
function shortDay(day) { return `${day.slice(8, 10)}.${day.slice(5, 7)}`; }
function aggregateCharts(devices, start, end) {
  // Split by actual UTC minutes, then group by Kyiv calendar time. Repeated DST
  // hours accumulate both occurrences; partial minute boundaries stay fractional.
  const slots = [];
  for (let t = start; t < end;) {
    const next = Math.min(end, (Math.floor(t / 60) + 1) * 60);
    slots.push({start: t, end: next, ...localParts(t)});
    t = next;
  }
  return devices.map(device => {
    const hourly = Array.from({length: 24}, () => ({offline: 0, known: 0, total: 0}));
    const calendar = new Map();
    let index = 0;
    slots.forEach(slot => {
      const key = `${slot.day}/${slot.hour}`;
      if (!calendar.has(key)) calendar.set(key, {offline: 0, known: 0, total: 0});
      const cell = calendar.get(key), hour = hourly[slot.hour];
      cell.total += slot.end - slot.start;
      hour.total += slot.end - slot.start;
      while (index < device.intervals.length && device.intervals[index].end <= slot.start) index++;
      for (let j = index; j < device.intervals.length && device.intervals[j].start < slot.end; j++) {
        const interval = device.intervals[j];
        const seconds = Math.max(0, Math.min(slot.end, interval.end) - Math.max(slot.start, interval.start));
        if (interval.state !== 'unknown') { cell.known += seconds; hour.known += seconds; }
        if (interval.state === 'offline') { cell.offline += seconds; hour.offline += seconds; }
      }
    });
    return {name: device.name, hourly, calendar};
  });
}
function socketLegend(devices, missing=false) {
  const legend = el('div', undefined, 'legend');
  devices.forEach((device, index) => {
    legend.append(el('span', `${device.name}: доступна`, `socket-key-${index} online-key`),
      el('span', `${device.name}: недоступна`, `socket-key-${index} offline-key`));
  });
  if (missing) legend.append(el('span', 'Немає даних', 'missing-key'));
  return legend;
}
function titledRect(attrs, caption) {
  const rect = svgElement('rect', {...attrs, tabindex: 0, 'aria-label': caption});
  rect.append(svgElement('title', {}, caption));
  return rect;
}
function chartPatterns(prefix, series) {
  const defs = svgElement('defs', {});
  const pattern = svgElement('pattern', {id: `${prefix}-missing`, width: 6, height: 6, patternUnits: 'userSpaceOnUse'});
  pattern.append(svgElement('rect', {width: 6, height: 6, fill: 'var(--chart-missing-bg)'}),
    svgElement('circle', {cx: 3, cy: 3, r: 1, fill: 'var(--chart-missing-line)'}));
  defs.append(pattern);
  series.forEach((device, index) => {
    const offline = svgElement('pattern', {id: `${prefix}-offline-${index}`, width: 6, height: 6, patternUnits: 'userSpaceOnUse'});
    offline.append(svgElement('rect', {width: 6, height: 6, fill: 'var(--paper)'}),
      svgElement('path', {d: 'M -1 1 L 5 7 M 3 -1 L 7 3', stroke: 'var(--offline)', 'stroke-width': 2}));
    defs.append(offline);
  });
  return defs;
}
function weeklyPanel(series, start, end, prefix = 'weekly') {
  const panel = el('section', undefined, 'panel');
  const header = el('div', undefined, 'section-head');
  header.append(el('h2', 'Тижневий розклад', 'chart-title'));
  const weeks = [];
  for (let day = monday(localParts(start).day), last = monday(localParts(end - .001).day); day <= last; day = shiftDay(day, 7)) weeks.push(day);
  if (!weeks.includes(selectedWeek)) selectedWeek = weeks[weeks.length - 1];
  const select = el('select', undefined, 'week-select');
  select.setAttribute('aria-label', 'Тиждень розкладу');
  weeks.forEach(week => {
    const option = el('option', `${shortDay(week)}–${shortDay(shiftDay(week, 6))}`);
    option.value = week; option.selected = week === selectedWeek; select.append(option);
  });
  select.value = selectedWeek;
  const chart = el('div', undefined, 'chart-scroll');
  function draw() {
    const svg = svgElement('svg', {viewBox: '0 0 1000 256', class: 'weekly-chart', role: 'img', 'aria-label': 'Тижневий розклад: години по горизонталі, дні тижня по вертикалі, дві смуги в кожній клітинці — дві розетки. Доступність — суцільна заливка, недоступність — штрихування, немає даних — сірі крапки.'});
    svg.append(chartPatterns(prefix, series));
    const left = 88, top = 36, width = 888 / 24, row = 30;
    ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Нд'].forEach((label, dayIndex) => {
      const day = shiftDay(select.value, dayIndex);
      const labelY = top + dayIndex * row;
      svg.append(svgElement('text', {x: left - 12, y: labelY + 11, 'text-anchor': 'end'}, label),
        svgElement('text', {x: left - 12, y: labelY + 24, 'text-anchor': 'end'}, shortDay(day)));
      for (let hour = 0; hour < 24; hour++) {
        series.forEach((device, index) => {
          const cell = device.calendar.get(`${day}/${hour}`) || {offline: 0, known: 0, total: 0};
          const total = Math.max(3600, cell.total), missing = Math.max(0, total - cell.known);
          const online = Math.max(0, cell.known - cell.offline);
          const x = left + hour * width + 2, y = top + dayIndex * row + 4 + index * 11;
          const caption = `${device.name}, ${shortDay(day)} ${String(hour).padStart(2, '0')}:00: доступна ≈ ${duration(online)}; недоступна ≈ ${duration(cell.offline)}; немає даних ≈ ${duration(missing)}. Довжина частини смуги — тривалість стану, без відображення порядку подій у межах години.`;
          if (online) svg.append(titledRect({x, y, width: (width - 4) * online / total, height: 9, fill: socketColors[index % socketColors.length]}, caption));
          if (cell.offline) svg.append(titledRect({x: x + (width - 4) * online / total, y, width: (width - 4) * cell.offline / total, height: 9, fill: `url(#${prefix}-offline-${index})`}, caption));
          if (missing) svg.append(titledRect({x: x + (width - 4) * (1 - missing / total), y, width: (width - 4) * missing / total, height: 9, fill: `url(#${prefix}-missing)`}, caption));
        });
      }
    });
    for (let hour = 0; hour <= 24; hour++) {
      const x = left + hour * width;
      svg.append(svgElement('line', {x1: x, x2: x, y1: top, y2: top + row * 7, class: 'chart-grid'}),
        svgElement('text', {x, y: top - 12, 'text-anchor': 'middle'}, String(hour).padStart(2, '0')));
    }
    for (let day = 0; day <= 7; day++) {
      const y = top + day * row;
      svg.append(svgElement('line', {x1: left, x2: left + width * 24, y1: y, y2: y, class: 'chart-grid'}));
    }
    svg.append(svgElement('rect', {x: left, y: top, width: width * 24, height: row * 7, class: 'weekly-frame'}));
    chart.replaceChildren(svg);
  }
  select.addEventListener('change', () => { selectedWeek = select.value; draw(); });
  header.append(select); draw();
  panel.append(header, chart, socketLegend(series, true), el('p', 'Кожна година містить дві смуги: зверху перша розетка, знизу друга. Доступність — суцільна заливка, недоступність — кольорове штрихування, немає даних — сірі крапки. Розклад використовує історію останніх 14 діб; майбутні години та давніші дані не заповнюються. Довжина частин показує тривалість станів, а не їх порядок у межах години. Це історія спостережень, а не прогноз.', 'hint'));
  return panel;
}

function dailyTimeline(device, today, now) {
  const section = el('div', undefined, 'daily-timeline');
  const svg = svgElement('svg', {viewBox: '0 0 1000 90', class: 'daily-bar', role: 'img',
    'aria-label': `${device.name}: доступність за поточний день від 00:00 до 23:59. Зелений — доступна, кораловий — недоступна, сірий — немає даних, темний — майбутній час.`});
  const x = timestamp => (timestamp - today.start) / (today.end - today.start) * 1000;
  const observedEnd = Math.max(today.start, Math.min(now, today.end));
  svg.append(svgElement('rect', {x: 0, y: 8, width: 1000, height: 32, class: 'daily-future'}));
  svg.append(titledRect({x: 0, y: 8, width: x(observedEnd), height: 32, class: 'daily-unknown'}, 'Немає даних'));
  device.today_intervals.forEach(interval => {
    const start = Math.max(today.start, interval.start), end = Math.min(observedEnd, interval.end);
    if (end <= start) return;
    svg.append(titledRect({x: x(start), y: 8, width: x(end) - x(start), height: 32,
      class: `daily-${interval.state}`}, `${labels[interval.state]}: ${date(start)} — ${date(end)} (≈ ${duration(end - start)})`));
  });
  // UTC positions preserve actual elapsed time on 23- and 25-hour days.
  const ticks = [{timestamp: today.start, label: '00:00'}];
  for (let timestamp = today.start + 3600; timestamp < today.end; timestamp += 3600) {
    const hour = localParts(timestamp).hour;
    if ([6, 12, 18].includes(hour)) ticks.push({timestamp, label: `${String(hour).padStart(2, '0')}:00`});
  }
  ticks.push({timestamp: today.end, label: '23:59'});
  ticks.forEach(({timestamp, label}, index) => {
    svg.append(svgElement('line', {x1: x(timestamp), x2: x(timestamp), y1: 43, y2: 50, class: 'chart-axis'}),
      svgElement('text', {x: x(timestamp), y: 78, 'text-anchor': index === 0 ? 'start' : index === ticks.length - 1 ? 'end' : 'middle'}, label));
  });
  const marker = svgElement('line', {x1: x(observedEnd), x2: x(observedEnd), y1: 3, y2: 45, class: 'daily-now'});
  marker.append(svgElement('title', {}, `Станом на ${date(observedEnd)}`));
  svg.append(marker);
  const legend = el('div', undefined, 'legend daily-legend');
  [['online', 'Доступна'], ['offline', 'Недоступна'], ['unknown', 'Немає даних'], ['future', 'Майбутній час']]
    .forEach(([state, label]) => legend.append(el('span', label, `daily-key-${state}`)));
  section.append(svg, legend);
  return section;
}
function card(device, today, now) {
  const panel = el('section', undefined, 'panel');
  const head = el('div', undefined, 'section-head');
  head.append(el('h2', device.name), el('span', labels[device.state], `badge ${device.state}`));
  panel.append(head);
  let checked = device.last_checked_at ? `Остання перевірка: ${date(device.last_checked_at)}` : 'Ще немає перевірок';
  if (device.error_code) checked += ` · Помилка: ${device.error_code}`;
  panel.append(el('p', checked, 'last'));
  const stats = device.stats;
  const metrics = el('div', undefined, 'metrics');
  const values = [
    ['Доступність', stats.availability_percent === null ? '—' : `${stats.availability_percent}%`],
    ['Недоступна ≈', duration(stats.seconds.offline)],
    ['Покриття даними', `${stats.coverage_percent}%`],
  ];
  values.forEach(([label, value]) => {
    const metric = el('div', undefined, 'metric');
    metric.append(el('p', label), el('strong', value));
    metrics.append(metric);
  });
  const longest = el('p', 'Найдовший період недоступності ≈ ', 'metric-secondary');
  longest.append(el('strong', duration(stats.longest_offline_seconds)));
  panel.append(metrics, longest, dailyTimeline(device, today, now));
  return panel;
}
function overallStatus(devices) {
  const offline = devices.filter(device => device.state === 'offline').length;
  const unknown = devices.filter(device => device.state === 'unknown').length;
  if (!devices.length) return {state: 'unknown', text: 'Ще немає даних про розетки'};
  if (unknown) return {state: 'unknown', text: 'Є розетки без актуальних даних'};
  if (offline) return {state: 'offline', text: offline === devices.length ? 'Обидві розетки недоступні' : 'Одна розетка недоступна'};
  return {state: 'online', text: 'Обидві розетки доступні'};
}
function render(data) {
  document.querySelector('#demo').hidden = !data.demo;
  const status = overallStatus(data.devices);
  const summary = document.querySelector('#summary');
  summary.className = `summary ${status.state}`;
  summary.replaceChildren(el('strong', status.text));
  const weekly = data.weekly;
  const series = aggregateCharts(weekly.devices, weekly.start, weekly.end);
  document.querySelector('#weekly').replaceChildren(weeklyPanel(series, weekly.start, weekly.end));
  document.querySelector('#devices').replaceChildren(...data.devices.map(device => card(device, data.today, data.end)));
  const outages = [];
  data.devices.forEach(device => device.intervals.filter(i => i.state === 'offline').forEach(interval => outages.push({...interval, name: device.name})));
  outages.sort((a, b) => b.start - a.start);
  const body = document.querySelector('#outages');
  body.replaceChildren();
  outages.forEach(interval => {
    const row = el('tr');
    const start = interval.start === data.start ? `${date(interval.start)} · межа періоду` : date(interval.start);
    const end = interval.end === data.end ? 'Триває за останніми даними' : date(interval.end);
    [interval.name, start, end, duration(interval.end - interval.start)].forEach(value => row.append(el('td', value)));
    body.append(row);
  });
  if (!outages.length) {
    const cell = el('td', 'За останню добу недоступність не зафіксована. Перевірте покриття даними.');
    cell.colSpan = 4;
    const row = el('tr'); row.append(cell); body.append(row);
  }
}
async function refresh() {
  if (loading) return;
  loading = true;
  const button = document.querySelector('#refresh');
  button.disabled = true;
  const error = document.querySelector('#error');
  try {
    const response = await fetch(`/api/dashboard?hours=${historyHours}`, {cache: 'no-store', signal: AbortSignal.timeout(15000)});
    if (!response.ok) throw new Error('request_failed');
    render(await response.json());
    error.hidden = true;
    document.querySelector('#updated').textContent = `Оновлено ${new Intl.DateTimeFormat('uk-UA', {timeZone: 'Europe/Kyiv', hour: '2-digit', minute: '2-digit', second: '2-digit'}).format(new Date())}`;
  } catch (_) {
    error.textContent = 'Не вдалося оновити дані. Показана історія може бути застарілою. Повторна спроба — через 30 секунд.';
    error.hidden = false;
  } finally {
    loading = false;
    button.disabled = false;
  }
}
function setupTabs() {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  function activate(tab, focus = false) {
    tabs.forEach(item => {
      const selected = item === tab;
      item.setAttribute('aria-selected', String(selected));
      item.tabIndex = selected ? 0 : -1;
      document.getElementById(item.getAttribute('aria-controls')).hidden = !selected;
    });
    if (focus) tab.focus();
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => activate(tab));
    tab.addEventListener('keydown', event => {
      let target;
      if (event.key === 'ArrowRight') target = (index + 1) % tabs.length;
      if (event.key === 'ArrowLeft') target = (index - 1 + tabs.length) % tabs.length;
      if (event.key === 'Home') target = 0;
      if (event.key === 'End') target = tabs.length - 1;
      if (target !== undefined) {
        event.preventDefault();
        activate(tabs[target], true);
      }
    });
  });
}

document.querySelector('#refresh').addEventListener('click', refresh);
setupTabs();
refresh();
setInterval(refresh, 30000);
