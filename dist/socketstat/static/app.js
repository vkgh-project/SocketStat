'use strict';
const labels = {online: 'Доступна', offline: 'Недоступна', unknown: 'Немає даних'};
const socketColors = ['var(--socket-1)', 'var(--socket-2)'];
const dateFormat = new Intl.DateTimeFormat('uk-UA', {timeZone: 'Europe/Kyiv', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});
const historyHours = 24;
const timelineHours = 2;
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
function timeline(devices, start, end) {
  const left = 48, right = 980, top = 48, rowHeight = 80, rowGap = 152;
  const bottom = top + Math.max(0, devices.length - 1) * rowGap + rowHeight;
  const axis = bottom + 28, chartHeight = axis + 56;
  const x = timestamp => left + (timestamp - start) / (end - start) * (right - left);
  const svg = svgElement('svg', {viewBox: `0 0 1000 ${chartHeight}`, role: 'img', 'aria-label': `Історія доступності: ${devices.map(device => device.name).join(', ')}. Кожна розетка в окремому ряду, одна над одною, зі спільною шкалою часу; 1 — доступна, 0 — недоступна; розриви — немає даних.`, class: 'timeline'});
  svg.append(svgElement('title', {}, `${devices.map(device => device.name).join(', ')}: ${date(start)} — ${date(end)}`));
  for (let i = 0; i <= 8; i++) {
    const tick = left + (right - left) * i / 8;
    svg.append(svgElement('line', {x1: tick, x2: tick, y1: top, y2: bottom, class: 'chart-grid'}));
  }
  svg.append(svgElement('path', {d: `M ${left} ${top} V ${axis} H ${right}`, class: 'chart-axis'}));
  devices.forEach((device, deviceIndex) => {
    const rowTop = top + deviceIndex * rowGap;
    const y = state => rowTop + (state === 'online' ? 0 : rowHeight);
    svg.append(svgElement('text', {x: left, y: rowTop - 18, class: 'timeline-device'}, device.name));
    for (const [value, level] of [[1, y('online')], [0, y('offline')]]) {
      svg.append(svgElement('line', {x1: left, x2: right, y1: level, y2: level, class: 'chart-grid'}),
        svgElement('text', {x: left - 16, y: level + 4, 'text-anchor': 'end', class: 'chart-value'}, value));
    }
    device.intervals.forEach((interval, index) => {
      if (interval.state === 'unknown') return;
      const a = x(interval.start), b = x(interval.end);
      const previous = device.intervals[index - 1];
      const connected = previous && previous.state !== 'unknown' && previous.end === interval.start;
      // Each socket has its own 0/1 row and gaps, with a shared time scale.
      const d = connected
        ? `M ${a} ${y(previous.state)} V ${y(interval.state)} H ${b}`
        : `M ${a} ${y(interval.state)} H ${b}`;
      const caption = `${device.name}: ${labels[interval.state]} (${interval.state === 'online' ? 1 : 0}): ${date(interval.start)} — ${date(interval.end)} (≈ ${duration(interval.end - interval.start)})`;
      const path = svgElement('path', {
        d, stroke: socketColors[deviceIndex % socketColors.length],
        class: `chart-step socket-line-${deviceIndex}`, tabindex: 0, 'aria-label': caption,
      });
      path.append(svgElement('title', {}, caption));
      svg.append(path);
    });
  });
  for (let i = 0; i <= 4; i++) {
    const tick = left + (right - left) * i / 4;
    svg.append(svgElement('line', {x1: tick, x2: tick, y1: axis, y2: axis + 5, class: 'chart-axis'}));
    svg.append(svgElement('text', {x: tick, y: axis + 25, 'text-anchor': i === 0 ? 'start' : i === 4 ? 'end' : 'middle'}, date(start + (end - start) * i / 4)));
  }
  svg.append(svgElement('text', {x: (left + right) / 2, y: chartHeight - 5, 'text-anchor': 'middle'}, 'Час · Київ'));
  return svg;
}
function chartPanel(devices, start, end) {
  const panel = el('section', undefined, 'panel');
  panel.append(el('h2', 'Доступність розеток · останні 2 години', 'chart-title'));
  const chart = el('div', undefined, 'chart-scroll');
  chart.append(timeline(devices, start, end));
  panel.append(chart);
  const legend = el('div', undefined, 'legend');
  devices.forEach((device, index) => legend.append(el('span', device.name, `socket-key-${index}`)));
  panel.append(legend, el('p', 'Кожна розетка показана в окремому ряду, одна над одною, зі спільною шкалою часу. 1 — доступна · 0 — недоступна · розрив лінії — немає даних.', 'hint'));
  return panel;
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
      svgElement('path', {d: 'M -1 1 L 5 7 M 3 -1 L 7 3', stroke: socketColors[index % socketColors.length], 'stroke-width': 2}));
    defs.append(offline);
  });
  return defs;
}
function hourlyPanel(series) {
  const panel = el('section', undefined, 'panel');
  panel.append(el('h2', 'Недоступність за годинами доби', 'chart-title'));
  const svg = svgElement('svg', {viewBox: '0 0 1000 300', class: 'hourly-chart', role: 'img', 'aria-label': 'Стовпчики: години доби 00–23, хвилини доступності суцільною заливкою, недоступності штрихуванням, без даних сірими крапками для кожної розетки.'});
  svg.append(chartPatterns('hourly', series));
  const left = 60, right = 980, top = 30, baseline = 232, group = (right - left) / 24;
  const maximum = Math.max(60, ...series.flatMap(device => device.hourly.map(h => h.total / 60)));
  const tick = Math.ceil(maximum / 4 / 15) * 15, ceiling = tick * 4;
  const height = minutes => minutes / ceiling * (baseline - top);
  svg.append(svgElement('text', {x: left, y: 15}, 'Хвилини'));
  for (let i = 0; i <= 4; i++) {
    const value = tick * i, y = baseline - height(value);
    svg.append(svgElement('line', {x1: left, x2: right, y1: y, y2: y, class: 'chart-grid'}),
      svgElement('text', {x: left - 10, y: y + 4, 'text-anchor': 'end'}, value));
  }
  for (let hour = 0; hour < 24; hour++) {
    svg.append(svgElement('text', {x: left + group * (hour + .5), y: 254, 'text-anchor': 'middle'}, String(hour).padStart(2, '0')));
    series.forEach((device, index) => {
      const cell = device.hourly[hour];
      const online = Math.max(0, cell.known - cell.offline) / 60;
      const offline = cell.offline / 60, missing = Math.max(0, cell.total - cell.known) / 60;
      const width = (group - 10) / series.length, x = left + hour * group + 5 + index * width;
      const caption = `${device.name}, ${String(hour).padStart(2, '0')}:00–${String(hour + 1).padStart(2, '0')}:00: доступна ≈ ${duration(online * 60)}; недоступна ≈ ${duration(cell.offline)}; немає даних ≈ ${duration(missing * 60)}; покриття ${cell.total ? Math.round(cell.known / cell.total * 100) : 0}%.`;
      if (online) svg.append(titledRect({x, y: baseline - height(online), width: width - 2, height: height(online), fill: socketColors[index % socketColors.length]}, caption));
      if (offline) svg.append(titledRect({x, y: baseline - height(online + offline), width: width - 2, height: height(offline), fill: `url(#hourly-offline-${index})`}, caption));
      if (missing) svg.append(titledRect({x, y: baseline - height(online + offline + missing), width: width - 2, height: height(missing), fill: 'url(#hourly-missing)'}, caption));
      if (!cell.total) svg.append(titledRect({x, y: baseline - 2, width: width - 2, height: 2, fill: 'url(#hourly-missing)'}, `${device.name}, ${hour}:00: година поза вибраним періодом.`));
    });
  }
  svg.append(svgElement('path', {d: `M ${left} ${top} V ${baseline} H ${right}`, class: 'chart-axis'}),
    svgElement('text', {x: 520, y: 286, 'text-anchor': 'middle'}, 'Година доби · Київ'));
  const chart = el('div', undefined, 'chart-scroll'); chart.append(svg);
  panel.append(chart, socketLegend(series, true), el('p', 'Кожен стовпчик містить хвилини доступності (суцільна заливка), недоступності (кольорове штрихування) та без даних (сірі крапки). Колір позначає розетку. Для кількох днів сума за одну годину доби може перевищувати 60 хв.', 'hint'));
  return panel;
}
function weeklyPanel(series, start, end) {
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
  const chart = el('div', undefined, 'chart-scroll');
  function draw() {
    const svg = svgElement('svg', {viewBox: '0 0 1000 280', class: 'weekly-chart', role: 'img', 'aria-label': 'Тижневий розклад: години по горизонталі, дні тижня по вертикалі, дві смуги в кожній клітинці — дві розетки. Доступність — суцільна заливка, недоступність — штрихування, немає даних — сірі крапки.'});
    svg.append(chartPatterns('weekly', series));
    const left = 88, top = 36, width = 888 / 24, row = 30;
    ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Нд'].forEach((label, dayIndex) => {
      const day = shiftDay(selectedWeek, dayIndex);
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
          if (cell.offline) svg.append(titledRect({x: x + (width - 4) * online / total, y, width: (width - 4) * cell.offline / total, height: 9, fill: `url(#weekly-offline-${index})`}, caption));
          if (missing) svg.append(titledRect({x: x + (width - 4) * (1 - missing / total), y, width: (width - 4) * missing / total, height: 9, fill: 'url(#weekly-missing)'}, caption));
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
    svg.append(svgElement('rect', {x: left, y: top, width: width * 24, height: row * 7, class: 'weekly-frame'}),
      svgElement('text', {x: left + width * 12, y: 273, 'text-anchor': 'middle'}, 'Година доби · Київ'));
    chart.replaceChildren(svg);
  }
  select.addEventListener('change', () => { selectedWeek = select.value; draw(); });
  header.append(select); draw();
  panel.append(header, chart, socketLegend(series, true), el('p', 'Кожна година містить дві смуги: зверху перша розетка, знизу друга. Доступність — суцільна заливка, недоступність — кольорове штрихування, немає даних — сірі крапки, зокрема поза вибраним періодом. Довжина частин показує тривалість станів, а не їх порядок у межах години. Це історія спостережень, а не прогноз.', 'hint'));
  return panel;
}

function card(device) {
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
    ['ДОСТУПНІСТЬ', stats.availability_percent === null ? '—' : `${stats.availability_percent}%`],
    ['НЕДОСТУПНА ≈', duration(stats.seconds.offline)],
    ['НАЙДОВШИЙ ПЕРІОД ≈', duration(stats.longest_offline_seconds)],
    ['ПОКРИТТЯ ДАНИМИ', `${stats.coverage_percent}%`],
  ];
  values.forEach(([label, value]) => {
    const metric = el('div', undefined, 'metric');
    metric.append(el('p', label), el('strong', value));
    metrics.append(metric);
  });
  panel.append(metrics);
  return panel;
}
function render(data) {
  document.querySelector('#demo').hidden = !data.demo;
  const series = aggregateCharts(data.devices, data.start, data.end);
  const timelineStart = data.end - timelineHours * 3600;
  const recentDevices = data.devices.map(device => ({...device, intervals: device.intervals
    .filter(interval => interval.end > timelineStart && interval.start < data.end)
    .map(interval => ({...interval, start: Math.max(interval.start, timelineStart), end: Math.min(interval.end, data.end)}))}));
  document.querySelector('#timeline').replaceChildren(chartPanel(recentDevices, timelineStart, data.end));
  document.querySelector('#hourly').replaceChildren(hourlyPanel(series));
  document.querySelector('#weekly').replaceChildren(weeklyPanel(series, data.start, data.end));
  document.querySelector('#devices').replaceChildren(...data.devices.map(device => card(device)));
  document.querySelector('#period').textContent = `Статистика за останню добу: ${date(data.start)} — ${date(data.end)}`;
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
