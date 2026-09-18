import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createI18n} from '../src/i18n/messages.ts';

test('activity dates keep the catalog calendar day across timezones', () => {
  const {date} = createI18n('en');

  // A ride started just after local midnight must not fall back to the UTC day.
  assert.equal(date('2026-08-09 00:30:00+02'), 'Aug 9, 2026');
  assert.equal(date('2026-08-09T00:30:00+02:00'), 'Aug 9, 2026');
  assert.equal(date('2026-08-09'), 'Aug 9, 2026');
  assert.equal(date('2026-08-09 06:01:51+02'), 'Aug 9, 2026');
});

test('localized dates format the same calendar day', () => {
  const {date} = createI18n('pt-BR');

  assert.equal(date('2026-08-09 00:30:00+02'), '9 de ago. de 2026');
});
