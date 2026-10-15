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

test('hourly and weekly panels render even when all observations are missing', () => {
  const context = load(), start = seconds('2026-10-15T00:00:00Z'), end = start + 3600;
  const series = context.aggregateCharts([{name: 'one', intervals: []}, {name: 'two', intervals: []}], start, end);
  assert.equal(context.hourlyPanel(series).tag, 'section');
  assert.equal(context.weeklyPanel(series, start, end).tag, 'section');
});

test('tabs show one panel, support keyboard navigation and keep selection during data rendering', () => {
  const context = load();
  const panels = {}, tabs = ['timeline', 'hourly', 'weekly', 'devices', 'outages'].map((name, index) => {
    const tab = element('button');
    tab.setAttribute('aria-controls', `panel-${name}`);
    tab.setAttribute('aria-selected', String(index === 0));
    tab.tabIndex = index === 0 ? 0 : -1;
    panels[`panel-${name}`] = {hidden: index !== 0};
    return tab;
  });
  const nodes = Object.fromEntries(['demo', 'timeline', 'hourly', 'weekly', 'devices', 'period', 'outages'].map(id => [`#${id}`, element('div')]));
  context.document.querySelectorAll = () => tabs;
  context.document.getElementById = id => panels[id];
  context.document.querySelector = id => nodes[id];
  context.setupTabs();
  tabs[3].listeners.click();
  assert.equal(panels['panel-devices'].hidden, false);
  assert.equal(Object.values(panels).filter(panel => !panel.hidden).length, 1);
  assert.equal(tabs[3].attrs['aria-selected'], 'true');
  assert.equal(tabs[0].tabIndex, -1);

  const start = seconds('2026-10-15T00:00:00Z');
  context.render({demo: true, start, end: start + 3600, devices: []});
  assert.equal(panels['panel-devices'].hidden, false);
  assert.equal(tabs[3].attrs['aria-selected'], 'true');
  assert.equal(nodes['#timeline'].children.length, 1);
  assert.equal(nodes['#hourly'].children.length, 1);
  assert.equal(nodes['#weekly'].children.length, 1);

  let prevented = false;
  const key = (tab, key) => tab.listeners.keydown({key, preventDefault() { prevented = true; }});
  key(tabs[3], 'End');
  assert.equal(panels['panel-outages'].hidden, false);
  assert.equal(tabs[4].focused, true);
  assert.equal(prevented, true);
  key(tabs[4], 'ArrowRight');
  assert.equal(panels['panel-timeline'].hidden, false);
  key(tabs[0], 'ArrowLeft');
  assert.equal(panels['panel-outages'].hidden, false);
  key(tabs[4], 'Home');
  assert.equal(panels['panel-timeline'].hidden, false);
  assert.equal(Object.values(panels).filter(panel => !panel.hidden).length, 1);
});
