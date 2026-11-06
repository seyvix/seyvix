import assert from 'node:assert/strict'
import test from 'node:test'

import { formatDetailDate, formatMediaTime, isActiveJob, isFinishedJob, jobStatusLabel, objectCountSummary } from './format.ts'
import type { NoteObject } from '../../types'

test('job helpers cover snapshot and tagging/taxonomy status vocabularies', () => {
  assert.equal(isActiveJob({ status: 'pending' }), true)
  assert.equal(isActiveJob({ status: 'processing' }), true)
  for (const status of ['done', 'succeeded', 'failed', 'cancelled']) {
    assert.equal(isActiveJob({ status }), false, status)
  }
  assert.equal(isFinishedJob({ status: 'done' }), true)
  assert.equal(isFinishedJob({ status: 'succeeded' }), true)
  assert.equal(isFinishedJob({ status: 'cancelled' }), false)
  assert.equal(jobStatusLabel({ status: 'succeeded' }), 'Готово')
  assert.equal(jobStatusLabel({ status: 'cancelled' }), 'Пропущено')
  assert.equal(jobStatusLabel({ status: 'pending' }), 'В очереди')
})

test('formatters handle invalid input', () => {
  assert.equal(formatDetailDate('not a date'), null)
  assert.equal(formatDetailDate(null), null)
  assert.equal(formatMediaTime(Number.NaN), '0:00')
  assert.equal(formatMediaTime(3725), '1:02:05')
  assert.equal(formatMediaTime(65), '1:05')
})

test('object counts follow the fixed type order', () => {
  const objects = ['video', 'text', 'image', 'text'].map((type, index) => ({
    id: String(index),
    type,
    content: '',
    createdAt: '',
  })) as NoteObject[]
  assert.deepEqual(objectCountSummary(objects), [
    { type: 'text', count: 2 },
    { type: 'image', count: 1 },
    { type: 'video', count: 1 },
  ])
})
