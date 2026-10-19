// Optional frontend checks: node --test tests/charts.test.cjs (Node 18+).
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
function element(tag) {
  return {tag, attrs: {}, children: [], listeners: {},
    setAttribute(key, value) { this.attrs[key] = value; },
    getAttribute(key) { return this.attrs[key]; },
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    addEventListener(name, listener) { this.listeners[name] = listener; },
    focus() { this.focused = true; },
  };
}
function load() {
  const context = {Intl, Date, document: {createElement: element, createElementNS: (_, tag) => element(tag)}};
  vm.createContext(context);
  const source = fs.readFileSync(path.join(__dirname, '../socketstat/static/app.js'), 'utf8');
  vm.runInContext(source.split("document.querySelector('#refresh').addEventListener")[0], context);
  return context;
}
const seconds = date => Date.parse(date) / 1000;

test('splits downtime at Kyiv midnight and preserves independent socket states', () => {
  const context = load();
  const start = seconds('2026-10-14T20:30:00Z'), end = start + 3600;
  const series = context.aggregateCharts([
    {name: 'one', intervals: [{start, end, state: 'offline'}]},
    {name: 'two', intervals: [{start, end, state: 'unknown'}]},
  ], start, end);
  assert.equal(series[0].calendar.get('2026-10-14/23').offline, 1800);
  assert.equal(series[0].calendar.get('2026-10-15/0').offline, 1800);
  assert.equal(series[0].hourly[23].offline, 1800);
  assert.equal(series[1].hourly[23].offline, 0);
  assert.equal(series[1].hourly[23].known, 0);
  assert.equal(series[1].hourly[23].total, 1800);
});

test('counts fractional minutes and implicit gaps without inventing downtime', () => {
  const context = load(), start = seconds('2026-10-15T10:00:15Z'), end = start + 120;
  const result = context.aggregateCharts([{name: 'one', intervals: [
    {start, end: start + 30.5, state: 'offline'},
    {start: start + 60, end, state: 'online'},
  ]}], start, end)[0].hourly[13];
  assert.equal(result.total, 120);
  assert.equal(result.offline, 30.5);
  assert.equal(result.known, 90.5);
});

test('repeated autumn hour contains both actual hours', () => {
  const context = load(), start = seconds('2026-10-25T00:00:00Z'), end = start + 7200;
  const result = context.aggregateCharts([{name: 'one', intervals: [{start, end, state: 'offline'}]}], start, end)[0];
  assert.equal(result.hourly[3].offline, 7200);
  assert.equal(result.calendar.get('2026-10-25/3').total, 7200);
});

test('spring clock change skips the nonexistent hour', () => {
  const context = load(), start = seconds('2026-03-29T00:00:00Z'), end = start + 7200;
  const result = context.aggregateCharts([{name: 'one', intervals: [{start, end, state: 'online'}]}], start, end)[0];
  assert.equal(result.hourly[2].known, 3600);
  assert.equal(result.hourly[3].total, 0);
  assert.equal(result.hourly[4].known, 3600);
});

test('weekly panel renders even when all observations are missing', () => {
  const context = load(), start = seconds('2026-10-15T00:00:00Z'), end = start + 3600;
  const series = context.aggregateCharts([{name: 'one', intervals: []}, {name: 'two', intervals: []}], start, end);
  assert.equal(context.weeklyPanel(series, start, end).tag, 'section');
});

test('summary distinguishes online, offline and missing observations', () => {
  const context = load();
  const status = states => context.overallStatus(states.map(state => ({state})));
  assert.equal(status(['online', 'online']).state, 'online');
  assert.equal(status(['online', 'offline']).state, 'offline');
  assert.equal(status(['offline', 'offline']).text, 'Обидві розетки недоступні');
  assert.equal(status(['online', 'unknown']).state, 'unknown');
  assert.equal(status(['offline', 'unknown']).state, 'unknown');
  assert.equal(status([]).state, 'unknown');
});

test('weekly overview uses its own SVG pattern IDs', () => {
  const context = load(), start = seconds('2026-10-15T00:00:00Z'), end = start + 3600;
  const series = context.aggregateCharts([{name: 'one', intervals: [{start, end, state: 'offline'}]}], start, end);
  const overview = context.weeklyPanel(series, start, end, 'overview');
  const svg = overview.children[1].children[0];
  const ids = svg.children[0].children.map(node => node.attrs.id);
  assert.ok(ids.includes('overview-missing'));
  assert.ok(ids.includes('overview-offline-0'));
  assert.ok(svg.children.some(node => node.attrs.fill === 'url(#overview-offline-0)'));
  assert.ok(svg.children.some(node => node.attrs.fill === 'url(#overview-missing)'));
});

test('daily bar clips intervals at midnight and now, with separate missing and future states', () => {
  const context = load(), start = seconds('2026-10-14T21:00:00Z');
  const now = start + 43200, end = start + 86400;
  const intervals = [
    {start: start - 3600, end: start + 3600, state: 'online'},
    {start: start + 3600, end: start + 7200, state: 'offline'},
    {start: start + 7200, end: start + 10800, state: 'unknown'},
    {start: start + 40000, end: end + 3600, state: 'online'},
    {start: end, end: end + 3600, state: 'offline'},
  ];
  const bar = context.dailyTimeline({name: 'one', today_intervals: intervals}, {start, end}, now).children[0];
  const rects = bar.children.filter(node => node.tag === 'rect');
  assert.equal(rects[0].attrs.class, 'daily-future');
  assert.equal(rects[0].attrs.width, 1000);
  assert.equal(rects[1].attrs.class, 'daily-unknown');
  assert.equal(rects[1].attrs.width, 500);
  assert.equal(rects[2].attrs.x, 0);
  assert.equal(rects[2].attrs.class, 'daily-online');
  assert.equal(rects[3].attrs.class, 'daily-offline');
  assert.equal(rects[4].attrs.class, 'daily-unknown');
  assert.equal(rects[5].attrs.x + rects[5].attrs.width, 500);
  assert.equal(rects.length, 6);
  assert.equal(intervals[0].start, start - 3600);
  assert.ok(bar.children.some(node => node.textContent === '23:59'));
});

test('daily bar places clock ticks by elapsed time on a 25-hour day', () => {
  const context = load(), start = seconds('2026-10-24T21:00:00Z'), end = seconds('2026-10-25T22:00:00Z');
  const bar = context.dailyTimeline({name: 'one', today_intervals: []}, {start, end}, end).children[0];
  const noon = bar.children.find(node => node.textContent === '12:00');
  assert.equal(noon.attrs.x, 13 / 25 * 1000);
});

test('tabs show one panel, support keyboard navigation and keep selection during data rendering', () => {
  const context = load();
  const panels = {}, tabs = ['devices', 'weekly', 'outages'].map((name, index) => {
    const tab = element('button');
    tab.setAttribute('aria-controls', `panel-${name}`);
    tab.setAttribute('aria-selected', String(index === 0));
    tab.tabIndex = index === 0 ? 0 : -1;
    panels[`panel-${name}`] = {hidden: index !== 0};
    return tab;
  });
  const nodes = Object.fromEntries(['demo', 'summary', 'weekly', 'devices', 'outages'].map(id => [`#${id}`, element('div')]));
  context.document.querySelectorAll = () => tabs;
  context.document.getElementById = id => panels[id];
  context.document.querySelector = id => nodes[id];
  context.setupTabs();
  tabs[1].listeners.click();
  assert.equal(panels['panel-weekly'].hidden, false);
  tabs[0].listeners.click();
  assert.equal(panels['panel-devices'].hidden, false);
  assert.equal(Object.values(panels).filter(panel => !panel.hidden).length, 1);
  assert.equal(tabs[0].attrs['aria-selected'], 'true');
  assert.equal(tabs[1].tabIndex, -1);

  const start = seconds('2026-10-15T00:00:00Z');
  context.render({demo: true, start, end: start + 3600, devices: []});
  assert.equal(panels['panel-devices'].hidden, false);
  assert.equal(tabs[0].attrs['aria-selected'], 'true');
  assert.equal(nodes['#weekly'].children.length, 1);

  let prevented = false;
  const key = (tab, key) => tab.listeners.keydown({key, preventDefault() { prevented = true; }});
  key(tabs[1], 'End');
  assert.equal(panels['panel-outages'].hidden, false);
  assert.equal(tabs[2].focused, true);
  assert.equal(prevented, true);
  key(tabs[2], 'ArrowRight');
  assert.equal(panels['panel-devices'].hidden, false);
  key(tabs[0], 'ArrowLeft');
  assert.equal(panels['panel-outages'].hidden, false);
  key(tabs[2], 'Home');
  assert.equal(panels['panel-devices'].hidden, false);
  assert.equal(Object.values(panels).filter(panel => !panel.hidden).length, 1);
});
